# taigacli

A terminal-first command-line client for [Taiga](https://taiga.io) boards.

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

   The file is looked up in the current directory and every parent; any of the keys can also be set as regular environment variables (they override the file).

2. Install and verify:

   ```sh
   pip install -e '.[dev]'     # or: pipx install -e .
   taiga whoami
   ```

Your auth token is cached in `~/.config/taigacli/.token` (honors `XDG_CONFIG_HOME`) after the first call and refreshed automatically on 401. `.env` contains credentials — keep it out of the repo; it is gitignored.

## Usage

```
taiga <command> [options]
```

```sh
taiga mine                                 # open user stories / tasks / issues assigned to you
taiga tasks                                # list tasks
taiga task 1343                            # show one task by ref
taiga set 1344 --in-review                 # change a status
taiga set 1344 --done --dry-run            # preview the change without saving
taiga tasks --filter assigned_to=115       # filter listings (repeatable)
taiga issue 12 --json                      # raw JSON payload
```

`python -m taigacli` works the same as the `taiga` script.

## Commands

| Command | Description |
| --- | --- |
| `mine` | User stories, tasks and issues assigned to you |
| `<resource> [ref]` | List a resource, or show one item: `stories` (`story`, `userstories`, `userstory`), `tasks` (`task`), `issues` (`issue`), `epics` (`epic`), `milestones` (`milestone`), `members` (`memberships`, `membership`), `wiki`, `timeline` |
| `set <ref> --<status>` | Change a status (e.g. `set 1344 --in-review`); bare `set <ref>` shows the options |
| `whoami` | Current user |
| `project` | Resolved project by slug |
| `help` | Command overview |

`stories`/`tasks`/`issues`/`epics` and their singular aliases resolve by ref. `milestones`, `members` and `wiki` take an item id; `timeline` lists only (it has no per-item lookup). `--filter`/`--limit` are accepted everywhere but ignored when a ref/id is given. Resource commands are exact words — no abbreviations.

## Flags

- `--json` — raw JSON payload on stdout
- `--plain` — no color, ASCII only
- `<resource>`: `--limit N` — cap listing results; `--filter k=v` — repeatable (keys: `project`, `status`, `milestone`, `assigned_to`, `page_size`)
- `set`: `--dry-run` — preview the change; `--status "In Review"` — target a status by name, slug or id instead of a flag

Re-setting the current status is a no-op. Refs are per-type: if a ref exists as more than one of user story / task / issue, `set` prints the candidates and asks for a resource prefix (e.g. `set story <ref>`).

## Output styling

Colors are rendered as truecolor/256-color ANSI when stdout is a tty, and plain when piped. Color is disabled by `NO_COLOR` or `TERM=dumb`; force it when piped with `TAIGA_COLOR=1`. For scripts, prefer `--plain` (ASCII only) or `--json` (machine-readable).

## Development

```sh
pip install -e '.[dev]'
pytest
```

`taiga --help` is the authoritative command reference — keep `README.md` in sync with it when adding commands or flags.
