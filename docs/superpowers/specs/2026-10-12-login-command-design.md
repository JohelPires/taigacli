# Design: token login (`taiga login` / `taiga logout`)

Date: 2026-10-12
Status: approved (user decisions recorded below)

## Motivation

`.env` currently holds `TAIGA_PASSWORD` in plaintext. The password should be entered once at login instead, exchanging it for a token that is cached and reused. This is **token login / stored-token auth** — not passwordless: the password is still typed at `taiga login`, it is just never stored.

## User decisions

- Auth helpers live in **`api.py`**; config split lives in `config.py` (approach A, no new `auth.py` module).
- `taiga login` accepts an **interactive prompt with flag overrides**: `--username/-u`, `--password`; missing values prompt (password hidden, username defaults to `TAIGA_USERNAME` from env/config if set).
- Missing or expired token: commands error with "run `taiga login`"; on 401 the cached token is dropped and the error is raised (no password re-auth, no silent token re-read).
- `config()` requires **only** `TAIGA_PROJECT_SLUG`. `TAIGA_USERNAME`/`TAIGA_PASSWORD` are optional and dropped from `.env.example` and README.
- Extras: add `taiga logout` (deletes the cached token, prints the path); after a successful login, verify and print the signed-in user via `/users/me`. No overwrite confirmation; no 401 re-read.

## Changes

### `src/taigacli/config.py`
- Add `DEFAULT_API_URL` and `api_url() -> str`: env `TAIGA_API_URL` > `.env` > default, `.rstrip("/")`. No validation, so `login` works before a slug is configured.
- `config()` builds on `api_url()` and requires only `slug`; `username` stays as an optional returned value; `password` is removed entirely. Missing-keys message updated.

### `src/taigacli/api.py`
- Delete `_token_cache`.
- `get_token(cfg, client)`: read `token_file()`; absent/empty → `CliError("Not logged in - run \`taiga login\`")`. No `/auth` POST, no "Authenticating…" print, no `refresh` param.
- `login(api_url, username, password, client) -> str`: POST `/auth`, require `auth_token`, `mkdir -p` the parent, write `token_file()`, `secure()`, return the token.
- `clear_token() -> bool`: unlink the token file if present.
- `request(...)`: drop the `retry` param and the 401 re-auth recursion; on 401, `clear_token()` then `CliError("Session expired - run \`taiga login\`")`. The `x-next` recursion no longer passes `retry=False`.
- `Api.__init__` keeps its shape: `self.cfg = config()`; `self.token = get_token(self.cfg, self.client)`.
- `__all__` gains `login`, `clear_token`.

### `src/taigacli/commands.py`
- `cmd_login(api_url, username, password, ctx)`: build an `httpx.Client`, call `api.login(...)`, then `api.request({"api_url": api_url}, client, token, "GET", "users/me")`. Print `logged in as <name>` to stderr; `--json` prints the user payload (never the token).
- `cmd_logout(ctx)`: `clear_token()`; print the removed path or "not logged in"; `--json` prints a status dict.

### `src/taigacli/cli.py`
- `login` command: `--username/-u`, `--password`; prompt for a missing username (default from `TAIGA_USERNAME` via env/`load_env()`) and a hidden password. `--json/--plain` per convention; `_ui(ctx)`/`pass_context` pattern.
- `logout` command with `--json/--plain`.
- Neither constructs `Api()` (which now requires a token). Import `api_url` from `config`.

### Docs & env
- `.env.example`: only `TAIGA_API_URL` + `TAIGA_PROJECT_SLUG`.
- README: Setup = copy example, install, `taiga login`, `taiga whoami`; document token cache, `logout`, 401 → re-login; add `login`/`logout` to the Commands table.
- Local `.env`: remove the `TAIGA_PASSWORD` line; keep the optional `TAIGA_USERNAME` as the login-prompt default.
- The previously stored password should be rotated in Taiga (it existed in a plaintext file).

## Tests (offline; token path and client monkeypatched)

- `tests/test_config.py`: drop `password` expectations; slug-only requirement; `api_url()` default/override.
- New `tests/test_auth.py`: `get_token` errors with no token file; `login` writes and secures the token (stub client); `clear_token` removes/absent; `request` on 401 clears and raises.
- `tests/test_cli_and_helpers.py`: help lists `login`/`logout`.

## Verification

- `.venv/bin/python -m pytest`
- `.venv/bin/taiga --help` lists `login`/`logout`
- Manual: `taiga logout && taiga whoami` → "Not logged in"; `taiga login` → `whoami` succeeds against the real API.
