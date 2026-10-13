# Design: "login once, remember me" via OS keyring

Date: 2026-10-13

## Problem

`taiga login` stores a single auth token in `~/.config/taigacli/.token`. Taiga's
normal auth tokens expire, and the only way to mint a new one is a fresh `POST /auth`
with username + password. On expiry the CLI clears the token and tells the user to run
`taiga login` again, so the user is bounced out periodically.

## Goal

After one `taiga login`, the CLI silently re-authenticates whenever the token expires,
using a password stored in the OS keyring. The user never sees "session expired" again.
User context: self-hosted Taiga, non-admin, so server-side token lifetime is unavailable;
the application-token flow requires an admin-registered application. Storing the password
is the only viable mechanism.

## Decisions

- Credential stored in the **OS keyring** (via `keyring`; SecretService on Linux, macOS
  Keychain, Windows Credential Locker). No plaintext fallback.
- If no working keyring backend exists: `login` prints a muted warning and behaves
  token-only (no password ever hits disk). Auto-renew is simply unavailable.
- **Remember is default-on**: `taiga login` always remembers when a keyring is available;
  `--no-remember` opts out.
- Renewal is **fully silent** (browser-like), so scripting output is untouched.

## Mechanism

On 401 from any API call, the CLI:

1. Loads the remembered credential for `cfg["api_url"]` from the keyring.
2. POSTs `/auth` (normal login) with username + password.
3. On success: overwrites the token file (same path/format as today) and **retries the
   original request exactly once**.
4. On failure or absent credential: current behavior — `clear_token()` and
   "Session expired - run `taiga login`". A retry guard prevents loops.

## Components

### `src/taigacli/credentials.py` (new)

Thin, soft-failing wrapper around `keyring`, imported lazily so a missing module never
breaks the CLI:

- `available() -> bool` — true only for a real backend (rejects keyring's fail backend).
- `save(api_url, username, password) -> bool`
- `load(api_url) -> tuple[str, str] | None`
- `forget(api_url) -> bool`
- Keyring service name: `"taigacli"`. Account: the API URL. Stored secret: JSON
  `{"username": ..., "password": ...}` so renewal needs only the API URL (no sidecar
  metadata file). All keyring errors degrade to "not remembered".

### `src/taigacli/api.py`

- Factor `_auth(api_url, username, password, client) -> str` out of `login()`;
  `login()` reuses it and additionally saves the credential (remember on).
- `request()` gains the 401 renewal path above (with a `_retried` flag).
- `Api.call()` re-reads the token file after each call so `self.token` stays
  current when a renewal wrote a new token during the call.
- Token file format unchanged (bare token) — full backward compatibility.

### `src/taigacli/commands.py` / `cli.py`

- `taiga login` gains `--remember/--no-remember` (default remember). After success it
  saves the credential when available and prints:
  - remembered → `logged in - token saved (remembered via OS keyring)`
  - keyring unavailable → muted warning: `logged in - token saved (keyring unavailable; you will be asked to log in again when the token expires)`
- `taiga logout` deletes the token **and** the keyring entry, reporting both.
- `--json` output gains a `remembered` field where relevant.

### `pyproject.toml`

Add `keyring>=24` to `dependencies` (installs `SecretStorage` on Linux).

## Edge cases

- Password changed / 2FA / locked keyring at renewal time → renewal fails, falls back to
  the current "run `taiga login`" message.
- Multiple Taiga instances → separate keyring entries keyed by API URL (also avoids the
  existing single-global-token collision at the credential layer).
- Headless / no DBus → `available()` false → warn + token-only.
- If `keyring` is not installed (e.g. dependency pruned), everything degrades gracefully.

## Security trade-off

The password is recoverable by anyone with access to the user's unlocked keyring
session — equivalent to a browser's saved-password store. Accepted by the user.

## Testing & docs

- Offline pytest (API + keyring mocked): renew-then-retry-once and token file rewrite;
  no credential → current message; keyring unavailable → warn + no save; `logout` clears
  both; missing `keyring` module → graceful.
- Update `README.md` (login/logout behavior, flags, security note) and `AGENTS.md`
  (new module, keyring dependency) — both must stay in sync with `taiga --help`.
