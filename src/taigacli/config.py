from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from taigacli.errors import CliError

DEFAULT_API_URL = "https://api.taiga.io/api/v1"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "taigacli"


def current_project_file() -> Path:
    return config_dir() / "current_project.json"


def load_current_project() -> dict | None:
    """Stored switch, or None when absent/corrupt."""
    path = current_project_file()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("slug"):
        return None
    return data


def save_current_project(project: dict, api_url_val: str | None = None) -> Path:
    """Persist the switched project atomically; returns the file path."""
    path = current_project_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "api_url": api_url_val if api_url_val is not None else api_url(),
        "id": project.get("id"),
        "slug": project.get("slug"),
        "name": project.get("name") or project.get("slug"),
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    os.replace(tmp, path)
    secure(path)
    return path


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


def config(require_slug: bool = True) -> dict:
    """Resolve api_url/username/slug.

    Slug precedence: stored `taiga project` switch > TAIGA_PROJECT_SLUG env
    var > .env files. The stored switch is honored only when its api_url
    matches the resolved one, so pointing TAIGA_API_URL elsewhere falls back
    to per-instance config instead of a stale cross-instance slug.
    """
    env = os.environ
    cfg = load_env()
    resolved_url = api_url()
    out = {
        "api_url": resolved_url,
        "username": env.get("TAIGA_USERNAME") or cfg.get("TAIGA_USERNAME"),
        "slug": None,
    }
    stored = load_current_project()
    if stored and stored.get("slug") and stored.get("api_url") in (None, resolved_url):
        out["slug"] = str(stored.get("slug"))
    env_slug = env.get("TAIGA_PROJECT_SLUG") or cfg.get("TAIGA_PROJECT_SLUG")
    if not out["slug"] and env_slug and "your_taiga" not in env_slug:
        out["slug"] = env_slug
    if require_slug and not out["slug"]:
        raise CliError(
            f"Missing config keys: slug - set TAIGA_PROJECT_SLUG, run `taiga projects`"
            f" and `taiga project <slug|id>`, or edit {env_file()}"
        )
    return out


def secure(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
