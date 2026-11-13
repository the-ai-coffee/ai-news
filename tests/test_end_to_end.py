"""Pipeline complet avec API simulées, jusqu'au site HTML généré."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ai_news.budget import Budget
from ai_news.cli import EXIT_CONFIG, EXIT_NO_EDITION, main
from ai_news.config import Config
from ai_news.models import Edition
from ai_news.pipeline.run import InsufficientStoriesError, build_edition
from ai_news.render.render import render_site
from ai_news.sources.firecrawl import SearchHit
from ai_news.store import edition_id, load_editions, save_edition
from tests.fakes import FakeLLM, FakeSearch, assess_all

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 13, 18, 0, tzinfo=ZoneInfo("Europe/Paris"))


def _hit(domain: str, slug: str, text: str) -> SearchHit:
    return SearchHit(
        url=f"https://{domain}/{slug}",
        title=f"{slug} <script>alert(1)</script>",
        description="",
        markdown=text,
        published=None,
    )


ENERGY = [
    _hit("lemonde.fr", "energie", "Les 14 ministres ont signé l'accord le 12 novembre 2026."),
    _hit("reuters.com", "energy", "Ministers from 16 countries signed the deal on 12 November."),
    _hit("elpais.com", "energia", "Los ministros firmaron el acuerdo energético en Bruselas."),
]
BUDGET = [
    _hit("rfi.fr", "budget", "Le parlement a adopté la loi de finances 2027 en deuxième lecture."),
    _hit("jeuneafrique.com", "budget", "L'Assemblée vote le budget 2027 après un long débat."),
]
LONELY = [_hit("blog.example", "rumeur", "Une seule source évoque une rumeur non confirmée.")]


def _cluster(user: str) -> dict[str, Any]:
    ids = {a["outlet"]: a["id"] for a in json.loads(user)["articles"]}
    return {
        "events": [
            {
                "label": "Accord sur l'énergie",
                "impact": 0.8,
                "impact_reason": "UE entière",
                "article_ids": [ids["lemonde.fr"], ids["reuters.com"], ids["elpais.com"]],
            },
            {
                "label": "Budget 2027",
                "impact": 0.5,
                "impact_reason": "national",
                "article_ids": [ids["rfi.fr"], ids["jeuneafrique.com"]],
            },
            {
                "label": "Rumeur",
                "impact": 0.1,
                "impact_reason": "faible",
                "article_ids": [ids["blog.example"]],
            },
        ]
    }


def _summarize(user: str) -> dict[str, Any]:
    sources = json.loads(user)["sources"]
    if any(s["outlet"] == "lemonde.fr" for s in sources):
        return {
            "title": "Accord européen sur les achats de gaz <b>signé</b>",
            "essentiel": "Les ministres ont signé un accord le 12 novembre 2026. "
            "Le texte doit être ratifié.",
            "faits": "L'accord a été signé à Bruxelles. Il porte sur les achats communs de gaz.",
            "contexte": "Les discussions duraient depuis plusieurs mois.",
            "divergences": [
                {
                    "topic": "Nombre de pays signataires",
                    "positions": [
                        {"position": "14 pays", "sources": ["S1"]},
                        {"position": "16 pays", "sources": ["S2"]},
                    ],
                }
            ],
        }
    return {
        "title": "Le parlement adopte la loi de finances 2027",
        "essentiel": "Le parlement a adopté la loi de finances 2027. Le vote a eu lieu en "
        "deuxième lecture.",
        "faits": "Le texte a été adopté après un long débat.",
        "contexte": "",
        "divergences": [],
    }


def _build(config: Config, budget: Budget | None = None) -> Edition:
    budget = budget or Budget(50, 50)
    search = FakeSearch({"actualité": ENERGY + LONELY, "actualité Europe": BUDGET + ENERGY[:1]})
    llm = FakeLLM(assess=assess_all(), cluster=_cluster, summarize=_summarize, budget=budget)
    return build_edition(
        config=config, search=search, llm=llm, budget=budget, now=NOW, previous=None
    )


def test_full_pipeline_to_site(config: Config, tmp_path: Path) -> None:
    edition = _build(config)
    assert edition.id == "2026-11-13-pm"
    assert [s.title for s in edition.stories][1] == "Le parlement adopte la loi de finances 2027"
    assert edition.stories[0].independent_sources == 3
    assert edition.stats.articles_read == 6  # doublon d'URL entre requêtes ignoré
    assert any("1 source" in c.reason for c in edition.cut)
    assert len(edition.audit) == 6
    assert edition.stats.llm_calls == 4  # 1 évaluation + 1 regroupement + 2 rédactions

    data = tmp_path / "data"
    save_edition(edition, data)
    site = tmp_path / "site"
    render_site(load_editions(data), config, site, ROOT / "deploy")

    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Accord européen sur les achats de gaz" in index
    assert "Divergence :" in index and "Nombre de pays signataires" in index
    assert "Édition du soir · vendredi 13 novembre 2026 · 18h00" in index
    assert "<b>signé</b>" not in index and "&lt;b&gt;signé&lt;/b&gt;" in index  # échappement
    story = (site / "e" / edition.id / "01.html").read_text(encoding="utf-8")
    assert "14 pays" in story and "16 pays" in story
    assert "https://reuters.com/energy" in story
    audit = (site / "e" / edition.id / "audit.html").read_text(encoding="utf-8")
    assert "Rumeur" in audit and "<script>" not in audit
    assert (site / "archives" / "index.html").exists()
    assert (site / "style.css").exists()
    assert (site / "middleware.js").exists() and (site / "vercel.json").exists()


def test_max_stories_respected(config: Config) -> None:
    limited = config.model_copy(
        update={"edition": config.edition.model_copy(update={"max_stories": 1})}
    )
    edition = _build(limited)
    assert len(edition.stories) == 1
    assert any(c.reason == "Hors top 1." for c in edition.cut)


def test_insufficient_stories_not_published(config: Config) -> None:
    strict = config.model_copy(
        update={"edition": config.edition.model_copy(update={"min_sources": 5})}
    )
    with pytest.raises(InsufficientStoriesError):
        _build(strict)


def test_llm_budget_exhaustion_degrades_gracefully(config: Config) -> None:
    edition = _build(config, Budget(max_llm_calls=3, max_search_requests=50))
    assert len(edition.stories) == 1
    assert any("Budget épuisé" in c.reason for c in edition.cut)
    assert any("Rédaction interrompue" in i for i in edition.incidents)


def test_edition_ids_and_archive_order(config: Config, tmp_path: Path) -> None:
    morning = NOW.replace(hour=6)
    assert edition_id(morning) == "2026-11-13-am"
    first = _build(config).model_copy(update={"id": edition_id(morning), "generated_at": morning})
    second = _build(config)
    save_edition(first, tmp_path)
    save_edition(second, tmp_path)
    assert [e.id for e in load_editions(tmp_path)] == ["2026-11-13-pm", "2026-11-13-am"]
    site = tmp_path / "site"
    render_site(load_editions(tmp_path), config, site)
    assert "Édition archivée" in (site / "e" / "2026-11-13-am" / "index.html").read_text()
    assert "Édition archivée" not in (site / "index.html").read_text()


def test_cli_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["--config", str(tmp_path / "absent.toml"), "render"]) == EXIT_CONFIG
    config_path = str(ROOT / "config.toml")
    assert main(["--config", config_path, "--data", str(tmp_path), "render"]) == EXIT_NO_EDITION
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert main(["--config", config_path, "--data", str(tmp_path), "run"]) == EXIT_CONFIG
