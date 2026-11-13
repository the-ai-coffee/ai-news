"""Modèles de données échangés entre les étapes du pipeline et stockés dans l'édition JSON."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Article(_Model):
    """Article brut collecté. Le texte complet n'est jamais persisté."""

    id: str
    url: str
    domain: str
    title: str
    description: str = ""
    text: str = Field(default="", exclude=True)
    theme: str
    region: str
    published: str | None = None


class SourceStatus(StrEnum):
    RETAINED = "retenue"
    MERGED = "fusionnée"
    REJECTED = "écartée"


class Assessment(_Model):
    reliability: float = Field(ge=0, le=1)
    reason: str
    outlet: str
    language: str = ""
    country: str = ""
    wire_agency: str | None = None


class AssessedArticle(_Model):
    article: Article
    assessment: Assessment
    status: SourceStatus
    status_reason: str = ""
    origin: str = ""  # identifiant d'origine éditoriale (agence ou domaine) après déduplication


class EventCluster(_Model):
    """Groupe d'articles décrivant le même événement, proposé par le LLM."""

    id: str
    label: str
    article_ids: list[str]
    impact: float = Field(ge=0, le=1)
    impact_reason: str
    repeat_without_new_facts: bool = False


class RankedCluster(_Model):
    cluster: EventCluster
    independent_sources: int
    score: float
    rank: int = 0


class SourceRef(_Model):
    outlet: str
    url: str
    language: str = ""
    country: str = ""
    published: str | None = None


class Position(_Model):
    position: str
    sources: list[str]


class Divergence(_Model):
    topic: str
    positions: list[Position] = Field(min_length=2)


class Story(_Model):
    id: str
    rank: int
    theme: str
    region: str
    title: str
    essentiel: str
    faits: str
    contexte: str
    divergences: list[Divergence] = []
    sources: list[SourceRef]
    independent_sources: int
    merged_wire_copies: int = 0
    score: float
    read_minutes: int


class CutStory(_Model):
    label: str
    rank: int | None
    score: float | None
    reason: str


class AuditEntry(_Model):
    cluster_label: str | None
    outlet: str
    url: str
    reliability: float
    status: SourceStatus
    reason: str


class EditionStats(_Model):
    queries: int = 0
    articles_read: int = 0
    sources_retained: int = 0
    events_detected: int = 0
    stories_published: int = 0
    llm_calls: int = 0
    search_requests: int = 0


class Edition(_Model):
    id: str
    generated_at: datetime
    themes: list[str]
    regions: list[str]
    stories: list[Story]
    cut: list[CutStory] = []
    audit: list[AuditEntry] = []
    incidents: list[str] = []
    stats: EditionStats = EditionStats()
