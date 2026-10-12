from __future__ import annotations

import json
import sys
import urllib.parse

import httpx

from taigacli.config import config, load_env, secure, token_file
from taigacli.errors import CliError
from taigacli.resources import STATUS_KINDS

_token_cache: dict[str, str] = {}


def get_token(cfg: dict, client: httpx.Client, refresh: bool = False) -> str:
    tf = token_file()
    if not refresh and tf.is_file():
        token = tf.read_text().strip()
        if token:
            return token
    print("Authenticating to Taiga...", file=sys.stderr, flush=True)
    payload = {"type": "normal", "username": cfg["username"], "password": cfg["password"]}
    response = client.post(f"{cfg['api_url']}/auth", json=payload)
    if response.status_code >= 400:
        raise CliError(f"Auth failed ({response.status_code}): {response.text}")
    token = response.json().get("auth_token")
    if not token:
        raise CliError("Auth succeeded but no auth_token returned")
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(token)
    secure(tf)
    _token_cache["token"] = token
    return token


def request(
    cfg: dict,
    client: httpx.Client,
    enrolled_token: str,
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
    soft: bool = False,
    retry: bool = True,
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
    if response.status_code == 401 and retry:
        token = get_token(cfg, client, refresh=True)
        return request(cfg, client, token, method, path, params, body, soft, retry=False)
    if response.status_code >= 400:
        raise CliError(f"API error {response.status_code} on {path}: {response.text}")
    resp_body = response.text
    resp = json.loads(resp_body) if resp_body else None
    next_link = response.headers.get("x-next")
    if next_link and url != next_link:
        more = request(cfg, client, enrolled_token, method, next_link, retry=False)
        if isinstance(resp, list) and isinstance(more, list):
            resp.extend(more)
    return resp


class Api:
    """Small stateful wrapper bundling config, token and an httpx client."""

    def __init__(self) -> None:
        self.cfg = config()
        self.client = httpx.Client(base_url=self.cfg["api_url"], follow_redirects=False)
        self.token = get_token(self.cfg, self.client)

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None, soft: bool = False):
        return request(self.cfg, self.client, self.token, method, path, params, body, soft)

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

__all__ = ["Api", "get_token", "load_env", "request", "config"]
