"""Chargement et validation de `config.toml`."""

from __future__ import annotations

import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(Exception):
    """Configuration absente ou invalide."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SiteConfig(_Strict):
    title: str = Field(min_length=1)
    timezone: str = "Europe/Paris"

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"fuseau horaire inconnu : {value}") from exc
        return value


class EditionConfig(_Strict):
    max_stories: int = Field(default=10, ge=1, le=50)
    min_stories: int = Field(default=3, ge=1)
    min_sources: int = Field(default=2, ge=1)
    max_read_minutes: int = Field(default=3, ge=1)
    words_per_minute: int = Field(default=230, ge=100)

    @model_validator(mode="after")
    def _coherent(self) -> EditionConfig:
        if self.min_stories > self.max_stories:
            raise ValueError("min_stories doit être <= max_stories")
        return self

    @property
    def max_words(self) -> int:
        return self.max_read_minutes * self.words_per_minute


class SearchConfig(_Strict):
    results_per_query: int = Field(default=8, ge=1, le=50)
    tbs: str = "qdr:d"
    max_chars_per_article: int = Field(default=6000, ge=500)


class AssessConfig(_Strict):
    min_reliability: float = Field(default=0.5, ge=0, le=1)
    batch_size: int = Field(default=10, ge=1, le=50)


class RankingConfig(_Strict):
    coverage_weight: float = Field(default=0.6, ge=0)
    impact_weight: float = Field(default=0.4, ge=0)
    repeat_penalty: float = Field(default=0.5, ge=0, le=1)


class BudgetConfig(_Strict):
    max_llm_calls: int = Field(default=80, ge=1)
    max_search_requests: int = Field(default=40, ge=1)


class LLMConfig(_Strict):
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: float = Field(default=120, gt=0)


class Theme(_Strict):
    name: str = Field(min_length=1)
    queries: list[str] = Field(min_length=1)


class Region(_Strict):
    name: str = Field(min_length=1)
    terms: str = ""


class SearchQuery(_Strict):
    theme: str
    region: str
    text: str


class Config(_Strict):
    site: SiteConfig
    edition: EditionConfig = EditionConfig()
    search: SearchConfig = SearchConfig()
    assess: AssessConfig = AssessConfig()
    ranking: RankingConfig = RankingConfig()
    budget: BudgetConfig = BudgetConfig()
    llm: LLMConfig = LLMConfig()
    themes: list[Theme] = Field(min_length=1)
    regions: list[Region] = Field(min_length=1)

    def search_queries(self) -> list[SearchQuery]:
        """Produit cartésien thèmes × régions × requêtes."""
        return [
            SearchQuery(theme=t.name, region=r.name, text=f"{q} {r.terms}".strip())
            for t in self.themes
            for r in self.regions
            for q in t.queries
        ]


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"fichier de configuration introuvable : {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML invalide dans {path} : {exc}") from exc
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"configuration invalide ({path}) :\n{exc}") from exc
