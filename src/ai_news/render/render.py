"""Génération du site statique à partir des éditions JSON."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ai_news.config import Config
from ai_news.models import Edition, SourceStatus

_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

STATIC_DIR = Path(__file__).parent / "static"


def french_date(moment: datetime, *, weekday: bool = True) -> str:
    text = f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"
    return f"{_DAYS[moment.weekday()]} {text}" if weekday else text


def edition_label(edition: Edition, tz: ZoneInfo) -> str:
    local = edition.generated_at.astimezone(tz)
    moment = "Édition du matin" if local.hour < 12 else "Édition du soir"
    return f"{moment} · {french_date(local)} · {local:%Hh%M}"


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("ai_news.render", "templates"),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["SourceStatus"] = SourceStatus
    return env


def render_site(
    editions: list[Edition], config: Config, output: Path, deploy_dir: Path | None = None
) -> None:
    """`editions` : de la plus récente à la plus ancienne. Reconstruit entièrement `output`."""
    if not editions:
        raise ValueError("aucune édition à générer")
    tz = ZoneInfo(config.site.timezone)
    env = _environment()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    common = {"site_title": config.site.title}
    latest = editions[0]
    for edition in editions:
        ctx = {
            **common,
            "edition": edition,
            "label": edition_label(edition, tz),
            "base": f"/e/{edition.id}",
            "is_latest": edition.id == latest.id,
        }
        edition_dir = output / "e" / edition.id
        edition_dir.mkdir(parents=True)
        index_html = env.get_template("index.html").render(**ctx)
        (edition_dir / "index.html").write_text(index_html, encoding="utf-8")
        if edition.id == latest.id:
            (output / "index.html").write_text(index_html, encoding="utf-8")
        for story in edition.stories:
            html = env.get_template("story.html").render(**ctx, story=story)
            (edition_dir / f"{story.id}.html").write_text(html, encoding="utf-8")
        audit_html = env.get_template("audit.html").render(**ctx)
        (edition_dir / "audit.html").write_text(audit_html, encoding="utf-8")

    archives = [(e, edition_label(e, tz)) for e in editions]
    archives_dir = output / "archives"
    archives_dir.mkdir()
    (archives_dir / "index.html").write_text(
        env.get_template("archives.html").render(**common, archives=archives), encoding="utf-8"
    )
    shutil.copy(STATIC_DIR / "style.css", output / "style.css")
    if deploy_dir is not None:
        for item in deploy_dir.iterdir():
            if item.is_file():
                shutil.copy(item, output / item.name)
