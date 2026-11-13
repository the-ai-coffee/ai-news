"""Abstraction LLM.

DeepSeek expose une API compatible OpenAI : changer de fournisseur = une classe.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from openai import OpenAI, OpenAIError

from ai_news.budget import Budget
from ai_news.config import LLMConfig

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Réponse LLM absente ou non exploitable."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Renvoie un objet JSON. Lève LLMError si la réponse n'en est pas un."""
        ...


class DeepSeekClient:
    def __init__(self, api_key: str, config: LLMConfig, budget: Budget) -> None:
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY manquante")
        self._config = config
        self._budget = budget
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=3,  # backoff exponentiel géré par le SDK (429, 5xx, réseau)
        )

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self._budget.spend_llm()
        try:
            response = self._client.chat.completions.create(
                model=self._config.model,
                temperature=self._config.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except OpenAIError as exc:
            raise LLMError(f"appel LLM échoué : {exc}") from exc
        content = response.choices[0].message.content if response.choices else None
        return parse_json_object(content)


def parse_json_object(content: str | None) -> dict[str, Any]:
    if not content:
        raise LLMError("réponse LLM vide")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON invalide : {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("le LLM n'a pas renvoyé un objet JSON")
    return value
