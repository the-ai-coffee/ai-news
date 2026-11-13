"""Étape 5 : classement objectif des événements.

score = coverage_weight × couverture normalisée + impact_weight × impact,
multiplié par repeat_penalty si l'événement est une redite sans fait nouveau.
"""

from __future__ import annotations

from ai_news.config import RankingConfig
from ai_news.models import CutStory, EventCluster, RankedCluster


def rank(
    clusters: list[tuple[EventCluster, int]],
    config: RankingConfig,
    min_sources: int,
) -> tuple[list[RankedCluster], list[CutStory]]:
    """`clusters` : (événement, nombre de sources indépendantes).

    Renvoie les événements éligibles triés par score, et ceux écartés faute de sources.
    """
    eligible = [(c, n) for c, n in clusters if n >= min_sources]
    cut = [
        CutStory(
            label=c.label,
            rank=None,
            score=None,
            reason=f"{n} source(s) indépendante(s), minimum {min_sources}.",
        )
        for c, n in clusters
        if n < min_sources
    ]
    if not eligible:
        return [], cut
    max_sources = max(n for _, n in eligible)
    total_weight = (config.coverage_weight + config.impact_weight) or 1.0
    ranked: list[RankedCluster] = []
    for c, n in eligible:
        coverage = n / max_sources
        score = (config.coverage_weight * coverage + config.impact_weight * c.impact) / total_weight
        if c.repeat_without_new_facts:
            score *= config.repeat_penalty
        ranked.append(RankedCluster(cluster=c, independent_sources=n, score=round(score, 4)))
    ranked.sort(key=lambda r: (r.score, r.independent_sources), reverse=True)
    for position, r in enumerate(ranked, start=1):
        r.rank = position
    return ranked, cut
