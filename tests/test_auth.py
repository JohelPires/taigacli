from __future__ import annotations

import json

import httpx
import pytest
from click.testing import CliRunner

import taigacli.cli as cli
from taigacli import api as api_mod
from taigacli import commands
from taigacli.api import clear_token, get_token, login
from taigacli.errors import CliError
from taigacli.theme import ui_init


@pytest.fixture(autouse=True)
def _plain():
    ui_init(plain=True)


@pytest.fixture
def token_store(tmp_path, monkeypatch):
    tok = tmp_path / "taigacli-tokens" / ".token"
    monkeypatch.setattr(api_mod, "token_file", lambda: tok)
    monkeypatch.setattr("taigacli.config.token_file", lambda: tok)
    return tok


class StubResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class StubClient:
    def __init__(self, responses: dict[str, StubResponse]):
        self._responses = responses

    def post(self, url, json=None):
        return self._responses["post"]

    def request(self, method, url, json=None, headers=None, timeout=None):
        return self._responses["request"]


def test_get_token_missing_raises(token_store):
    with pytest.raises(CliError) as exc:
        get_token({}, StubClient({}))
    assert "taiga login" in str(exc.value)


def test_get_token_reads_cached(token_store):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("cached-token\n")
    assert get_token({}, StubClient({})) == "cached-token"


def test_get_token_empty_file_raises(token_store):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("   \n")
    with pytest.raises(CliError):
        get_token({}, StubClient({}))


def test_login_writes_and_secures_token(token_store):
    client = StubClient({"post": StubResponse(200, {"auth_token": "tok-123"})})
    token = login("http://x/api", "user", "pass", client)
    assert token == "tok-123"
    assert token_store.read_text() == "tok-123"
    assert (token_store.stat().st_mode & 0o777) == 0o600


def test_login_failure_leaves_no_token(token_store):
    client = StubClient({"post": StubResponse(400, text="bad creds")})
    with pytest.raises(CliError) as exc:
        login("http://x/api", "user", "pass", client)
    assert "400" in str(exc.value)
    assert not token_store.exists()


def test_login_no_auth_token(token_store):
    client = StubClient({"post": StubResponse(200, {})})
    with pytest.raises(CliError):
        login("http://x/api", "user", "pass", client)
    assert not token_store.exists()


def test_clear_token(token_store):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("t")
    assert clear_token() is True
    assert clear_token() is False


def test_request_401_clears_and_raises(token_store):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    client = StubClient({"request": StubResponse(401)})
    with pytest.raises(CliError) as exc:
        api_mod.request({"api_url": "http://x"}, client, "stale", "GET", "users/me")
    assert "taiga login" in str(exc.value)
    assert not token_store.exists()


def test_request_400_raises(token_store):
    client = StubClient({"request": StubResponse(400)})
    with pytest.raises(CliError):
        api_mod.request({"api_url": "http://x"}, client, "t", "GET", "users/me")


def _ctx(json=False):
    class Ctx:
        obj = {"json": json, "plain": True}

    return Ctx()


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kw: StubClient({}))
    yield


def test_cmd_login_prints_user_but_not_token(token_store, fake_http, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-123")

    def fake_request(cfg, client, token, method, path, *a, **k):
        assert token == "tok-123"
        return {"full_name": "Jane Doe", "id": 7}

    monkeypatch.setattr(api_mod, "request", fake_request)
    commands.cmd_login("http://x/api", "user", "pass", _ctx())
    out = capsys.readouterr().out
    assert "Jane Doe" in out
    assert "tok-123" not in out


def test_cmd_login_json(token_store, fake_http, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "tok-1")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"id": 7})
    commands.cmd_login("http://x/api", "user", "pass", _ctx(json=True))
    assert json.loads(capsys.readouterr().out) == {"already_logged_in": False, "user": {"id": 7}}


def test_cmd_login_json_never_contains_token(token_store, fake_http, monkeypatch, capsys):
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "sekrit")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"id": 7})
    commands.cmd_login("http://x/api", "user", "pass", _ctx(json=True))
    assert "sekrit" not in capsys.readouterr().out


def test_cmd_login_already_logged_in(token_store, fake_http, monkeypatch, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("valid")

    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"full_name": "Jane Doe", "id": 7})

    def _fail(*a, **k):
        raise AssertionError("login() must not be called while a session is valid")

    monkeypatch.setattr(api_mod, "login", _fail)
    commands.cmd_login("http://x/api", None, None, _ctx())
    out = capsys.readouterr().out
    assert "Jane Doe" in out and "already logged in" in out and "logout" in out
    assert token_store.read_text() == "valid"


def test_cmd_login_already_logged_in_json(token_store, fake_http, monkeypatch, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("valid")
    monkeypatch.setattr(api_mod, "request", lambda *a, **k: {"id": 7})
    monkeypatch.setattr(api_mod, "login", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no re-login")))
    commands.cmd_login("http://x/api", None, None, _ctx(json=True))
    assert json.loads(capsys.readouterr().out) == {"already_logged_in": True, "user": {"id": 7}}


def test_cmd_login_expired_token_relogins(token_store, fake_http, monkeypatch, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    calls = []

    def fake_request(cfg, client, token, method, path, *a, **k):
        calls.append(token)
        if token == "stale":
            raise CliError("Session expired - run `taiga login`")
        return {"full_name": "Jane Doe"}

    monkeypatch.setattr(api_mod, "request", fake_request)
    monkeypatch.setattr(api_mod, "login", lambda url, user, pwd, client: "fresh")
    commands.cmd_login("http://x/api", "user", "pass", _ctx())
    out = capsys.readouterr().out
    assert "Jane Doe" in out and "logged in" in out
    assert "already logged in" not in out
    assert calls == ["stale", "fresh"]


def test_cmd_logout(token_store, capsys):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("t")
    commands.cmd_logout(_ctx())
    out = capsys.readouterr().out
    assert "removed" in out and not token_store.exists()
    commands.cmd_logout(_ctx())
    assert "not logged in" in capsys.readouterr().out


def test_cli_help_lists_login_logout():
    result = CliRunner().invoke(cli.taiga, ["--help"])
    assert result.exit_code == 0
    for name in ("login", "logout"):
        assert name in result.output


def test_cli_logout_smoke(token_store):
    token_store.parent.mkdir(parents=True)
    token_store.write_text("t")
    result = CliRunner().invoke(cli.taiga, ["logout"])
    assert result.exit_code == 0
    assert not token_store.exists()


class RenewClient:
    """401 on the first `expire_times` requests, then 200; /auth yields 'fresh'."""

    def __init__(self, expire_times=1):
        self.requests = 0
        self.expire_times = expire_times
        self.auth_calls = 0

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.requests += 1
        return (
            StubResponse(401)
            if self.requests <= self.expire_times
            else StubResponse(200, {"id": 1}, text='{"id": 1}')
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
    token_store.parent.mkdir(parents=True)
    token_store.write_text("stale")
    monkeypatch.setenv("TAIGA_PROJECT_SLUG", "proj")

    def renewing_request(cfg, client, token, method, path, *a, **k):
        token_store.write_text("fresh")              # simulate the internal renewal
        return {"ok": True}

    monkeypatch.setattr(api_mod, "request", renewing_request)
    api = api_mod.Api()
    assert api.token == "stale"
    api.call("GET", "users/me")
    assert api.token == "fresh"  # self.token synced from the file
