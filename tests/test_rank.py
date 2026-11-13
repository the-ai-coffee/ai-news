from __future__ import annotations

from ai_news.config import RankingConfig
from ai_news.models import EventCluster
from ai_news.pipeline.rank import rank


def _event(eid: str, impact: float, repeat: bool = False) -> EventCluster:
    return EventCluster(
        id=eid,
        label=f"Événement {eid}",
        article_ids=[eid],
        impact=impact,
        impact_reason="r",
        repeat_without_new_facts=repeat,
    )


def test_coverage_and_impact_combined() -> None:
    ranked, cut = rank(
        [(_event("a", 0.2), 6), (_event("b", 0.9), 3), (_event("c", 0.5), 1)],
        RankingConfig(),
        min_sources=2,
    )
    # a : 0,6 × 1 + 0,4 × 0,2 = 0,68 ; b : 0,6 × 0,5 + 0,4 × 0,9 = 0,66
    assert [r.cluster.id for r in ranked] == ["a", "b"]
    assert [r.rank for r in ranked] == [1, 2]
    assert ranked[0].score == 0.68
    assert len(cut) == 1 and "1 source" in cut[0].reason


def test_repeat_penalty_demotes() -> None:
    ranked, _ = rank(
        [(_event("old", 0.9, repeat=True), 5), (_event("new", 0.5), 4)],
        RankingConfig(repeat_penalty=0.5),
        min_sources=2,
    )
    assert [r.cluster.id for r in ranked] == ["new", "old"]


def test_nothing_eligible() -> None:
    ranked, cut = rank([(_event("a", 1.0), 1)], RankingConfig(), min_sources=2)
    assert ranked == [] and len(cut) == 1
