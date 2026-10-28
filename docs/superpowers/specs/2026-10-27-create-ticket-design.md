# Create tickets — design

Date: 2026-10-27

## Goal

Create user stories, tasks, and issues in the current project from the CLI.

## Command

```sh
taiga new <resource> "<subject>" \
  [--description TEXT] \
  [--status NAME|SLUG|ID] \
  [--story REF] \
  [--json | --plain]
```

- `<resource>` accepts the listing aliases: `story`/`stories`/`userstory`/`userstories`,
  `task`/`tasks`, `issue`/`issues` (reuses `SET_ALIASES`). Anything else errors.
- `subject` is one required positional argument; stripped, empty rejected.
- `--description` is Markdown passed through unchanged as the API `description`
  field — Taiga renders `description_html` server-side (the GUI editor does the same).
- `--status` resolves through `api.load_statuses()` + `_match_status()` (name, slug or id).
  When omitted the `status` key is left out of the payload so Taiga applies the
  project default status.
- `--story REF` applies to tasks only: resolves the story ref in the current
  project via `api.by_ref("userstories", ref)` and sets `user_story` to its id.
  Omitted → standalone task (Taiga's task model allows a null user story).
  `--story` on a story/issue is a usage error.
- `--json` prints the raw API response; otherwise the created ticket renders via
  `render_record(item, LABELS[resource])`.

## Data flow

1. `Api.post(path, body)` — thin wrapper over `Api.call("POST", ...)`.
2. `commands.cmd_new(api, ctx, resource, subject, description, status_opt, story_ref)`:
   alias → canonical resource; validate; build payload
   (`project`, `subject`, optional `description`/`status`/`user_story`);
   `POST` to `RESOURCES[resource]`; render record or JSON.
3. `cli.py` wires the `new` command with the standard group- and
   subcommand-level `--json`/`--plain` options.

Payload requirements per API docs (`POST /userstories`, `/tasks`, `/issues`):
`project` and `subject` required; `description`, `status`, `user_story` (tasks)
optional. Epics, milestones, members, wiki, and timelines are not creatable.

## Errors

- Unknown resource: "Can only create stories, tasks, or issues".
- Empty subject: "Subject cannot be empty".
- Invalid `--status`: "No status matches 'X' - choose from: <names>".
- Unknown `--story` ref: "Story not found: #REF".
- `--story` on a non-task: "--story only applies to tasks".
- API failures keep the existing `API error N ...` reporting.

## Out of scope

`--tag`, `--assignee`, `--milestone`, epics, batch creation, `$EDITOR`,
`--description -` (stdin), `--dry-run`.

## Tests

Command tests with a fake API: minimal story payload; alias forms; description +
status mapping; task with/without parent story; unsupported resource; empty
subject; unknown status (lists options); missing story ref; `--story` on
non-task; `--json`. CLI tests: invocation, `--json` before/after the command,
`--story` option, `new` in `--help`. `Api.post` unit test.
