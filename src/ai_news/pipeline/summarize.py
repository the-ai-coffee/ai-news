"""Étape 6 : rédaction d'un sujet à partir de ses sources, puis contrôles mécaniques."""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_news.llm import LLMClient, LLMError
from ai_news.models import AssessedArticle, Divergence, Position, RankedCluster, SourceRef, Story
from ai_news.pipeline import checks
from ai_news.prompts import SUMMARIZE_SYSTEM

log = logging.getLogger(__name__)

MAX_TOTAL_SOURCE_CHARS = 40_000
MAX_TITLE_WORDS = 14  # 12 demandés, petite tolérance
MIN_ESSENTIEL_SENTENCES = 2


class _Draft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3)
    essentiel: str = Field(min_length=20)
    faits: str = Field(min_length=20)
    contexte: str = ""
    divergences: list[dict[str, Any]] = []


@dataclass
class SummaryOutcome:
    story: Story | None
    rejection: str | None = None


def _source_payload(sources: list[AssessedArticle], per_source_chars: int) -> str:
    return json.dumps(
        {
            "sources": [
                {
                    "id": f"S{i}",
                    "outlet": s.assessment.outlet,
                    "language": s.assessment.language,
                    "title": s.article.title,
                    "text": s.article.text[:per_source_chars],
                }
                for i, s in enumerate(sources, start=1)
            ]
        },
        ensure_ascii=False,
    )


def _divergences(raw: list[dict[str, Any]], labels: dict[str, str]) -> list[Divergence]:
    """Convertit les identifiants S1.. en noms de médias ; écarte les entrées invalides."""
    result: list[Divergence] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        positions: list[Position] = []
        for pos in item.get("positions", []) or []:
            if not isinstance(pos, dict):
                continue
            outlets = [labels[s] for s in pos.get("sources", []) or [] if s in labels]
            text = str(pos.get("position") or "").strip()
            if outlets and text:
                positions.append(Position(position=text, sources=list(dict.fromkeys(outlets))))
        topic = str(item.get("topic") or "").strip()
        if topic and len(positions) >= 2:
            result.append(Divergence(topic=topic, positions=positions))
    return result


def _divergence_text(divergences: list[Divergence]) -> str:
    return " ".join(f"{d.topic}. " + " ".join(p.position for p in d.positions) for d in divergences)


def _issues(draft: _Draft, divergences: list[Divergence], max_words: int) -> list[str]:
    issues: list[str] = []
    words = checks.word_count(
        draft.essentiel, draft.faits, draft.contexte, _divergence_text(divergences)
    )
    if words > max_words:
        issues.append(f"Texte trop long ({words} mots) : raccourcis à {max_words} mots maximum.")
    if checks.word_count(draft.title) > MAX_TITLE_WORDS:
        issues.append("Titre trop long : 12 mots maximum.")
    found = checks.sensational_terms(
        " ".join([draft.title, draft.essentiel, draft.faits, draft.contexte])
    )
    if found:
        issues.append(f"Termes sensationnalistes interdits : {', '.join(sorted(found))}.")
    return issues


def summarize(
    llm: LLMClient,
    ranked: RankedCluster,
    sources: list[AssessedArticle],
    *,
    story_rank: int,
    max_words: int,
    words_per_minute: int,
    merged_wire_copies: int,
) -> SummaryOutcome:
    """`sources` : articles indépendants retenus (un par origine), les plus fiables d'abord."""
    labels = {f"S{i}": s.assessment.outlet for i, s in enumerate(sources, start=1)}
    per_source = max(1000, MAX_TOTAL_SOURCE_CHARS // max(1, len(sources)))
    source_payload = _source_payload(sources, per_source)
    system = SUMMARIZE_SYSTEM.format(max_words=max_words)
    source_numbers: set[str] = set()
    for s in sources:
        source_numbers |= checks.numbers_in(f"{s.article.title} {s.article.text}")

    feedback: list[str] = []
    draft: _Draft | None = None
    divergences: list[Divergence] = []
    for _attempt in (1, 2):
        user = source_payload
        if feedback:
            user += (
                "\n\nCorrige les problèmes suivants de ta réponse précédente :\n- "
                + "\n- ".join(feedback)
            )
        try:
            draft = _Draft.model_validate(llm.complete_json(system, user))
        except (LLMError, ValidationError) as exc:
            feedback = [
                f"Réponse invalide ({type(exc).__name__}) : respecte strictement le format."
            ]
            draft = None
            continue
        divergences = _divergences(draft.divergences, labels)
        feedback = _issues(draft, divergences, max_words)
        if not feedback:
            break

    if draft is None:
        return SummaryOutcome(None, "Sortie LLM hors schéma après nouvel essai.")
    if feedback:
        return SummaryOutcome(None, "Contrôles non satisfaits : " + " ".join(feedback))

    # Chiffres : toute phrase contenant un nombre absent des sources est retirée.
    if checks.unverified_numbers(draft.title, source_numbers):
        return SummaryOutcome(None, "Chiffre du titre absent des sources.")
    essentiel, dropped_e = checks.drop_unverified_sentences(draft.essentiel, source_numbers)
    faits, dropped_f = checks.drop_unverified_sentences(draft.faits, source_numbers)
    contexte, dropped_c = checks.drop_unverified_sentences(draft.contexte, source_numbers)
    divergences = [
        d
        for d in divergences
        if not checks.unverified_numbers(_divergence_text([d]), source_numbers)
    ]
    if dropped_e + dropped_f + dropped_c:
        log.info(
            "sujet %d : %d phrase(s) retirée(s) (chiffres non sourcés)",
            story_rank,
            dropped_e + dropped_f + dropped_c,
        )
    if len(checks.split_sentences(essentiel)) < MIN_ESSENTIEL_SENTENCES or not faits:
        return SummaryOutcome(None, "Texte incohérent après retrait des chiffres non sourcés.")

    themes = Counter(s.article.theme for s in sources)
    regions = Counter(s.article.region for s in sources)
    words = checks.word_count(essentiel, faits, contexte, _divergence_text(divergences))
    story = Story(
        id=f"{story_rank:02d}",
        rank=story_rank,
        theme=themes.most_common(1)[0][0],
        region=regions.most_common(1)[0][0],
        title=draft.title.strip(),
        essentiel=essentiel,
        faits=faits,
        contexte=contexte,
        divergences=divergences,
        sources=[
            SourceRef(
                outlet=s.assessment.outlet,
                url=s.article.url,
                language=s.assessment.language,
                country=s.assessment.country,
                published=s.article.published,
            )
            for s in sources
        ],
        independent_sources=ranked.independent_sources,
        merged_wire_copies=merged_wire_copies,
        score=ranked.score,
        read_minutes=checks.read_minutes(words, words_per_minute),
    )
    return SummaryOutcome(story)
