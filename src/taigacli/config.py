from __future__ import annotations

import os
import stat
from pathlib import Path

from taigacli.errors import CliError

DEFAULT_API_URL = "https://api.taiga.io/api/v1"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "taigacli"


def env_file() -> Path:
    """Highest-precedence discovered .env, or the canonical user config path."""
    files = env_files()
    return files[0] if files else config_dir() / ".env"


def env_files() -> list[Path]:
    """Discovered .env files, highest precedence first.

    The nearest .env walking up from cwd wins; a project's own .env (e.g. a
    Django app) is never let to shadow files above it - we merge per key.
    The user config file is the global fallback for system-wide installs.
    """
    files: list[Path] = []
    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            files.append(candidate)
            break
    global_env = config_dir() / ".env"
    if global_env.is_file() and global_env not in files:
        files.append(global_env)
    return files


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
    merged: dict[str, str] = {}
    for path in reversed(env_files()):
        merged.update(parse_env_file(path))
    return merged


def api_url() -> str:
    """Resolved API URL with no validation, so login works before a slug is set."""
    env = os.environ
    cfg = load_env()
    return (env.get("TAIGA_API_URL") or cfg.get("TAIGA_API_URL", DEFAULT_API_URL)).rstrip("/")


def config() -> dict:
    env = os.environ
    cfg = load_env()
    out = {
        "api_url": api_url(),
        "username": env.get("TAIGA_USERNAME") or cfg.get("TAIGA_USERNAME"),
        "slug": env.get("TAIGA_PROJECT_SLUG") or cfg.get("TAIGA_PROJECT_SLUG"),
    }
    missing = [k for k in ("slug",) if not out[k] or "your_taiga" in out[k]]
    if missing:
        raise CliError(
            f"Missing config keys: {', '.join(missing)} - set TAIGA_* environment"
            f" variables or edit {env_file()}"
        )
    return out


def secure(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
