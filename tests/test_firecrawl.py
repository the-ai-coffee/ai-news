from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai_news.budget import Budget, BudgetExceededError
from ai_news.config import SearchQuery
from ai_news.sources.firecrawl import FirecrawlClient, SearchError, domain_of

QUERY = SearchQuery(theme="Monde", region="Europe", text="actualité Europe")
ITEM = {
    "url": "https://www.lemonde.fr/article",
    "title": "Titre",
    "description": "Desc",
    "markdown": "# Texte",
    "metadata": {"publishedTime": "2026-11-13T08:00:00Z"},
}


def _client(handler: Any, budget: Budget | None = None) -> FirecrawlClient:
    return FirecrawlClient(
        "fc-test",
        budget or Budget(10, 10),
        limit=5,
        tbs="qdr:d",
        backoff_seconds=0,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("data", [[ITEM], {"web": [ITEM]}])
def test_both_response_shapes(data: Any) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"success": True, "data": data})

    hits = _client(handler).search(QUERY)
    assert len(hits) == 1
    assert hits[0].published == "2026-11-13T08:00:00Z"
    assert seen["body"]["tbs"] == "qdr:d"
    assert seen["body"]["scrapeOptions"]["formats"] == ["markdown"]
    assert seen["auth"] == "Bearer fc-test"


def test_results_without_text_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": [{**ITEM, "markdown": " "}]})

    assert _client(handler).search(QUERY) == []


def test_retry_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"success": True, "data": [ITEM]})

    budget = Budget(10, 10)
    assert len(_client(handler, budget).search(QUERY)) == 1
    assert budget.search_requests == 3


def test_non_retryable_error_raises_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(SearchError, match="401"):
        _client(handler).search(QUERY)
    assert calls["n"] == 1


def test_budget_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": []})

    client = _client(handler, Budget(10, 1))
    client.search(QUERY)
    with pytest.raises(BudgetExceededError):
        client.search(QUERY)


def test_missing_key_rejected() -> None:
    with pytest.raises(ValueError):
        FirecrawlClient("", Budget(1, 1), limit=1, tbs="qdr:d")


def test_domain_of() -> None:
    assert domain_of("https://www.LeMonde.fr/x") == "lemonde.fr"
