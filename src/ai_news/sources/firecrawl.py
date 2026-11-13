"""Client Firecrawl : recherche web + extraction du texte en Markdown, en un seul appel."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from ai_news.budget import Budget
from ai_news.config import SearchQuery

log = logging.getLogger(__name__)

API_URL = "https://api.firecrawl.dev/v2/search"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SearchError(Exception):
    """Échec définitif d'une requête de recherche."""


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    description: str
    markdown: str
    published: str | None


class SearchClient(Protocol):
    def search(self, query: SearchQuery) -> list[SearchHit]: ...


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def domain_of(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.").lower()


class FirecrawlClient:
    def __init__(
        self,
        api_key: str,
        budget: Budget,
        *,
        limit: int,
        tbs: str,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
        http: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("FIRECRAWL_API_KEY manquante")
        self._budget = budget
        self._limit = limit
        self._tbs = tbs
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._http = http or httpx.Client(timeout=httpx.Timeout(120.0))
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def search(self, query: SearchQuery) -> list[SearchHit]:
        payload: dict[str, Any] = {
            "query": query.text,
            "limit": self._limit,
            "tbs": self._tbs,
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
        }
        body = self._post_with_retry(payload)
        return [hit for item in _extract_results(body) if (hit := _to_hit(item)) is not None]

    def _post_with_retry(self, payload: dict[str, Any]) -> Any:
        last_error: str = ""
        for attempt in range(1, self._max_attempts + 1):
            self._budget.spend_search()
            try:
                response = self._http.post(API_URL, json=payload, headers=self._headers)
            except httpx.TransportError as exc:
                last_error = f"erreur réseau : {exc}"
            else:
                if response.status_code == 200:
                    return response.json()
                last_error = f"HTTP {response.status_code} : {response.text[:200]}"
                if response.status_code not in RETRYABLE_STATUS:
                    break
            if attempt < self._max_attempts:
                delay = self._backoff * 2 ** (attempt - 1)
                log.warning("Firecrawl %s, nouvel essai dans %.0fs", last_error, delay)
                time.sleep(delay)
        raise SearchError(last_error)


def _extract_results(body: Any) -> list[dict[str, Any]]:
    """Accepte les deux formes documentées : `data: [...]` et `data: {web: [...]}`."""
    if not isinstance(body, dict) or not body.get("success", True):
        raise SearchError(f"réponse Firecrawl inattendue : {str(body)[:200]}")
    data = body.get("data", [])
    if isinstance(data, dict):
        data = data.get("web", [])
    return [item for item in data if isinstance(item, dict)]


def _to_hit(item: dict[str, Any]) -> SearchHit | None:
    metadata = item.get("metadata") or {}
    url = item.get("url") or metadata.get("sourceURL")
    markdown = item.get("markdown") or ""
    if not url or not markdown.strip():
        return None
    published = (
        metadata.get("publishedTime") or metadata.get("article:published_time") or item.get("date")
    )
    return SearchHit(
        url=str(url),
        title=str(item.get("title") or metadata.get("title") or ""),
        description=str(item.get("description") or metadata.get("description") or ""),
        markdown=str(markdown),
        published=str(published) if published else None,
    )
