from __future__ import annotations

import os
import stat
from pathlib import Path

from taigacli.errors import CliError


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "taigacli"


def env_file() -> Path:
    paths = []
    cwd = Path.cwd().resolve()
    paths.extend(cwd.parents)
    paths.insert(0, cwd)
    for directory in paths:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return cwd / ".env"


def token_file() -> Path:
    override = os.environ.get("TAIGA_TOKEN_FILE")
    if override:
        return Path(override).expanduser()
    return config_dir() / ".token"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def load_env() -> dict:
    path = env_file()
    if not path.is_file():
        raise CliError(f"Missing env file: {path}")
    return parse_env_file(path)


def config() -> dict:
    env = os.environ
    cfg = load_env()
    out = {
        "api_url": env.get("TAIGA_API_URL") or cfg.get("TAIGA_API_URL", "https://api.taiga.io/api/v1").rstrip("/"),
        "username": env.get("TAIGA_USERNAME") or cfg.get("TAIGA_USERNAME"),
        "password": env.get("TAIGA_PASSWORD") or cfg.get("TAIGA_PASSWORD"),
        "slug": env.get("TAIGA_PROJECT_SLUG") or cfg.get("TAIGA_PROJECT_SLUG"),
    }
    missing = [k for k in ("username", "password", "slug") if not out[k] or "your_taiga" in out[k]]
    if missing:
        from taigacli.errors import CliError

        raise CliError(f"Missing config keys: {', '.join(missing)} - edit {env_file()}")
    return out


def secure(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
