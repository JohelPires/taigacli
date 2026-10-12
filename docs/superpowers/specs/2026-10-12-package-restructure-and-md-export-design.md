# Design: taigacli package restructure + markdown export

Date: 2026-10-12
Status: approved (user decisions recorded below)

## Motivation

`taiga.py` is a ~1127-line single-file CLI. The user removed the "single file, stdlib only" premise; the project should now be an installable, growing package. On top of that we add `--md PATH` to export a full ticket as Markdown. Sequencing: restructure first (behavior-preserving), then the feature.

## User decisions

- CLI framework: **Click** (handles `set 1344 --in-review` dynamic flags via `ignore_unknown_options`).
- HTTP: **httpx** (sync).
- Terminal output: **preserve the current hand-rolled design** (HUES/GLYPHS/status rules); extract to theme/render modules, no rich.
- Tooling: **minimal** — pyproject (setuptools) + pytest. No ruff/mypy/CI yet.
- Dependencies: `click`, `httpx`, `markdownify` (transitively `beautifulsoup4`). No python-dotenv.
- Config discovery: env vars override; `.env` searched in cwd walking **up** to filesystem root; `.token` cached in **`~/.config/taigacli/`** (respects `XDG_CONFIG_HOME`).
- Help: rely on Click's `--help`; `taiga help` kept as an alias printing the `taiga --help` page. README mirrors Click help output.
- Export: `--md PATH` writes file (creates parents; existing directory → auto-named file inside; existing file → prompt, `--force` skips). "Full ticket" = front matter + subject + description + acceptance criteria (stories) + child tasks + comments + attachment list.
- `--json`/`--plain` accepted at group level and on every subcommand (preserves "anywhere in argv" UX).

## Phase 1 layout

```
pyproject.toml              # setuptools, deps, console script, requires-python >=3.10
src/taigacli/
  __init__.py
  __main__.py               # python -m taigacli
  errors.py                 # CliError exception; error() reporter
  config.py                 # .env walk-up parse, config(), token cache, secure()
  api.py                    # httpx client: login, http, by_ref, project(_id), load_statuses
  resources.py              # RESOURCES/LABELS/STATUS_KINDS/SET_ALIASES/RESOURCE_SPECS/RESOURCE_CANONICAL/REF_RESOURCES, normalize_name, _norm_item
  theme.py                  # HUES, GLYPHS, STATUS_RULES/ORDER, _STATE, ui_init, paint, g, status_hue, palette helpers
  render.py                 # layout: pads/squeeze, header_line, eyebrow, kv_rows, description_block, render_rows/timeline/members/record/status_menu/change, ribbon, strip_html, show_summary
  commands.py               # cmd bodies ported verbatim (mine, get, list, whoami, project, set, help)
  cli.py                    # Click group, alias resolution, shared options, dispatch; main() entry
tests/
```

### Parity contract

`taigacli --plain` output must byte-match the pre-restructure script for: help, whoami, project, mine, listings, `story 1343`, `set 1343 --dry-run`, ambiguous ref, and the 404 error path (message text on stderr preserved). Verified by diffing captured baselines (captured before any change).

### Click specifics

- Custom `Group.get_command()` resolves aliases from `RESOURCE_CANONICAL`.
- Resource command options: `REF` arg, `--limit`, repeatable `--filter`, `--json/--plain`; group also defines `--json/--plain`.
- `set`: `context_settings={"ignore_unknown_options": True, "allow_extra_args": True}`, single `args` collector; status flags recovered from `ctx.args` exactly like the old argv scan.

## Phase 2 — markdown export

- `api.get_history/get_attachments/get_child_tasks`, best-effort (failure ⇒ section omitted, not abort).
- `export.render_markdown` builds: YAML-ish front matter (`ref/type/status/assignee/milestone/tags/created/modified/id`), `# Subject`, Description (markdownify; `strip_html` fallback), Acceptance criteria (stories), Tasks (child, stories), Comments (`/history/{kind}/{id}` entries with a `comment`), Attachments (name/size). No file downloads.
- `export.write_markdown`: parents created; arg-directory → `<type>-<ref>-<slug>.md`; exists → prompt `[y/N]`, non-tty abort suggests `--force`; `--force` skips.
- CLI: `--md PATH`, `--force` on stories/tasks/issues/epics/milestones/wiki; error on members and on md without a ref/id. Writes file, prints `saved <path>` to stderr, suppresses record output; `--json`/`--plain` ignored.

## Tests

- pytest unit: theme/helpers, config parsing (tmp cwd), `strip_html`, `normalize_name`/`match_status`, markdown front matter/mardownify/writer (tmp_path), Click runner smoke tests with the API monkeypatched.
- Live manual verification against the real API at the end of each phase.

## Risks

- `?user_story=`/`?issue=` child-task filters and `/history/{kind}/{id}` shape verified live during Phase 2; adapters isolate those calls.
- Baselines captured before any code change; any behavioral drift shows up as a diff failure.
