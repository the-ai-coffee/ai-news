"""Étape 3 : regroupement des articles retenus par événement, avec score d'impact."""

from __future__ import annotations

import json
import logging
from typing import Any

from ai_news.llm import LLMClient, LLMError
from ai_news.models import AssessedArticle, EventCluster
from ai_news.prompts import CLUSTER_SYSTEM

log = logging.getLogger(__name__)

MAX_ARTICLES = 150
DESCRIPTION_CHARS = 300


class ClusterError(Exception):
    """Regroupement impossible : sans lui, aucune édition fiable n'est possible."""


def _payload(articles: list[AssessedArticle], previous_titles: list[str]) -> str:
    return json.dumps(
        {
            "previous_edition_titles": previous_titles,
            "articles": [
                {
                    "id": a.article.id,
                    "outlet": a.assessment.outlet,
                    "title": a.article.title,
                    "description": (a.article.description or a.article.text)[:DESCRIPTION_CHARS],
                }
                for a in articles
            ],
        },
        ensure_ascii=False,
    )


def _parse(raw: dict[str, Any], known_ids: set[str]) -> list[EventCluster]:
    clusters: list[EventCluster] = []
    assigned: set[str] = set()
    for item in raw.get("events", []):
        if not isinstance(item, dict):
            continue
        ids = [
            str(i)
            for i in item.get("article_ids", [])
            if str(i) in known_ids and str(i) not in assigned
        ]
        ids = list(dict.fromkeys(ids))
        if not ids:
            continue
        try:
            impact = min(1.0, max(0.0, float(item.get("impact", 0))))
        except (TypeError, ValueError):
            impact = 0.0
        assigned.update(ids)
        clusters.append(
            EventCluster(
                id=f"e{len(clusters) + 1:03d}",
                label=str(item.get("label") or "Événement sans titre").strip(),
                article_ids=ids,
                impact=impact,
                impact_reason=str(item.get("impact_reason") or "").strip(),
                repeat_without_new_facts=bool(item.get("repeat_without_new_facts", False)),
            )
        )
    return clusters


def cluster(
    llm: LLMClient, retained: list[AssessedArticle], previous_titles: list[str]
) -> list[EventCluster]:
    if not retained:
        return []
    # Au-delà du plafond, on garde les articles les plus fiables.
    pool = sorted(retained, key=lambda a: a.assessment.reliability, reverse=True)[:MAX_ARTICLES]
    known = {a.article.id for a in pool}
    payload = _payload(pool, previous_titles)
    last_error = ""
    for attempt in (1, 2):
        try:
            clusters = _parse(llm.complete_json(CLUSTER_SYSTEM, payload), known)
        except LLMError as exc:
            last_error = str(exc)
            log.warning("regroupement : essai %d en échec (%s)", attempt, exc)
            continue
        log.info("regroupement : %d événements", len(clusters))
        return clusters
    raise ClusterError(f"regroupement impossible : {last_error}")
