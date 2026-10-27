from __future__ import annotations

import json
import urllib.parse

import httpx

from taigacli import credentials
from taigacli.config import config, secure, token_file
from taigacli.errors import CliError
from taigacli.resources import HISTORY_KINDS, STATUS_KINDS


NOT_LOGGED_IN = "Not logged in - run `taiga login`"


def load_token() -> str | None:
    tf = token_file()
    if tf.is_file():
        token = tf.read_text().strip()
        if token:
            return token
    return None


def get_token(cfg: dict, client: httpx.Client) -> str:
    token = load_token()
    if token:
        return token
    raise CliError(NOT_LOGGED_IN)


def _auth(api_url: str, username: str, password: str, client: httpx.Client) -> str:
    payload = {"type": "normal", "username": username, "password": password}
    try:
        response = client.post(f"{api_url}/auth", json=payload)
    except httpx.HTTPError as e:
        raise CliError(f"Connection error: {e}")
    if response.status_code >= 400:
        raise CliError(f"Login failed ({response.status_code}): {response.text}")
    token = response.json().get("auth_token")
    if not token:
        raise CliError("Login succeeded but no auth_token returned")
    return token


def _cache_token(token: str) -> None:
    tf = token_file()
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(token)
    secure(tf)


def login(api_url: str, username: str, password: str, client: httpx.Client) -> str:
    """Authenticate and cache the token. Saving credentials is cmd_login's job."""
    token = _auth(api_url, username, password, client)
    _cache_token(token)
    return token


def _renew(cfg: dict, client: httpx.Client) -> str | None:
    """Silent renewal: re-auth with the remembered keyring credential."""
    api_url_val = cfg.get("api_url", "")
    cred = credentials.load(api_url_val)
    if cred is None:
        return None
    username, password = cred
    try:
        token = _auth(api_url_val, username, password, client)
    except CliError:
        return None
    _cache_token(token)
    return token


def clear_token() -> bool:
    tf = token_file()
    if tf.is_file():
        tf.unlink()
        return True
    return False


def request(
    cfg: dict,
    client: httpx.Client,
    enrolled_token: str,
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
    soft: bool = False,
    _retried: bool = False,
):
    url = path if path.startswith("http") else f"{cfg['api_url']}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    headers = {"Authorization": f"Bearer {enrolled_token}"}
    try:
        response = client.request(method, url, json=body if body is not None else None, headers=headers, timeout=30.0)
    except httpx.HTTPError as e:
        raise CliError(f"Connection error: {e}")
    if response.status_code == 404 and soft:
        return None
    if response.status_code == 401:
        # remembered credential: re-auth silently and retry once (browser-like)
        fresh = _renew(cfg, client) if not _retried else None
        if fresh:
            return request(cfg, client, fresh, method, path, params, body, soft, _retried=True)
        clear_token()
        raise CliError("Session expired - run `taiga login`")
    if response.status_code >= 400:
        raise CliError(f"API error {response.status_code} on {path}: {response.text}")
    resp_body = response.text
    resp = json.loads(resp_body) if resp_body else None
    next_link = response.headers.get("x-next")
    if next_link and url != next_link:
        more = request(cfg, client, enrolled_token, method, next_link)
        if isinstance(resp, list) and isinstance(more, list):
            resp.extend(more)
    return resp


class Api:
    """Small stateful wrapper bundling config, token and an httpx client."""

    def __init__(self, require_project: bool = True) -> None:
        self.cfg = config(require_slug=require_project)
        self.client = httpx.Client(base_url=self.cfg["api_url"], follow_redirects=False)
        self.token = get_token(self.cfg, self.client)

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None, soft: bool = False):
        result = request(self.cfg, self.client, self.token, method, path, params, body, soft)
        fresh = load_token()
        if fresh and fresh != self.token:
            self.token = fresh
        return result

    def get(self, path: str, params: dict | None = None, soft: bool = False):
        return self.call("GET", path, params=params, soft=soft)

    def patch(self, path: str, body: dict):
        return self.call("PATCH", path, body=body)

    def by_ref(self, path: str, ref: int, soft: bool = False) -> dict:
        item = self.get(f"{path}/by_ref", params={"ref": ref, "project": self.project_id()}, soft=soft)
        if item is None and soft:
            return None
        if isinstance(item, list):
            if not item:
                if soft:
                    return None
                raise CliError(f"Not found: {path} ref {ref}")
            item = item[0]
        else:
            if item is None and soft:
                return None
            if item is None:
                raise CliError(f"Not found: {path} ref {ref}")
        return item

    _PROJECT_CACHE: dict[tuple, dict] = {}

    def project(self) -> dict:
        if not self.cfg.get("slug"):
            raise CliError("No project selected - run `taiga projects`, then `taiga project <slug|id>`")
        cache_key = (self.cfg["api_url"], self.cfg["slug"], self.token)
        if cache_key in Api._PROJECT_CACHE:
            return Api._PROJECT_CACHE[cache_key]
        proj = self.get("projects/by_slug", params={"slug": self.cfg["slug"]})
        if isinstance(proj, dict) and proj.get("id"):
            Api._PROJECT_CACHE[cache_key] = proj
            return proj
        raise CliError(f"Could not resolve project by slug '{self.cfg['slug']}': {proj}")

    def project_id(self) -> int:
        return self.project()["id"]

    def load_statuses(self, project_id_val: int, resource: str) -> list[dict]:
        kinds = STATUS_KINDS.get(resource)
        if not kinds:
            raise CliError(f"No statuses for resource '{resource}' - choose from: userstories, tasks, issues")
        data = self.get(kinds, params={"project": project_id_val}) or []
        return sorted(data, key=lambda s: (s.get("order") or 0, s.get("id") or 0))

    # best-effort reads for the markdown export: a failure omits the section
    def history(self, resource: str, item_id: int):
        kind = HISTORY_KINDS.get(resource)
        if not kind or not item_id:
            return None
        try:
            return self.get(f"history/{kind}/{item_id}", soft=True)
        except CliError:
            return None

    def attachments(self, resource: str, item_id: int):
        if not item_id:
            return None
        try:
            return self.get(f"{resource}/attachments", params={"object_id": item_id}, soft=True)
        except CliError:
            return None

    def child_tasks(self, story_id: int):
        if not story_id:
            return None
        try:
            return self.get("tasks", params={"user_story": story_id}, soft=True)
        except CliError:
            return None


__all__ = ["Api", "get_token", "load_token", "login", "clear_token", "load_env", "request", "config"]
