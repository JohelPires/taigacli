# Project list & switch — design

Date: 2026-10-27

## Goal

List the user's Taiga projects and switch between them globally from the CLI,
without editing `.env`.

## Commands

- `taiga projects` — lists projects the signed-in user is a member of
  (`GET users/me` for the id, then `GET projects?member=<id>&order_by=memberships__user_order`).
  Flags: `--limit N`, `--json`, `--plain`. Styled rows with a current-project
  marker (dot + bold name), name, slug, id, and a count header; empty list
  prints a muted "no projects" line.
- `taiga project` — no argument: shows the current project (name, id, slug)
  plus the source ("switched", "env", ".env") and, when nothing is selected,
  a hint to run `taiga projects`.
- `taiga project <slug|id>` — resolves the project (`projects/by_slug` for a
  slug; all-digits targets go to `projects/<id>`) and persists it globally,
  printing `now using <name> · slug · id`. Unknown targets raise
  `Project not found: X — run \`taiga projects\``. Works before any project is
  configured (bootstrap mode), so first run is
  `taiga login` → `taiga projects` → `taiga project <slug>`.
- Both accept `--json`/`--plain` like every other command.

## Storage & resolution

- Current project lives in `~/.config/taigacli/current_project.json`
  (honors `XDG_CONFIG_HOME`): `{"api_url", "id", "slug", "name"}`.
- Slug resolution: stored current project → shell env `TAIGA_PROJECT_SLUG` →
  `.env` files. The stored project counts only when its `api_url` matches the
  resolved API URL; a missing/corrupt file is ignored silently. The stored
  choice intentionally outranks the env var; the env var matters only until a
  switch has ever been made.
- Writes are atomic (temp file + rename) and chmod 0600. Logout does not clear
  the selection. The file is not a secret but is created parent-first.

## Bootstrap-safe config

- `config(require_slug=True|False)`: validation of the slug moves behind a
  flag; `Api(require_project=True)` (default) keeps today's strictness, while
  `projects`/`project`/`whoami` construct `Api(require_project=False)`.
- Missing slug raises "Missing config keys: slug — ..." with a pointer to
  `taiga projects` / `.env`; `Api.project()` guards the same way for the
  bootstrap path. `whoami` prints the project as "none" when unset.

## Out of scope

Per-command `--project` override, join/leave, per-directory pinning, creating
projects.

## Tests

- config: stored project beats env beats `.env`; api_url mismatch falls back;
  corrupt file ignored; save/load roundtrip; 0600 permissions.
- api: `Api.project()` raises the friendly error when no slug.
- commands: list rendering with current marker; `--json`; switch by slug and
  by id stores the record; not-found error; no-arg show with source; no
  project selected hint.
- cli: `--help` lists `projects`; invocations render through the group.
