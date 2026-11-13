"""Étape 2 : évaluation de la fiabilité de chaque article par le LLM, par lots."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from ai_news.budget import BudgetExceededError
from ai_news.llm import LLMClient, LLMError
from ai_news.models import Article, AssessedArticle, Assessment, SourceStatus
from ai_news.prompts import ASSESS_SYSTEM

log = logging.getLogger(__name__)

EXCERPT_CHARS = 1500


def _payload(batch: list[Article]) -> str:
    items = [
        {
            "id": a.id,
            "domain": a.domain,
            "title": a.title,
            "description": a.description,
            "excerpt": a.text[:EXCERPT_CHARS],
        }
        for a in batch
    ]
    return json.dumps({"articles": items}, ensure_ascii=False)


def _parse(raw: dict[str, Any]) -> dict[str, tuple[Assessment, bool]]:
    parsed: dict[str, tuple[Assessment, bool]] = {}
    for item in raw.get("articles", []):
        if not isinstance(item, dict) or "id" not in item:
            continue
        try:
            assessment = Assessment(
                reliability=float(item.get("reliability", 0)),
                reason=str(item.get("reason", "")).strip() or "Aucune justification fournie.",
                outlet=str(item.get("outlet") or "").strip(),
                language=str(item.get("language") or ""),
                country=str(item.get("country") or ""),
                wire_agency=(str(item["wire_agency"]).strip() or None)
                if item.get("wire_agency")
                else None,
            )
        except (ValidationError, TypeError, ValueError):
            continue
        parsed[str(item["id"])] = (assessment, bool(item.get("is_opinion", False)))
    return parsed


def _assess_batch(llm: LLMClient, batch: list[Article]) -> dict[str, tuple[Assessment, bool]]:
    for attempt in (1, 2):
        try:
            return _parse(llm.complete_json(ASSESS_SYSTEM, _payload(batch)))
        except LLMError as exc:
            log.warning("évaluation : essai %d en échec (%s)", attempt, exc)
    return {}


def assess(
    llm: LLMClient, articles: list[Article], *, batch_size: int, min_reliability: float
) -> tuple[list[AssessedArticle], list[str]]:
    results: list[AssessedArticle] = []
    incidents: list[str] = []
    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        try:
            verdicts = _assess_batch(llm, batch)
        except BudgetExceededError as exc:
            incidents.append(f"Évaluation interrompue : {exc}")
            # Tout le reste est écarté faute d'évaluation.
            _reject_unassessed(articles[start:], results, "Non évalué : budget épuisé.")
            break
        for article in batch:
            verdict = verdicts.get(article.id)
            if verdict is None:
                _reject_unassessed([article], results, "Non évalué : réponse LLM absente.")
                continue
            assessment, is_opinion = verdict
            if not assessment.outlet:
                assessment = assessment.model_copy(update={"outlet": article.domain})
            if is_opinion:
                status, reason = SourceStatus.REJECTED, "Contenu d'opinion, non factuel."
            elif assessment.reliability < min_reliability:
                status, reason = SourceStatus.REJECTED, "Fiabilité sous le seuil."
            else:
                status, reason = SourceStatus.RETAINED, ""
            results.append(
                AssessedArticle(
                    article=article, assessment=assessment, status=status, status_reason=reason
                )
            )
    retained = sum(r.status is SourceStatus.RETAINED for r in results)
    log.info("évaluation : %d retenus sur %d", retained, len(results))
    return results, incidents


def _reject_unassessed(
    articles: list[Article], results: list[AssessedArticle], reason: str
) -> None:
    for article in articles:
        results.append(
            AssessedArticle(
                article=article,
                assessment=Assessment(reliability=0, reason=reason, outlet=article.domain),
                status=SourceStatus.REJECTED,
                status_reason=reason,
            )
        )
