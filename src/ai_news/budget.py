"""Plafonds de coût par run : appels LLM et requêtes de recherche."""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceededError(Exception):
    """Le plafond d'un poste de coût est atteint : le run s'arrête proprement."""


@dataclass
class Budget:
    max_llm_calls: int
    max_search_requests: int
    llm_calls: int = field(default=0, init=False)
    search_requests: int = field(default=0, init=False)

    def spend_llm(self) -> None:
        if self.llm_calls >= self.max_llm_calls:
            raise BudgetExceededError(f"plafond d'appels LLM atteint ({self.max_llm_calls})")
        self.llm_calls += 1

    def spend_search(self) -> None:
        if self.search_requests >= self.max_search_requests:
            raise BudgetExceededError(
                f"plafond de requêtes de recherche atteint ({self.max_search_requests})"
            )
        self.search_requests += 1
