"""Étapes LLM : évaluation, regroupement, rédaction (LLM simulé)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ai_news.models import EventCluster, RankedCluster, SourceStatus
from ai_news.pipeline.assess import assess
from ai_news.pipeline.cluster import ClusterError, cluster
from ai_news.pipeline.summarize import summarize
from tests.conftest import make_article, make_assessed
from tests.fakes import FakeLLM, assess_all

# ---------- évaluation ----------


def test_assess_statuses() -> None:
    def respond(user: str) -> dict[str, Any]:
        return {
            "articles": [
                {"id": "ok", "reliability": 0.9, "reason": "Fiable", "outlet": "Le Monde"},
                {"id": "low", "reliability": 0.2, "reason": "Racoleur", "outlet": "Buzz"},
                {
                    "id": "op",
                    "reliability": 0.9,
                    "reason": "Tribune",
                    "outlet": "X",
                    "is_opinion": True,
                },
                {"id": "bad", "reliability": "n/a"},
            ]
        }

    articles = [make_article(i) for i in ("ok", "low", "op", "bad", "missing")]
    results, incidents = assess(
        FakeLLM(assess=respond), articles, batch_size=10, min_reliability=0.5
    )
    status = {r.article.id: r.status for r in results}
    assert status == {
        "ok": SourceStatus.RETAINED,
        "low": SourceStatus.REJECTED,
        "op": SourceStatus.REJECTED,
        "bad": SourceStatus.REJECTED,
        "missing": SourceStatus.REJECTED,
    }
    assert incidents == []


def test_assess_retries_then_rejects_batch() -> None:
    llm = FakeLLM(assess=lambda _: "error")
    results, _ = assess(llm, [make_article("a")], batch_size=10, min_reliability=0.5)
    assert len(llm.calls) == 2
    assert results[0].status is SourceStatus.REJECTED


def test_assess_batches() -> None:
    llm = FakeLLM(assess=assess_all())
    articles = [make_article(str(i)) for i in range(25)]
    results, _ = assess(llm, articles, batch_size=10, min_reliability=0.5)
    assert len(llm.calls) == 3
    assert all(r.status is SourceStatus.RETAINED for r in results)


# ---------- regroupement ----------


def test_cluster_filters_unknown_and_duplicate_ids() -> None:
    retained = [make_assessed(i) for i in ("a", "b", "c")]

    def respond(user: str) -> dict[str, Any]:
        payload = json.loads(user)
        assert payload["previous_edition_titles"] == ["Ancien sujet"]
        return {
            "events": [
                {
                    "label": "E1",
                    "article_ids": ["a", "b", "zzz"],
                    "impact": 1.7,
                    "impact_reason": "r",
                },
                {"label": "E2", "article_ids": ["b"], "impact": 0.5, "impact_reason": "r"},
                {
                    "label": "E3",
                    "article_ids": ["c"],
                    "impact": "x",
                    "impact_reason": "r",
                    "repeat_without_new_facts": True,
                },
            ]
        }

    events = cluster(FakeLLM(cluster=respond), retained, ["Ancien sujet"])
    assert [e.article_ids for e in events] == [["a", "b"], ["c"]]
    assert events[0].impact == 1.0
    assert events[1].impact == 0.0 and events[1].repeat_without_new_facts


def test_cluster_failure_raises() -> None:
    with pytest.raises(ClusterError):
        cluster(FakeLLM(cluster=lambda _: "error"), [make_assessed("a")], [])


# ---------- rédaction ----------

SOURCE_A = "Le bilan provisoire est de 12 morts et 40 blessés, selon la police, le 13 novembre."
SOURCE_B = "Les autorités évoquent au moins 20 morts. L'enquête est en cours depuis le 13 novembre."


def _ranked() -> RankedCluster:
    event = EventCluster(
        id="e001", label="Accident", article_ids=["a", "b"], impact=0.5, impact_reason="r"
    )
    return RankedCluster(cluster=event, independent_sources=2, score=0.8, rank=1)


def _sources() -> list[Any]:
    return [
        make_assessed("a", domain="lemonde.fr", outlet="Le Monde", text=SOURCE_A),
        make_assessed("b", domain="bbc.com", outlet="BBC", text=SOURCE_B),
    ]


def _draft(**overrides: Any) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "title": "Un accident fait au moins 12 morts",
        "essentiel": "Un accident a eu lieu le 13 novembre. Le bilan provisoire est de 12 morts.",
        "faits": "La police fait état de 40 blessés. L'enquête est en cours.",
        "contexte": "Aucun antécédent n'est mentionné par les sources.",
        "divergences": [
            {
                "topic": "Bilan humain",
                "positions": [
                    {"position": "12 morts", "sources": ["S1"]},
                    {"position": "Au moins 20 morts", "sources": ["S2", "S9"]},
                ],
            },
            {"topic": "Invalide", "positions": [{"position": "x", "sources": ["S1"]}]},
        ],
    }
    draft.update(overrides)
    return draft


def _summarize(llm: FakeLLM, max_words: int = 690) -> Any:
    return summarize(
        llm,
        _ranked(),
        _sources(),
        story_rank=1,
        max_words=max_words,
        words_per_minute=230,
        merged_wire_copies=1,
    )


def test_summarize_valid_story() -> None:
    outcome = _summarize(FakeLLM(summarize=lambda _: _draft()))
    story = outcome.story
    assert story is not None, outcome.rejection
    assert story.id == "01" and story.read_minutes == 1
    assert [d.topic for d in story.divergences] == ["Bilan humain"]
    assert story.divergences[0].positions[1].sources == ["BBC"]
    assert [s.outlet for s in story.sources] == ["Le Monde", "BBC"]
    assert story.merged_wire_copies == 1


def test_unverified_number_sentence_removed() -> None:
    draft = _draft(faits="La police fait état de 40 blessés. Il y aurait 300 évacués. Fin.")
    story = _summarize(FakeLLM(summarize=lambda _: draft)).story
    assert story is not None
    assert "300" not in story.faits and "40 blessés" in story.faits


def test_unverified_number_in_title_rejects() -> None:
    draft = _draft(title="Un accident fait 99 morts")
    outcome = _summarize(FakeLLM(summarize=lambda _: draft))
    assert outcome.story is None and "titre" in (outcome.rejection or "")


def test_too_long_retries_with_feedback() -> None:
    drafts = [_draft(faits="mot " * 800), _draft()]
    llm = FakeLLM(summarize=lambda _: drafts.pop(0))
    outcome = _summarize(llm)
    assert outcome.story is not None
    assert len(llm.calls) == 2
    assert "trop long" in llm.calls[1][1]


def test_sensational_terms_rejected_after_retry() -> None:
    llm = FakeLLM(summarize=lambda _: _draft(title="Accident choc en ville"))
    outcome = _summarize(llm)
    assert outcome.story is None and "sensationnalistes" in (outcome.rejection or "")
    assert len(llm.calls) == 2


def test_invalid_output_rejected_after_retry() -> None:
    llm = FakeLLM(summarize=lambda _: {"title": "x"})
    outcome = _summarize(llm)
    assert outcome.story is None and "hors schéma" in (outcome.rejection or "")
    assert len(llm.calls) == 2


def test_incoherent_after_number_removal_rejected() -> None:
    draft = _draft(essentiel="Il y a 77 morts. Et 88 blessés. Le bilan évolue.")
    outcome = _summarize(FakeLLM(summarize=lambda _: draft))
    assert outcome.story is None and "incohérent" in (outcome.rejection or "")
