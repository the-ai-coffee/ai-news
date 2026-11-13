"""Persistance des éditions : un fichier JSON par édition, versionné dans git (trace d'audit)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ai_news.models import Edition


def edition_id(moment: datetime) -> str:
    """`moment` doit être dans le fuseau du site. Ex. 2026-10-23-pm."""
    return f"{moment:%Y-%m-%d}-{'am' if moment.hour < 12 else 'pm'}"


def save_edition(edition: Edition, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{edition.id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(edition.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)  # écriture atomique
    return path


def load_editions(directory: Path) -> list[Edition]:
    """Toutes les éditions, de la plus récente à la plus ancienne."""
    if not directory.is_dir():
        return []
    editions = [
        Edition.model_validate_json(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")
    ]
    return sorted(editions, key=lambda e: e.generated_at, reverse=True)
