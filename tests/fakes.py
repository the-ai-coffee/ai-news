"""Doublures de test pour les API externes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ai_news.budget import Budget
from ai_news.config import SearchQuery
from ai_news.llm import LLMError
from ai_news.prompts import ASSESS_SYSTEM, CLUSTER_SYSTEM
from ai_news.sources.firecrawl import SearchHit

Responder = Callable[[str], dict[str, Any] | str]


class FakeLLM:
    """Répond selon l'étape (identifiée par le prompt système).

    Un répondeur peut renvoyer un dict (réponse JSON) ou la chaîne "error" (LLMError).
    """

    def __init__(
        self,
        *,
        assess: Responder | None = None,
        cluster: Responder | None = None,
        summarize: Responder | None = None,
        budget: Budget | None = None,
    ) -> None:
        self._assess = assess
        self._cluster = cluster
        self._summarize = summarize
        self._budget = budget
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if self._budget is not None:
            self._budget.spend_llm()
        if system == ASSESS_SYSTEM:
            step, responder = "assess", self._assess
        elif system == CLUSTER_SYSTEM:
            step, responder = "cluster", self._cluster
        else:
            step, responder = "summarize", self._summarize
        self.calls.append((step, user))
        if responder is None:
            raise AssertionError(f"appel LLM inattendu : {step}")
        result = responder(user)
        if result == "error":
            raise LLMError("erreur simulée")
        assert isinstance(result, dict)
        return result


def assess_all(reliability: float = 0.9) -> Responder:
    def respond(user: str) -> dict[str, Any]:
        items = json.loads(user)["articles"]
        return {
            "articles": [
                {
                    "id": a["id"],
                    "reliability": reliability,
                    "reason": "Média identifiable, faits attribués.",
                    "outlet": a["domain"],
                    "language": "fr",
                    "country": "France",
                    "wire_agency": None,
                    "is_opinion": False,
                }
                for a in items
            ]
        }

    return respond


class FakeSearch:
    def __init__(self, hits_by_query: dict[str, list[SearchHit]]) -> None:
        self._hits = hits_by_query
        self.queries: list[str] = []

    def search(self, query: SearchQuery) -> list[SearchHit]:
        self.queries.append(query.text)
        return self._hits.get(query.text, [])
