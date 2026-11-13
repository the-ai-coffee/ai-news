"""Étape 4 : comptage des sources indépendantes d'un événement.

Deux articles comptent pour une seule source s'ils viennent du même domaine, s'ils reprennent
la même dépêche d'agence, ou si leurs textes sont quasi identiques.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_news.models import AssessedArticle, SourceStatus

SIMILARITY_THRESHOLD = 0.5
SHINGLE_SIZE = 5
TEXT_WINDOW = 3000
BYLINE_WINDOW = 600

_AGENCIES = {
    "afp": "AFP",
    "agence france-presse": "AFP",
    "agence france presse": "AFP",
    "reuters": "Reuters",
    "associated press": "AP",
    "ap": "AP",
    "dpa": "DPA",
    "ansa": "ANSA",
    "efe": "EFE",
    "xinhua": "Xinhua",
    "anadolu": "Anadolu",
    "belga": "Belga",
    "ats": "ATS",
}
# Mentions typiques de crédit : "(AFP)", "- AFP", "avec AFP", "Par AFP", "(Reuters) -".
_CREDIT_RE = re.compile(
    r"(?:\(|\bavec\s+|\bpar\s+|\bsource\s*:\s*|[-–—]\s*)"
    r"(afp|agence france[- ]presse|reuters|associated press|ap|dpa|ansa|efe|xinhua|anadolu"
    r"|belga|ats)"
    r"\b\)?",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\w+")


def normalize_agency(name: str | None) -> str | None:
    if not name:
        return None
    return _AGENCIES.get(name.strip().lower(), name.strip())


def detect_agency(text: str) -> str | None:
    match = _CREDIT_RE.search(text[:BYLINE_WINDOW])
    return normalize_agency(match.group(1)) if match else None


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORD_RE.findall(text[:TEXT_WINDOW].lower())
    return {tuple(words[i : i + SHINGLE_SIZE]) for i in range(len(words) - SHINGLE_SIZE + 1)}


def jaccard(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class IndependenceResult:
    articles: list[AssessedArticle]  # statut et origine mis à jour
    independent_count: int
    merged_wire_copies: int


def resolve_independence(articles: list[AssessedArticle]) -> IndependenceResult:
    """Regroupe les articles par origine éditoriale (union-find) et marque les doublons."""
    ordered = sorted(articles, key=lambda a: a.assessment.reliability, reverse=True)
    parent = list(range(len(ordered)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)  # la racine reste l'article le plus fiable

    keys: list[str] = []
    agencies: list[str | None] = []
    for a in ordered:
        agency = normalize_agency(a.assessment.wire_agency) or detect_agency(a.article.text)
        agencies.append(agency)
        keys.append(f"agence:{agency}" if agency else f"domaine:{a.article.domain}")

    first_by_key: dict[str, int] = {}
    for i, key in enumerate(keys):
        if key in first_by_key:
            union(first_by_key[key], i)
        else:
            first_by_key[key] = i

    shingles = [_shingles(a.article.text) for a in ordered]
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            if find(i) != find(j) and jaccard(shingles[i], shingles[j]) >= SIMILARITY_THRESHOLD:
                union(i, j)

    updated: list[AssessedArticle] = []
    merged_wire = 0
    roots: set[int] = set()
    for i, a in enumerate(ordered):
        root = find(i)
        origin = keys[root]
        if root == i:
            roots.add(i)
            updated.append(a.model_copy(update={"origin": origin, "status": SourceStatus.RETAINED}))
            continue
        agency = agencies[i] or agencies[root]
        if agency:
            merged_wire += 1
            reason = f"Reprise de dépêche {agency} : comptée avec la source d'origine."
        else:
            reason = f"Contenu quasi identique à {ordered[root].assessment.outlet}."
        updated.append(
            a.model_copy(
                update={"origin": origin, "status": SourceStatus.MERGED, "status_reason": reason}
            )
        )
    return IndependenceResult(
        articles=updated, independent_count=len(roots), merged_wire_copies=merged_wire
    )
