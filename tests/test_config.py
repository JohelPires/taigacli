from __future__ import annotations

import os
from pathlib import Path

import pytest

from taigacli import config as config_mod
from taigacli.config import api_url, config, env_files, parse_env_file
from taigacli.errors import CliError


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    home = tmp_path / "xdgconfig" / "taigacli"
    home.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "config_dir", lambda: home)
    return home


def _clear_taiga_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TAIGA_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def no_taiga_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TAIGA_"):
            monkeypatch.delenv(key, raising=False)


def test_parse_env_file_ignores_comments_and_bad_lines(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nBADLINE\n\nB = 2 \n")
    assert parse_env_file(f) == {"A": "1", "B": "2"}


def test_walk_up_finds_repo_env(cwd: Path, config_home):
    (cwd / ".env").write_text("TAIGA_USERNAME=from-repo\n")
    files = env_files()
    assert files[0] == cwd / ".env"


def test_global_fallback_when_no_local_env(cwd: Path, config_home: Path):
    (config_home / ".env").write_text("TAIGA_USERNAME=from-global\n")
    files = env_files()
    assert files == [config_home / ".env"]


def test_local_env_shadows_global_but_merges_per_key(cwd: Path, config_home: Path):
    (config_home / ".env").write_text("TAIGA_USERNAME=global-user\nTAIGA_PASSWORD=global-pass\n")
    (cwd / ".env").write_text("TAIGA_USERNAME=local-user\n")
    values = config_mod.load_env()
    assert values["TAIGA_USERNAME"] == "local-user"
    assert values["TAIGA_PASSWORD"] == "global-pass"


def test_env_vars_beat_files(cwd: Path, config_home: Path, monkeypatch):
    (config_home / ".env").write_text("TAIGA_USERNAME=file-user\nTAIGA_PROJECT_SLUG=file-slug\n")
    monkeypatch.setenv("TAIGA_USERNAME", "env-user")
    out = config()
    assert out["username"] == "env-user"
    assert "password" not in out


def test_foreign_project_env_does_not_hijack(cwd: Path, config_home: Path, no_taiga_env):
    # a unrelated .env (like a backend's) missing TAIGA keys, global fills in
    (cwd / ".env").write_text("DATABASE_URL=postgres://x\n")
    (config_home / ".env").write_text("TAIGA_PROJECT_SLUG=s\n")
    out = config()
    assert out["slug"] == "s"


def test_config_rejects_missing_slug(cwd: Path, config_home, no_taiga_env, monkeypatch):
    monkeypatch.setenv("TAIGA_PROJECT_SLUG", "")
    with pytest.raises(CliError) as exc:
        config()
    assert "Missing config keys: slug" in str(exc.value)


def test_missing_file_only_fails_on_missing_keys(cwd: Path, config_home, monkeypatch):
    for key in list(os.environ):
        if key.startswith("TAIGA_"):
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(CliError) as exc:
        config()
    assert "Missing config keys" in str(exc.value)


def test_env_vars_only_no_env_files(cwd: Path, config_home, monkeypatch):
    monkeypatch.setenv("TAIGA_USERNAME", "u")
    monkeypatch.setenv("TAIGA_PROJECT_SLUG", "s")
    out = config()
    assert out == {
        "api_url": "https://api.taiga.io/api/v1",
        "username": "u",
        "slug": "s",
    }


def test_api_url_default_and_env_override(cwd: Path, config_home, monkeypatch):
    monkeypatch.delenv("TAIGA_API_URL", raising=False)
    assert api_url() == "https://api.taiga.io/api/v1"
    monkeypatch.setenv("TAIGA_API_URL", "http://taiga.local/api/v1/")
    assert api_url() == "http://taiga.local/api/v1"


def test_api_url_from_env_file(cwd: Path, config_home, monkeypatch):
    monkeypatch.delenv("TAIGA_API_URL", raising=False)
    (config_home / ".env").write_text("TAIGA_API_URL=http://filehost/api/v1\n")
    assert api_url() == "http://filehost/api/v1"
