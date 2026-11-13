"""Contrôles mécaniques appliqués aux textes générés : on ne fait pas confiance au LLM."""

from __future__ import annotations

import math
import re

# Nombres d'au moins deux chiffres, avec séparateurs éventuels (1 200 ; 1,200 ; 0,25 ; 12.5).
_NUMBER_RE = re.compile(r"\d[\d   ,.]*\d")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"\w+(?:['’-]\w+)*")

SENSATIONAL_TERMS = (
    "choc",
    "incroyable",
    "hallucinant",
    "terrifiant",
    "scandaleux",
    "stupéfiant",
    "spectaculaire",
    "bouleversant",
    "effroyable",
    "sidérant",
    "explosif",
)
_SENSATIONAL_RE = re.compile(r"\b(" + "|".join(SENSATIONAL_TERMS) + r")\w*\b", re.IGNORECASE)


def word_count(*texts: str) -> int:
    return sum(len(_WORD_RE.findall(t)) for t in texts)


def read_minutes(words: int, words_per_minute: int) -> int:
    return max(1, math.ceil(words / words_per_minute))


def _digits(token: str) -> str:
    return re.sub(r"\D", "", token)


def numbers_in(text: str) -> set[str]:
    """Nombres normalisés en suite de chiffres (séparateurs retirés)."""
    found: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        token = match.group(0).strip(" ,.  ")
        # Une séquence "12, 14" ou "2025 et" ne doit pas fusionner deux nombres.
        for part in re.split(r"[   ]*,[   ]+|[.,]\s+", token):
            digits = _digits(part)
            if len(digits) >= 2:
                found.add(digits)
    return found


def unverified_numbers(text: str, source_numbers: set[str]) -> set[str]:
    return {n for n in numbers_in(text) if n not in source_numbers}


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text.strip()) if s]


def drop_unverified_sentences(text: str, source_numbers: set[str]) -> tuple[str, int]:
    """Retire chaque phrase contenant un nombre absent des sources. Renvoie (texte, nb retirées)."""
    kept: list[str] = []
    dropped = 0
    for sentence in split_sentences(text):
        if unverified_numbers(sentence, source_numbers):
            dropped += 1
        else:
            kept.append(sentence)
    return " ".join(kept), dropped


def sensational_terms(text: str) -> set[str]:
    return {m.group(0).lower() for m in _SENSATIONAL_RE.finditer(text)}
