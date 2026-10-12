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

   Values are merged per key with precedence: environment variables > nearest `.env` walking up from the current directory > `~/.config/taigacli/.env` (the global fallback for system-wide installs). No `.env` is required if all keys come from variables.

2. Install and verify:

   ```sh
   uv tool install --editable .    # or: pipx install -e ., or pip install -e '.[dev]' for dev
   taiga whoami
   ```

   `--editable` keeps the install live: after `git pull` the new code runs with no reinstall. Re-run the install only if `pyproject.toml` dependencies change. Uninstall with `uv tool uninstall taigacli`.

Your auth token is cached in `~/.config/taigacli/.token` (honors `XDG_CONFIG_HOME`) after the first call and refreshed automatically on 401. `.env` contains credentials — keep it out of the repo; it is gitignored.

## Usage

```
taiga <command> [options]
```

```sh
taiga mine                                 # open user stories / tasks / issues assigned to you
taiga tasks                                # list tasks
taiga task 1343                            # show one task by ref
taiga story 1343 --md ./1343.md            # export a ticket as markdown to a file
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
- `<resource> <ref>`: `--md PATH` — write the full ticket as markdown to PATH; `--force` — overwrite an existing file without asking

Re-setting the current status is a no-op. Refs are per-type: if a ref exists as more than one of user story / task / issue, `set` prints the candidates and asks for a resource prefix (e.g. `set story <ref>`).

## Markdown export

`--md PATH` saves a full ticket as a Markdown file (one `GET` and a few best-effort calls; a failing section is omitted, never fatal):

- YAML-ish front matter: type, ref, status, assignee, milestone, tags, created, modified, id
- `# Subject`, the description (HTML converted to Markdown)
- Acceptance criteria (client/team requirements) for user stories
- Child tasks for a user story
- Comments from the item history
- Attachment index (name + size; files are not downloaded)

Path semantics: missing parent directories are created; if `PATH` is an existing directory a file named `<type>-<ref>-<subject-slug>.md` is written inside it; if the target file exists you are asked to confirm overwrite (or pass `--force`; from a non-interactive shell a prompt is refused). `--md` without a ref is an error.

```sh
taiga story 1343 --md ./stories/1343.md
taiga issue 12 --md ~/notes -f            # -f == --force
```

## Output styling

Colors are rendered as truecolor/256-color ANSI when stdout is a tty, and plain when piped. Color is disabled by `NO_COLOR` or `TERM=dumb`; force it when piped with `TAIGA_COLOR=1`. For scripts, prefer `--plain` (ASCII only) or `--json` (machine-readable).

## Development

```sh
pip install -e '.[dev]'
pytest
```

`taiga --help` is the authoritative command reference — keep `README.md` in sync with it when adding commands or flags.
