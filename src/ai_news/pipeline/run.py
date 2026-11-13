"""Orchestration du pipeline : collecte → évaluation → regroupement → indépendance → classement
→ rédaction. Chaque étape est une fonction pure de ses entrées, testable séparément."""

from __future__ import annotations

import logging
from datetime import datetime

from ai_news.budget import Budget, BudgetExceededError
from ai_news.config import Config
from ai_news.llm import LLMClient
from ai_news.models import (
    AssessedArticle,
    AuditEntry,
    CutStory,
    Edition,
    EditionStats,
    SourceStatus,
    Story,
)
from ai_news.pipeline.assess import assess
from ai_news.pipeline.cluster import cluster
from ai_news.pipeline.collect import collect
from ai_news.pipeline.independence import IndependenceResult, resolve_independence
from ai_news.pipeline.rank import rank
from ai_news.pipeline.summarize import summarize
from ai_news.sources.firecrawl import SearchClient
from ai_news.store import edition_id

log = logging.getLogger(__name__)


class InsufficientStoriesError(Exception):
    """Trop peu de sujets valides : on ne publie pas, l'édition précédente reste en ligne."""


def build_edition(
    *,
    config: Config,
    search: SearchClient,
    llm: LLMClient,
    budget: Budget,
    now: datetime,
    previous: Edition | None,
) -> Edition:
    queries = config.search_queries()
    collected = collect(search, queries, config.search.max_chars_per_article)
    incidents = list(collected.incidents)

    assessed, assess_incidents = assess(
        llm,
        collected.articles,
        batch_size=config.assess.batch_size,
        min_reliability=config.assess.min_reliability,
    )
    incidents += assess_incidents
    by_id: dict[str, AssessedArticle] = {a.article.id: a for a in assessed}
    retained = [a for a in assessed if a.status is SourceStatus.RETAINED]

    previous_titles = [s.title for s in previous.stories] if previous else []
    events = cluster(llm, retained, previous_titles)

    label_of: dict[str, str] = {}
    independence: dict[str, IndependenceResult] = {}
    for event in events:
        members = [by_id[i] for i in event.article_ids]
        result = resolve_independence(members)
        independence[event.id] = result
        for article in result.articles:
            by_id[article.article.id] = article
            label_of[article.article.id] = event.label

    ranked, cut = rank(
        [(e, independence[e.id].independent_count) for e in events],
        config.ranking,
        config.edition.min_sources,
    )

    stories: list[Story] = []
    for position, candidate in enumerate(ranked):
        if len(stories) >= config.edition.max_stories:
            cut += [
                CutStory(
                    label=r.cluster.label,
                    rank=r.rank,
                    score=r.score,
                    reason=f"Hors top {config.edition.max_stories}.",
                )
                for r in ranked[position:]
            ]
            break
        result = independence[candidate.cluster.id]
        sources = [a for a in result.articles if a.status is SourceStatus.RETAINED]
        try:
            outcome = summarize(
                llm,
                candidate,
                sources,
                story_rank=len(stories) + 1,
                max_words=config.edition.max_words,
                words_per_minute=config.edition.words_per_minute,
                merged_wire_copies=result.merged_wire_copies,
            )
        except BudgetExceededError as exc:
            incidents.append(f"Rédaction interrompue : {exc}")
            cut += [
                CutStory(label=r.cluster.label, rank=r.rank, score=r.score, reason="Budget épuisé.")
                for r in ranked[position:]
            ]
            break
        if outcome.story is not None:
            stories.append(outcome.story)
        else:
            cut.append(
                CutStory(
                    label=candidate.cluster.label,
                    rank=candidate.rank,
                    score=candidate.score,
                    reason=f"Rejeté : {outcome.rejection}",
                )
            )

    audit = [
        AuditEntry(
            cluster_label=label_of.get(a.article.id),
            outlet=a.assessment.outlet,
            url=a.article.url,
            reliability=a.assessment.reliability,
            status=a.status,
            reason=a.status_reason or a.assessment.reason,
        )
        for a in by_id.values()
    ]
    audit.sort(key=lambda e: (e.cluster_label is None, e.cluster_label or "", -e.reliability))

    edition = Edition(
        id=edition_id(now),
        generated_at=now,
        themes=[t.name for t in config.themes],
        regions=[r.name for r in config.regions],
        stories=stories,
        cut=cut,
        audit=audit,
        incidents=incidents,
        stats=EditionStats(
            queries=len(queries),
            articles_read=len(collected.articles),
            sources_retained=len(retained),
            events_detected=len(events),
            stories_published=len(stories),
            llm_calls=budget.llm_calls,
            search_requests=budget.search_requests,
        ),
    )
    if len(stories) < config.edition.min_stories:
        raise InsufficientStoriesError(
            f"{len(stories)} sujet(s) valide(s), minimum {config.edition.min_stories}. "
            f"Incidents : {incidents or 'aucun'}"
        )
    log.info("édition %s : %d sujets", edition.id, len(stories))
    return edition
