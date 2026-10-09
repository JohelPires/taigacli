# taigacli

A terminal-first command-line client for [Taiga](https://taiga.io) boards.

Single file (`taiga.py`), Python standard library only — no `pip install`, no dependencies, one `.env` file for setup. It covers all read operations and one write: `set` changes statuses.

## Requirements

- Python 3.10+
- A [Taiga](https://taiga.io) instance: a hosted account, or your own server — just point `TAIGA_API_URL` at it

## Setup

1. Copy `.env.example` to `.env` and fill it in:

   ```ini
   TAIGA_API_URL=https://api.taiga.io/api/v1
   TAIGA_USERNAME=you@example.com
   TAIGA_PASSWORD=your-password
   TAIGA_PROJECT_SLUG=your-project-slug
   ```

   Any of these can also be set as regular environment variables (they override `.env`).

2. Verify it works:

   ```sh
   python taiga.py whoami
   ```

Your auth token is cached in `.token` after the first call and refreshed automatically on 401. Both `.env` and `.token` are gitignored — keep your credentials out of the repo.

## Usage

```
taiga.py <command> [options]
```

```sh
taiga.py mine                                 # open user stories / tasks / issues assigned to you
taiga.py set 1344 --in-review                 # change a status
taiga.py set 1344 --done --dry-run            # preview the change without saving
taiga.py list tasks --filter assigned_to=115  # filter lists (repeatable)
taiga.py get userstories 1344                 # one item in full detail
taiga.py get issues 12 --json                 # raw JSON payload
```

## Commands

| Command | Description |
| --- | --- |
| `mine` | User stories, tasks and issues assigned to you |
| `set <ref> --<status>` | Change a status (e.g. `set 1344 --in-review`); bare `set <ref>` shows the options |
| `list <resource>` | Filterable listing: `epics stories userstories tasks issues milestones members wiki timeline` |
| `get <resource> <id>` | Single object in full detail (e.g. `get userstories 1344`) |
| `whoami` | Current user |
| `project` | Resolved project by slug |
| `help` | Command overview |

## Flags

- `--json` — raw JSON payload on stdout
- `--plain` — no color, ASCII only
- `list`: `--limit N` — cap results; `--filter k=v` — repeatable (keys: `project`, `status`, `milestone`, `assigned_to`, `page_size`)
- `set`: `--dry-run` — preview the change; `--status "In Review"` — target a status by name, slug or id instead of a flag

Re-setting the current status is a no-op. Refs are per-type: if a ref exists as more than one of user story / task / issue, `set` prints the candidates and asks for a resource prefix (e.g. `set story <ref>`).

## Output styling

Colors are rendered as truecolor/256-color ANSI when stdout is a tty, and plain when piped. Color is disabled by `NO_COLOR` or `TERM=dumb`; force it when piped with `TAIGA_COLOR=1`. For scripts, prefer `--plain` (ASCII only) or `--json` (machine-readable).
