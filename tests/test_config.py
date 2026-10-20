"""Tests for Databento API key resolution."""

from __future__ import annotations

import pytest

from sofr_data import config


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    """Point `API_KEY_FILE` at a temp path and clear the environment variable."""
    path = tmp_path / ".databento_api_key"
    monkeypatch.setattr(config, "API_KEY_FILE", path)
    monkeypatch.delenv(config.API_KEY_ENV, raising=False)
    return path


def test_key_file_is_used(key_file) -> None:
    key_file.write_text("db-from-file\n")
    assert config.resolve_api_key() == "db-from-file"


def test_key_file_wins_over_environment(key_file, monkeypatch) -> None:
    key_file.write_text("db-from-file")
    monkeypatch.setenv(config.API_KEY_ENV, "db-from-env")
    assert config.resolve_api_key() == "db-from-file"


@pytest.mark.parametrize("contents", ["", "\n", "   \n\n  "])
def test_empty_key_file_falls_back_to_environment(key_file, monkeypatch, contents) -> None:
    """An empty or blank file used to raise IndexError instead of falling back."""
    key_file.write_text(contents)
    monkeypatch.setenv(config.API_KEY_ENV, "db-from-env")
    assert config.resolve_api_key() == "db-from-env"


def test_leading_blank_lines_are_skipped(key_file) -> None:
    key_file.write_text("\n\n  db-after-blanks  \n")
    assert config.resolve_api_key() == "db-after-blanks"


def test_missing_key_file_falls_back_to_environment(key_file, monkeypatch) -> None:
    monkeypatch.setenv(config.API_KEY_ENV, "db-from-env")
    assert not key_file.exists()
    assert config.resolve_api_key() == "db-from-env"


@pytest.mark.parametrize("contents", [None, "", "  \n"])
def test_no_key_anywhere_gives_the_helpful_error(key_file, contents) -> None:
    if contents is not None:
        key_file.write_text(contents)
    with pytest.raises(FileNotFoundError, match="No Databento API key found"):
        config.resolve_api_key()
