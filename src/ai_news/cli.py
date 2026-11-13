"""Point d'entrée : `ai-news run` (pipeline complet) et `ai-news render` (site seul)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_news.budget import Budget
from ai_news.config import ConfigError, load_config
from ai_news.llm import DeepSeekClient
from ai_news.pipeline.cluster import ClusterError
from ai_news.pipeline.run import InsufficientStoriesError, build_edition
from ai_news.render.render import render_site
from ai_news.sources.firecrawl import FirecrawlClient
from ai_news.store import load_editions, save_edition

log = logging.getLogger("ai_news")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NO_EDITION = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-news", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--data", type=Path, default=Path("data/editions"))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--deploy-dir", type=Path, default=Path("deploy"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="génère une nouvelle édition puis le site")
    run.add_argument(
        "--dry-run", action="store_true", help="n'enregistre rien, affiche l'édition en JSON"
    )
    sub.add_parser("render", help="régénère le site à partir des éditions existantes")
    return parser


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"variable d'environnement manquante : {name}")
    return value


def _render(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    editions = load_editions(args.data)
    if not editions:
        log.error("aucune édition dans %s", args.data)
        return EXIT_NO_EDITION
    deploy_dir = args.deploy_dir if args.deploy_dir.is_dir() else None
    render_site(editions, config, args.site, deploy_dir)
    log.info("site généré dans %s (%d éditions)", args.site, len(editions))
    return EXIT_OK


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    budget = Budget(config.budget.max_llm_calls, config.budget.max_search_requests)
    search = FirecrawlClient(
        _require_env("FIRECRAWL_API_KEY"),
        budget,
        limit=config.search.results_per_query,
        tbs=config.search.tbs,
    )
    llm = DeepSeekClient(_require_env("DEEPSEEK_API_KEY"), config.llm, budget)
    previous = load_editions(args.data)
    try:
        edition = build_edition(
            config=config,
            search=search,
            llm=llm,
            budget=budget,
            now=datetime.now(ZoneInfo(config.site.timezone)),
            previous=previous[0] if previous else None,
        )
    except (InsufficientStoriesError, ClusterError) as exc:
        log.error("édition non publiée : %s", exc)
        return EXIT_NO_EDITION
    if args.dry_run:
        sys.stdout.write(edition.model_dump_json(indent=2) + "\n")
        return EXIT_OK
    path = save_edition(edition, args.data)
    log.info("édition enregistrée : %s", path)
    return _render(args)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        return _run(args) if args.command == "run" else _render(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
