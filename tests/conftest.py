from __future__ import annotations

from typing import Any

import pytest

from ai_news.config import Config
from ai_news.models import Article, AssessedArticle, Assessment, SourceStatus

CONFIG_DICT: dict[str, Any] = {
    "site": {"title": "Test", "timezone": "Europe/Paris"},
    "edition": {"max_stories": 3, "min_stories": 1, "min_sources": 2},
    "themes": [{"name": "Monde", "queries": ["actualité"]}],
    "regions": [{"name": "International", "terms": ""}, {"name": "Europe", "terms": "Europe"}],
}


@pytest.fixture
def config() -> Config:
    return Config.model_validate(CONFIG_DICT)


def make_article(
    aid: str,
    *,
    domain: str = "example.org",
    text: str = "",
    title: str = "Titre",
    theme: str = "Monde",
    region: str = "International",
) -> Article:
    return Article(
        id=aid,
        url=f"https://{domain}/{aid}",
        domain=domain,
        title=title,
        text=text or f"Texte original et unique de l'article {aid} " * 5,
        theme=theme,
        region=region,
    )


def make_assessed(
    aid: str,
    *,
    domain: str = "example.org",
    outlet: str | None = None,
    reliability: float = 0.9,
    agency: str | None = None,
    text: str = "",
) -> AssessedArticle:
    return AssessedArticle(
        article=make_article(aid, domain=domain, text=text),
        assessment=Assessment(
            reliability=reliability,
            reason="ok",
            outlet=outlet or domain,
            language="fr",
            country="France",
            wire_agency=agency,
        ),
        status=SourceStatus.RETAINED,
    )
