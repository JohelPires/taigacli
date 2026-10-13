# taigacli

A terminal-first command-line client for [Taiga](https://taiga.io) boards.

## Requirements

- Python 3.10+
- A [Taiga](https://taiga.io) instance: a hosted account, or your own server — just point `TAIGA_API_URL` at it

## Setup

1. Copy `.env.example` to `.env` and fill it in:

   ```ini
   TAIGA_API_URL=https://api.taiga.io/api/v1
   TAIGA_PROJECT_SLUG=your-project-slug
   ```

   Values are merged per key with precedence: environment variables > nearest `.env` walking up from the current directory > `~/.config/taigacli/.env` (the global fallback for system-wide installs). No `.env` is required if all keys come from variables. `TAIGA_USERNAME` is optional — it becomes the default at the login prompt.

2. Install and log in:

   ```sh
   uv tool install --editable .    # or: pipx install -e ., or pip install -e '.[dev]' for dev
   taiga login                     # prompts for username + password (or use -u/--password)
   taiga whoami
   ```

   `--editable` keeps the install live: after `git pull` the new code runs with no reinstall. Re-run the install only if `pyproject.toml` dependencies change. Uninstall with `uv tool uninstall taigacli`.

`taiga login` exchanges your password (typed once, hidden) for an auth token cached in `~/.config/taigacli/.token` (honors `XDG_CONFIG_HOME`). The password itself is stored in the OS keyring under the service `taigacli`, keyed by API URL — that's what makes "log in once": when a token expires the CLI re-authenticates with the remembered password and carries on silently. With `--no-remember`, or when no keyring backend is available (headless server, locked keyring), no password is stored: login prints a warning, and an expired token falls back to the familiar "run `taiga login`". Keeping the password in the keyring is equivalent to a browser's saved passwords — anyone with access to your unlocked desktop session could retrieve it. Running `login` while signed in just reports the current user — run `taiga logout` first to sign in as another user; `taiga logout` deletes the cached token and the remembered password.

## Usage

```
taiga <command> [options]
```

```sh
taiga mine                                 # open user stories / tasks / issues assigned to you
taiga mine --md ./mine                     # export all of them as markdown files
taiga tasks                                # list tasks
taiga task 1343                            # show one task by ref
taiga story 1343 --md ./stories            # export a ticket as markdown into a folder (filename derived from the title)
taiga set 1344 --in-review                 # change a status
taiga set 1344 --done --dry-run            # preview the change without saving
taiga tasks --filter assigned_to=115       # filter listings (repeatable)
taiga issue 12 --json                      # raw JSON payload
```

`python -m taigacli` works the same as the `taiga` script.

## Commands

| Command | Description |
| --- | --- |
| `mine` | User stories, tasks and issues assigned to you; `--md DIR` exports them all as markdown |
| `login` | Sign in once; the token is cached and the password kept in the OS keyring so tokens renew silently (`--no-remember` opts out) |
| `logout` | Delete the cached auth token and the remembered keyring credential |
| `<resource> [ref]` | List a resource, or show one item: `stories` (`story`, `userstories`, `userstory`), `tasks` (`task`), `issues` (`issue`), `epics` (`epic`), `milestones` (`milestone`), `members` (`memberships`, `membership`), `wiki`, `timeline` |
| `set <ref> --<status>` | Change a status (e.g. `set 1344 --in-review`); bare `set <ref>` shows the options |
| `whoami` | Current user |
| `project` | Resolved project by slug |
| `help` | Command overview |

`stories`/`tasks`/`issues`/`epics` and their singular aliases resolve by ref. `milestones`, `members` and `wiki` take an item id; `timeline` lists only (it has no per-item lookup). `--filter`/`--limit` are accepted everywhere but ignored when a ref/id is given. Resource commands are exact words — no abbreviations.

## Flags

- `--json` — raw JSON payload on stdout
- `--plain` — no color, ASCII only
- `login`: `-u/--username`, `--password` — skip the prompts; the password stays hidden when prompted; `--remember/--no-remember` (default: remember) — whether the password is stored in the OS keyring for silent token renewal
- `mine`: `--md DIR` — export every listed ticket as markdown into the folder DIR (existing files are overwritten)
- `<resource>`: `--limit N` — cap listing results; `--filter k=v` — repeatable (keys: `project`, `status`, `milestone`, `assigned_to`, `page_size`)
- `set`: `--dry-run` — preview the change; `--status "In Review"` — target a status by name, slug or id instead of a flag
- `<resource> <ref>`: `--md DIR` — write the full ticket as markdown into DIR, named from the ticket title; `--force` — overwrite an existing file without asking

Re-setting the current status is a no-op. Refs are per-type: if a ref exists as more than one of user story / task / issue, `set` prints the candidates and asks for a resource prefix (e.g. `set story <ref>`).

## Markdown export

`--md DIR` saves a full ticket as a Markdown file (one `GET` and a few best-effort calls; a failing section is omitted, never fatal):

- YAML-ish front matter: type, ref, id, url, status, assignee, milestone, tags, created, modified
- `# Subject`, the description (HTML converted to Markdown)
- Acceptance criteria (client/team requirements) for user stories
- Child tasks for a user story
- Comments from the item history
- Attachment index (name + size; files are not downloaded)

Path semantics: `DIR` is folder-first — only a path with a file extension (e.g. `.md`) is taken as an explicit file name. The folder is created if missing and the file inside is named `<type>-<ref>-<subject-slug>.md` from the ticket title. If the target file exists you are asked to confirm overwrite (or pass `--force`; from a non-interactive shell a prompt is refused). `--md` without a ref is an error. Stories, tasks, issues and epics also carry a `url:` front-matter link to the ticket on the web — derived from `TAIGA_API_URL` (hosted `api.taiga.io` maps to `tree.taiga.io`; self-hosted drops the `/api/v1` suffix) plus the project slug and ref.

```sh
taiga story 1343 --md ./stories            # ./stories/story-1343-<title-slug>.md
taiga story 1343 --md ./stories/1343.md    # explicit file name still works
taiga issue 12 --md ~/notes -f             # -f == --force
```

`taiga mine --md DIR` exports every open ticket assigned to you (user stories, tasks and issues) into the folder in one go, using the same layout and naming; each ticket's full detail is fetched so the files match a single-ticket export. Because it is a batch, it overwrites any same-named file without prompting. The exported paths go to stderr, followed by a `N tickets saved to DIR` summary.

```sh
taiga mine --md ./mine                     # ./mine/story-1343-<slug>.md, task-…, issue-…
```

## Output styling

Colors are rendered as truecolor/256-color ANSI when stdout is a tty, and plain when piped. Color is disabled by `NO_COLOR` or `TERM=dumb`; force it when piped with `TAIGA_COLOR=1`. For scripts, prefer `--plain` (ASCII only) or `--json` (machine-readable).

## Development

```sh
pip install -e '.[dev]'
pytest
```

`taiga --help` is the authoritative command reference — keep `README.md` in sync with it when adding commands or flags.
