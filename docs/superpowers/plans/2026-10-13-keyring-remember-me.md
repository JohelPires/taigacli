# Remember-Me (Keyring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After one `taiga login`, the CLI silently re-authenticates on token expiry using a password stored in the OS keyring.

**Architecture:** A new soft-failing `taigacli.credentials` module wraps `keyring` (service `"taigacli"`, account = API URL, secret = `{"username","password"}` JSON). `api.request()` intercepts 401s: if a remembered credential exists it re-auths, rewrites the token file, and retries the request exactly once; otherwise today's behavior. `cmd_login`/`cmd_logout` save/forget the credential; remember is default-on with `--no-remember` opt-out; keyring-unavailable degrades to token-only with a warning.

**Tech Stack:** click, httpx, pytest; new dependency `keyring>=24`.

**Spec:** `docs/superpowers/specs/2026-10-13-keyring-remember-me-design.md`

## Global Constraints

- Tests never touch the real OS keyring (autouse fixture disables the keyring source).
- Token file (`token_file()`) format stays a bare token; `secure()` permission rules unchanged.
- All styling via `taigacli.theme` helpers (`paint`, `GUTTER`); no raw ANSI/Unicode.
- `.env` and token cache contents are never printed.
- Tests: `.venv/bin/python -m pytest` (offline; API + keyring mocked).

---

### Task 1: `credentials` module + test isolation

**Files:**
- Create: `src/taigacli/credentials.py`
- Create: `tests/conftest.py`
- Test: `tests/test_credentials.py`
- Modify: `pyproject.toml` (dependencies)

**Interfaces:**
- Produces (used by Tasks 2–3): `SERVICE = "taigacli"`, `available() -> bool`, `save(api_url: str, username: str, password: str) -> bool`, `load(api_url: str) -> tuple[str, str] | None`, `forget(api_url: str) -> bool`, and an introspectable `_keyring()` seam (returns a usable module/None) tests and `_no_keyring` patch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_credentials.py
from __future__ import annotations

import json
import sys

import pytest

from taigacli import credentials


class FakeKeyring:
    """In-memory stand-in for the keyring module."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            from keyring.errors import PasswordDeleteError
            raise PasswordDeleteError("not set")
        del self.store[(service, username)]


@pytest.fixture
def fake_kr(monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: kr)
    return kr


def test_save_load_roundtrip(fake_kr):
    assert credentials.save("https://a/api/v1", "alice", "pw") is True
    assert credentials.load("https://a/api/v1") == ("alice", "pw")
    # stored as a JSON blob so renewal needs only the API URL
    blob = json.loads(fake_kr.store[(credentials.SERVICE, "https://a/api/v1")])
    assert set(blob) == {"username", "password"}


def test_load_missing_returns_none(fake_kr):
    assert credentials.load("https://nothing/api/v1") is None


def test_keyring_unavailable(fake_kr, monkeypatch):
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    assert credentials.available() is False
    assert credentials.save("https://a/api/v1", "u", "p") is False
    assert credentials.load("https://a/api/v1") is None
    assert credentials.forget("https://a/api/v1") is False


def test_forget_removes_entry(fake_kr):
    credentials.save("https://a/api/v1", "alice", "pw")
    assert credentials.forget("https://a/api/v1") is True
    assert credentials.load("https://a/api/v1") is None
    assert credentials.forget("https://a/api/v1") is False


def test_corrupt_entry_degrades(fake_kr):
    fake_kr.store[(credentials.SERVICE, "https://a/api/v1")] = "not json"
    assert credentials.load("https://a/api/v1") is None
    credentials.forget("https://a/api/v1")  # forget clears regardless of decode


def test_corrupt_secret_forget_still_clears(fake_kr):
    fake_kr.store[(credentials.SERVICE, "https://a/api/v1")] = "not json"
    assert credentials.forget("https://a/api/v1") is True


def test_missing_keyring_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import raises ImportError
    assert credentials.load("https://a/api/v1") is None
    assert credentials.available() is False
```

Add `tests/conftest.py` so no test ever touches the real OS keyring:

```python
# tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch):
    """Keep tests offline of the real OS keyring: `credentials._keyring` -> None."""
    monkeypatch.setattr("taigacli.credentials._keyring", lambda: None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'taigacli.credentials'` (or ImportError on unknown attribute inside `conftest`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/taigacli/credentials.py
from __future__ import annotations

import json

# Remembered login for silent token renewal: the OS keyring keeps the
# password so the CLI can authenticate again when a token expires.
# Every operation soft-fails — no keyring means "not remembered", not a crash.

SERVICE = "taigacli"


def _keyring():
    """The keyring module, or None when unavailable/unusable."""
    try:
        import keyring
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        from keyring.backends import fail

        if isinstance(backend, fail.Keyring):
            return None
    except Exception:
        return None
    return keyring


def available() -> bool:
    return _keyring() is not None


def save(api_url: str, username: str, password: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(
            SERVICE, api_url, json.dumps({"username": username, "password": password})
        )
        return True
    except Exception:
        return False


def load(api_url: str) -> tuple[str, str] | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        secret = kr.get_password(SERVICE, api_url)
    except Exception:
        return None
    if not secret:
        return None
    try:
        blob = json.loads(secret)
        username, password = blob["username"], blob["password"]
    except (ValueError, KeyError, TypeError):
        return None
    if not username or not password:
        return None
    return username, password


def forget(api_url: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, api_url)
        return True
    except Exception:
        return False
```

Add the dependency in `pyproject.toml`:

```toml
dependencies = [
    "click>=8.1",
    "httpx>=0.27",
    "keyring>=24",
    "markdownify>=0.13",
    "beautifulsoup4>=4.12",
]
```

Then refresh the editable install (only needed because deps changed):
`uv tool install --editable /home/johel-pires/Documentos/GitHub/taigacli --force` (if run outside the repo venv) — or simply `uv pip install keyring --python .venv/bin/python` for the test venv.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_credentials.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/taigacli/credentials.py tests/test_credentials.py tests/conftest.py pyproject.toml
git commit -m "feat: keyring-backed credential store for remember-me"
```

---

### Task 2: silent renewal on 401 in `api.py`

**Files:**
- Modify: `src/taigacli/api.py`
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `credentials.load(api_url) -> tuple[str, str] | None` from Task 1.
- Produces: `_auth(api_url: str, username: str, password: str, client) -> str` (raises `CliError`); `_renew(cfg: dict, client) -> str | None`; `_cache_token(token: str) -> None`; `login(api_url, username, password, client, remember: bool = True) -> str` (pure auth + cache, does NOT touch the keyring — saving is `cmd_login`'s job); `request(cfg, client, enrolled_token, method, path, params=None, body=None, soft=False, _retried: bool = False)`; `Api.call` re-reads the token file so `self.token` survives renewals.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py` (imports already in place: `api_mod`, `StubResponse`, `StubClient`, `CliError`, `token_store` fixture):

```python
class RenewClient:
    """401 on N-1 requests, then 200; /auth always yields 'fresh'."""

    def __init__(self,expire_times=1):
        self.requests = 0
        self.expire_times = expire_times
        self.auth_calls = 0

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.requests += 1
        return (
            StubResponse(401)
            if self.requests <= self.expire_times
            else StubResponse(200, {"id": 1})
        )

    def post(self, url, json=None):
        self.auth_calls += 1
        return StubResponse(200, {"auth_token": "fresh"})


def test_request_401_renews_and_retries_once(token_store, monkeypatch):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    monkeypatch.setattr(api_mod.credentials, "load", lambda url: ("user", "pass"))
    client = RenewClient()
    resp = api_mod.request({"api_url": "http://x"}, client, "stale", "GET", "users/me")
    assert resp == {"id": 1}
    assert token_store.read_text() == "fresh"       # token file rewritten silently
    assert (token_store.stat().st_mode & 0o777) == 0o600


def test_request_401_no_credential_keeps_current_behavior(token_store, monkeypatch):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    monkeypatch.setattr(api_mod.credentials, "load", lambda url: None)
    client = StubClient({"request": StubResponse(401)})
    with pytest.raises(CliError) as exc:
        api_mod.request({"api_url": "http://x"}, client, "stale", "GET", "users/me")
    assert "taiga login" in str(exc.value)
    assert not token_store.exists()                  # stale token still cleared


def test_request_401_renew_auth_failure_falls_back(token_store, monkeypatch):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    monkeypatch.setattr(api_mod.credentials, "load", lambda url: ("user", "pass"))
    client = StubClient({"request": StubResponse(401), "post": StubResponse(400, text="bad")})
    with pytest.raises(CliError) as exc:
        api_mod.request({"api_url": "http://x"}, client, "stale", "GET", "users/me")
    assert "taiga login" in str(exc.value)


def test_request_renewal_never_loops(token_store, monkeypatch):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    monkeypatch.setattr(api_mod.credentials, "load", lambda url: ("user", "pass"))
    client = RenewClient(expire_times=99)            # even a fresh token 401s
    with pytest.raises(CliError) as exc:
        api_mod.request({"api_url": "http://x"}, client, "stale", "GET", "users/me")
    assert "taiga login" in str(exc.value)
    assert client.auth_calls == 1                    # exactly one re-auth attempt


def test_api_call_picks_up_renewed_token(token_store, monkeypatch):
    monkeypatch.setenv("TAIGA_PROJECT_SLUG", "proj")

    real_request = api_mod.request

    def renewing_request(cfg, client, token, method, path, *a, **k):
        real_request(cfg, client, token, method, path, *a, **k) if False else None
        token_store.write_text("fresh")              # simulate internal renewal
        return {"ok": True}

    monkeypatch.setattr(api_mod, "request", renewing_request)
    api = api_mod.Api()
    api.call("GET", "users/me")
    assert api.token == "fresh"                      # self.token synced from the file
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_auth.py -v -k renew`
Expected: FAIL — `AttributeError: ... has no attribute 'credentials'` (module attribute missing) or assertion that renewal didn't happen.

- [ ] **Step 3: Write minimal implementation**

In `src/taigacli/api.py` replace `login()` and the 401 branch of `request()`:

```python
from taigacli import credentials
from taigacli.config import config, secure, token_file


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
```

In `request()`, extend the signature and 401 branch (keep everything else identical):

```python
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
```

In `Api.call()`, sync the in-memory token with any renewal the file picked up:

```python
    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None, soft: bool = False):
        result = request(self.cfg, self.client, self.token, method, path, params, body, soft)
        fresh = load_token()
        if fresh and fresh != self.token:
            self.token = fresh
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_auth.py -v`
Expected: PASS — including all pre-existing auth tests (`test_request_401_clears_and_raises` still holds because no keyring credential exists in tests).

- [ ] **Step 5: Commit**

```bash
git add src/taigacli/api.py tests/test_auth.py
git commit -m "feat: silent token renewal on 401 via remembered keyring credential"
```

---

### Task 3: `login`/`logout` CLI behavior

**Files:**
- Modify: `src/taigacli/commands.py:294-367` (`cmd_login`, `cmd_logout`)
- Modify: `src/taigacli/cli.py:83-100` (`login_cmd` flag)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `credentials.save/forget/available` (Task 1); `login(...)` signature from Task 2.
- Produces: `cmd_login(api_url, username, password, ctx, remember: bool = True)`; `cmd_logout(ctx)` (unchanged signature, also forgets the keyring). CLI flag `--remember/--no-remember` on `login` (default remember). JSON gains `remembered` (login) / `remembered_removed` (logout).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:

```python
def test_cmd_login_remembered_message(fake_http, token_store, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"full_name": "Jane Doe"})
    monkeypatch.setattr("taigacli.commands.credentials.save", lambda *a: True)
    monkeypatch.setattr("taigacli.commands.credentials.forget", lambda *a: False)
    commands.cmd_login("http://x/api", "user", "pass", _ctx())
    out = capsys.readouterr().out
    assert "remembered via OS keyring" in out


def test_cmd_login_keyring_unavailable_warns(fake_http, token_store, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"full_name": "Jane Doe"})
    monkeypatch.setattr("taigacli.commands.credentials.save", lambda *a: False)
    monkeypatch.setattr("taigacli.commands.credentials.forget", lambda *a: False)
    commands.cmd_login("http://x/api", "user", "pass", _ctx())
    out = capsys.readouterr().out
    assert "keyring unavailable" in out
    assert "remembered via OS keyring" not in out


def test_cmd_login_no_remember_saves_nothing(fake_http, token_store, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"full_name": "Jane Doe"})
    saved = []

    def _guard(*a):
        saved.append(a)

    monkeypatch.setattr("taigacli.commands.credentials.save", _guard)
    commands.cmd_login("http://x/api", "user", "pass", _ctx(), remember=False)
    assert saved == []
    assert "keyring unavailable" not in capsys.readouterr().out


def test_cmd_login_json_reports_remembered(fake_http, token_store, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"id": 7})
    monkeypatch.setattr("taigacli.commands.credentials.save", lambda *a: True)
    commands.cmd_login("http://x/api", "user", "pass", _ctx(json=True))
    assert json.loads(capsys.readouterr().out) == {
        "already_logged_in": False, "user": {"id": 7}, "remembered": True,
    }


def test_cmd_logout_forgets_credential(fake_http, token_store, monkeypatch, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("t")
    monkeypatch.setenv("TAIGA_API_URL", "http://x/api")
    calls = []
    monkeypatch.setattr("taigacli.commands.credentials.forget", lambda url: calls.append(url) or True)
    commands.cmd_logout(_ctx())
    assert calls == ["http://x/api"]
    out = capsys.readouterr().out
    assert "removed" in out and "remembered" in out


def test_cmd_logout_without_credential_stays_quiet(fake_http, token_store, monkeypatch, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("t")
    monkeypatch.setattr("taigacli.commands.credentials.forget", lambda url: False)
    commands.cmd_logout(_ctx())
    assert "removed" in capsys.readouterr().out


def test_cli_login_no_remember_flag(token_store, fake_http, monkeypatch):
    token_store.parent.mkdir(parents=True)
    monkeypatch.setenv("TAIGA_USERNAME", "user")
    monkeypatch.setattr(api_mod, "login", lambda *a, **k: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"id": 7})
    monkeypatch.setattr("taigacli.commands.credentials.save", lambda *a: (_ for _ in ()).throw(AssertionError("must not save")))
    result = CliRunner().invoke(cli.taiga, ["login", "--password", "pw", "--no-remember"], catch_exceptions=False)
    assert result.exit_code == 0
    assert token_store.read_text() == "tok-1"
```

Note: pre-existing tests `test_cmd_login_prints_user_but_not_token`, `test_cmd_login_json`, `test_cmd_login_json_never_contains_token`, `test_cmd_login_expired_token_relogins` call `cmd_login` without `remember`; they end up exercising keyring-unavailable mode (the autouse `_no_keyring` fixture makes `credentials.save` return False) and must still pass — check their assertions: they only fail if `cmd_login` raises. The added warning line is extra text on an otherwise passing path, which is fine.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_auth.py -v -k "remembered or no_remember or forgets_credential"`
Expected: FAIL — `cmd_login` has no `remember` parameter; `cmd_logout` doesn't call `credentials.forget`; messages absent.

- [ ] **Step 3: Write minimal implementation**

In `cli.py`, extend `login_cmd`:

```python
@taiga.command(name="login", help="sign in and cache an auth token")
@click.option("--username", "-u", default=None, help="Taiga username or email")
@click.option("--password", default=None, help="Taiga password (prefer the prompt)")
@click.option(
    "--remember/--no-remember",
    default=True,
    help="keep the password in the OS keyring so tokens renew silently (default: remember)",
)
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def login_cmd(ctx, username, password, remember, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_login(api_url(), username, password, ctx, remember=remember)
```

In `commands.py`, `cmd_login` gains the remember params/messages (top of `cmd_login` imports `credentials`):

```python
def cmd_login(api_url: str, username: str | None, password: str | None, ctx, remember: bool = True):
    import click
    import httpx

    from taigacli import api as api_mod
    from taigacli.config import load_env

    client = httpx.Client(base_url=api_url, follow_redirects=False)
    if not _print_session(api_mod, client, api_url, username, ctx):
        return
    if username is None:
        default = load_env().get("TAIGA_USERNAME")
        username = click.prompt("Username", default=default, show_default=bool(default))
    if password is None:
        password = click.prompt("Password", hide_input=True)
    token = api_mod.login(api_url, username, password, client)
    remembered = remember and credentials.save(api_url, username, password)
    me = _me(api_mod, client, token, api_url)
    user = me if isinstance(me, dict) else {}
    if is_json(ctx):
        print(json.dumps({"already_logged_in": False, "user": user, "remembered": remembered}))
        return
    name = user.get("full_name") or user.get("username") or username
    print()
    print(GUTTER + paint(g("dot"), "ready") + " " + paint(str(name), "ink", bold=True))
    if remembered:
        print(GUTTER + paint("logged in - token saved - remembered via OS keyring", "muted"))
    else:
        print(GUTTER + paint("logged in - token saved", "muted"))
        if remember:
            print(GUTTER + paint(
                "keyring unavailable; you will be asked to log in again when the token expires",
                "muted",
            ))
    print()
```

(`credentials` is imported once at the top of `commands.py`: `from taigacli import credentials` — alongside the existing header imports; the function-level imports stay as they are.)

`cmd_logout` also forgets the remembered credential:

```python
def cmd_logout(ctx):
    from taigacli import api as api_mod
    from taigacli.api import clear_token
    from taigacli.config import api_url, token_file

    path = token_file()
    remembered_removed = credentials.forget(api_url())
    if clear_token():
        if is_json(ctx):
            print(json.dumps({"logged_out": True, "token_file": str(path), "remembered_removed": remembered_removed}))
            return
        print(GUTTER + paint(f"removed {path}", "muted"))
        if remembered_removed:
            print(GUTTER + paint("forgot the remembered login", "muted"))
    else:
        if is_json(ctx):
            print(json.dumps({"logged_out": False, "token_file": str(path), "remembered_removed": remembered_removed}))
            return
        if remembered_removed:
            print(GUTTER + paint("forgot the remembered login", "muted"))
        else:
            print(GUTTER + paint("not logged in", "muted"))
```

(If another module in `commands.py` already imports `api_mod` differently, reuse that pattern; the key point is `credentials.forget(api_url())` runs before/after `clear_token()` regardless of outcome.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_auth.py -v`
Expected: PASS (all tests, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/taigacli/cli.py src/taigacli/commands.py tests/test_auth.py
git commit -m "feat: login remembers via keyring by default; logout forgets it"
```

---

### Task 4: README, AGENTS, full verification

**Files:**
- Modify: `README.md` (login/logout bullets around lines 19/25/31/57/71)
- Modify: `AGENTS.md` (Layout list, Environment, Install note)

**Interfaces:**
- Consumes: final CLI surface from Task 3. Docs must mirror `taiga --help`.

- [ ] **Step 1: Update README**

- Command list row: `| login | Sign in once; saves the auth token and remembers it in the OS keyring (default; `--no-remember` opts out) |` and `| logout | Delete the cached auth token and the remembered keyring credential |`.
- Login flags line: mention `--remember/--no-remember`.
- Paragraph (around line 31): rewrite "the password stays hidden when prompted" behavior to: once authenticated, the password is kept in the OS keyring (service `taigacli`) keyed by API URL so an expired token renews silently on the next command; when no keyring backend is available the password is never stored and the CLI warns that you will be prompted again on next expiry. `taiga logout` removes both token and remembered login. Keeping the password in the keyring is equivalent to a browser's saved passwords; anyone with access to the unlocked keyring session could retrieve it.

- [ ] **Step 2: Update AGENTS.md**

- Layout: new bullet for `src/taigacli/credentials.py` — "keyring store for remembered logins (`available/save/load/forget`); soft-fails when no backend; never surfaces raw errors."
- Environment: one line noting the remembered credential lives in the OS keyring, not on disk beside the token.
- Dependencies list mention: `keyring` runtime dep.

- [ ] **Step 3: Full verification**

Run:
```bash
.venv/bin/python -m pytest
.venv/bin/taiga --help
```
Expected: all tests PASS; `login` help shows `--remember / --no-remember`; README bullets match help text.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: remember-me via OS keyring"
```
