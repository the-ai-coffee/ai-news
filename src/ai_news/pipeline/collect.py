"""Étape 1 : collecte des articles via la recherche web, pour chaque couple thème × région."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ai_news.budget import BudgetExceededError
from ai_news.config import SearchQuery
from ai_news.models import Article
from ai_news.sources.firecrawl import SearchClient, SearchError, article_id, domain_of

log = logging.getLogger(__name__)


@dataclass
class CollectResult:
    articles: list[Article] = field(default_factory=list)
    incidents: list[str] = field(default_factory=list)


def collect(client: SearchClient, queries: list[SearchQuery], max_chars: int) -> CollectResult:
    result = CollectResult()
    seen: set[str] = set()
    for query in queries:
        try:
            hits = client.search(query)
        except SearchError as exc:
            result.incidents.append(
                f"Recherche « {query.text} » ({query.theme} · {query.region}) en échec : {exc}"
            )
            continue
        except BudgetExceededError as exc:
            result.incidents.append(f"Collecte interrompue : {exc}")
            break
        for hit in hits:
            aid = article_id(hit.url)
            if aid in seen:
                continue
            seen.add(aid)
            result.articles.append(
                Article(
                    id=aid,
                    url=hit.url,
                    domain=domain_of(hit.url),
                    title=hit.title,
                    description=hit.description,
                    text=hit.markdown[:max_chars],
                    theme=query.theme,
                    region=query.region,
                    published=hit.published,
                )
            )
    log.info(
        "collecte : %d articles uniques, %d incidents", len(result.articles), len(result.incidents)
    )
    return result
