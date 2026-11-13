from __future__ import annotations

from ai_news.models import SourceStatus
from ai_news.pipeline.independence import detect_agency, resolve_independence
from tests.conftest import make_assessed

WIRE = (
    "PARIS (AFP) - Les ministres de l'énergie ont signé jeudi un accord de mutualisation "
    "des achats de gaz qui entrera en vigueur au premier janvier prochain selon le texte "
    "publié par la présidence du Conseil et consulté par plusieurs rédactions européennes."
)


def test_detect_agency_from_byline() -> None:
    assert detect_agency("BRUXELLES (Reuters) - Le texte...") == "Reuters"
    assert detect_agency("Un article avec AFP en fin de chapeau") == "AFP"
    assert detect_agency("Après une longue réunion, les ministres...") is None


def test_wire_copies_count_once() -> None:
    articles = [
        make_assessed("a", domain="lemonde.fr", reliability=0.9, agency="AFP"),
        make_assessed("b", domain="lefigaro.fr", reliability=0.8, text=WIRE),
        make_assessed("c", domain="reuters.com", reliability=0.95),
    ]
    result = resolve_independence(articles)
    assert result.independent_count == 2
    assert result.merged_wire_copies == 1
    merged = [a for a in result.articles if a.status is SourceStatus.MERGED]
    assert [a.article.id for a in merged] == ["b"]
    assert "AFP" in merged[0].status_reason


def test_same_domain_counts_once() -> None:
    articles = [
        make_assessed("a", domain="bbc.co.uk"),
        make_assessed("b", domain="bbc.co.uk", reliability=0.7),
    ]
    assert resolve_independence(articles).independent_count == 1


def test_near_identical_texts_merged() -> None:
    text = " ".join(f"mot{i}" for i in range(200))
    articles = [
        make_assessed("a", domain="site-a.com", text=text),
        make_assessed("b", domain="site-b.com", text=text + " fin", reliability=0.6),
    ]
    result = resolve_independence(articles)
    assert result.independent_count == 1
    assert result.merged_wire_copies == 0
    merged = next(a for a in result.articles if a.status is SourceStatus.MERGED)
    assert "quasi identique" in merged.status_reason


def test_most_reliable_article_is_kept() -> None:
    articles = [
        make_assessed("low", domain="x.com", agency="AFP", reliability=0.6),
        make_assessed("high", domain="y.com", agency="AFP", reliability=0.9),
    ]
    result = resolve_independence(articles)
    kept = next(a for a in result.articles if a.status is SourceStatus.RETAINED)
    assert kept.article.id == "high"
