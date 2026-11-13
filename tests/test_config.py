from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_news.config import Config, ConfigError, load_config
from tests.conftest import CONFIG_DICT

ROOT = Path(__file__).resolve().parents[1]


def test_repository_config_is_valid() -> None:
    config = load_config(ROOT / "config.toml")
    assert config.edition.max_stories == 10
    assert config.edition.max_words == 3 * 230
    assert len(config.search_queries()) == 15


def test_search_queries_cartesian_product(config: Config) -> None:
    texts = [q.text for q in config.search_queries()]
    assert texts == ["actualité", "actualité Europe"]


def test_min_stories_above_max_rejected() -> None:
    raw = copy.deepcopy(CONFIG_DICT)
    raw["edition"] = {"max_stories": 2, "min_stories": 5}
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_unknown_key_rejected() -> None:
    raw = copy.deepcopy(CONFIG_DICT)
    raw["edition"] = {"max_storys": 2}
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_unknown_timezone_rejected() -> None:
    raw = copy.deepcopy(CONFIG_DICT)
    raw["site"] = {"title": "x", "timezone": "Mars/Olympus"}
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_missing_and_invalid_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        load_config(tmp_path / "absent.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("[site\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML invalide"):
        load_config(bad)
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="configuration invalide"):
        load_config(empty)
