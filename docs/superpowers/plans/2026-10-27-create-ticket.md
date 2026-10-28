# Create Ticket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `taiga new <resource> "<subject>"` to create user stories, tasks, and issues in the current project.

**Architecture:** Add a generic `Api.post()`, implement `cmd_new()` beside the other command bodies in `commands.py`, and wire a thin Click command in `cli.py`. Reuse existing `SET_ALIASES`, `RESOURCES`, `LABELS`, `_match_status`, `load_statuses`, `by_ref`, and `render_record`.

**Tech Stack:** Python 3.10+, Click, httpx, pytest, Click `CliRunner`.

## Global Constraints

- Only `userstories`, `tasks`, and `issues` are creatable.
- `description` is Markdown passed through unchanged; Taiga renders `description_html`.
- Omitting `--status` omits the `status` key so Taiga applies its default.
- `--story REF` applies only to tasks and is optional.
- No new dependencies. No hardcoded ANSI/Unicode; use existing render/theme helpers.
- Tests run offline: `.venv/bin/python -m pytest`.
- Keep `README.md` and `AGENTS.md` in sync with `taiga --help`.
- Commit style follows `git log`: `feat:`/`docs:`.

Spec: `docs/superpowers/specs/2026-10-27-create-ticket-design.md`.

---

### Task 1: Add `Api.post`

**Files:**
- Modify: `src/taigacli/api.py` (after `patch`)
- Test: `tests/test_cli_and_helpers.py`

**Interfaces:**
- Produces: `Api.post(self, path: str, body: dict)` → parsed JSON response.

- [ ] **Step 1: Write the failing test**

```python
def test_api_post_uses_call():
    from taigacli.api import Api

    api = object.__new__(Api)
    captured = {}

    def fake_call(method, path, params=None, body=None, soft=False):
        captured.update(method=method, path=path, body=body)
        return {"id": 99}

    api.call = fake_call
    assert api.post("userstories", {"subject": "S"}) == {"id": 99}
    assert captured == {
        "method": "POST",
        "path": "userstories",
        "body": {"subject": "S"},
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_and_helpers.py::test_api_post_uses_call -v`
Expected: FAIL with `AttributeError: 'Api' object has no attribute 'post'`.

- [ ] **Step 3: Implement `Api.post`**

```python
    def post(self, path: str, body: dict):
        return self.call("POST", path, body=body)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_and_helpers.py::test_api_post_uses_call -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/taigacli/api.py tests/test_cli_and_helpers.py
git commit -m "feat: add POST helper to Api"
```

---

### Task 2: Implement `cmd_new` with validation and output

**Files:**
- Modify: `src/taigacli/commands.py`
- Create: `tests/test_new.py`

**Interfaces:**
- Consumes: `Api.project_id()`, `Api.load_statuses()`, `Api.by_ref()`, `Api.post()`.
- Produces: `cmd_new(api, ctx, resource, subject, description=None, status_opt=None, story_ref=None)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_new.py` with `NewApi`
  fake (records `post` calls; `project_id()` → 1; statuses New/In Progress;
  `by_ref` returns story id 17 for ref 3) covering: minimal story payload;
  all 8 aliases; description + status mapping; task with/without parent story;
  unsupported resource; empty subject; unknown status; missing story ref;
  `--story` on non-task; `--json`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_new.py -v`
Expected: FAIL with `ImportError: cannot import name 'cmd_new'`.

- [ ] **Step 3: Implement `cmd_new` in `src/taigacli/commands.py`**

```python
def cmd_new(
    api,
    ctx,
    resource: str,
    subject: str,
    description: str | None = None,
    status_opt: str | None = None,
    story_ref: int | None = None,
):
    canonical = SET_ALIASES.get(str(resource).strip().lower())
    if canonical is None:
        raise CliError(
            "Can only create stories, tasks, or issues - expected story, task, or issue"
        )
    subject = str(subject).strip()
    if not subject:
        raise CliError("Subject cannot be empty")
    if story_ref is not None and canonical != "tasks":
        raise CliError("--story only applies to tasks")

    body: dict = {"project": api.project_id(), "subject": subject}
    if description is not None:
        body["description"] = description
    if status_opt:
        options = api.load_statuses(body["project"], canonical)
        matched = _match_status(options, None, status_opt)
        if matched is None:
            names = ", ".join(o.get("name", "?") for o in options)
            raise CliError(f"No status matches '{status_opt}' - choose from: {names}")
        body["status"] = matched["id"]
    if canonical == "tasks" and story_ref is not None:
        story = api.by_ref("userstories", story_ref, soft=True)
        if not isinstance(story, dict) or not story.get("id"):
            raise CliError(f"Story not found: #{story_ref}")
        body["user_story"] = story["id"]

    item = api.post(RESOURCES[canonical], body)
    if is_json(ctx):
        print(json.dumps(item, indent=2))
        return
    if not isinstance(item, dict):
        raise CliError("Could not create ticket: empty response")
    print(render_record(item, LABELS.get(canonical, canonical)))
```

All names (`SET_ALIASES`, `RESOURCES`, `LABELS`, `_match_status`,
`render_record`, `CliError`, `json`) are already imported in `commands.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_new.py -v` — all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest` — all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/taigacli/commands.py tests/test_new.py
git commit -m "feat: create stories, tasks, and issues"
```

---

### Task 3: Wire `taiga new` into the CLI

**Files:**
- Modify: `src/taigacli/cli.py`
- Modify: `tests/test_new.py`, `tests/test_cli_and_helpers.py`

**Interfaces:**
- Consumes: `commands.cmd_new(api, ctx, resource, subject, description, status_opt, story_ref)`.
- Produces: Click command `new` with `RESOURCE`, `SUBJECT`, `--description/-d`,
  `--status`, `--story REF`, `--json`, `--plain`.

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/test_new.py`:

```python
def test_cli_new_invocation(monkeypatch):
    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(
        cli.taiga, ["new", "story", "Fix login", "--description", "Body", "--json"]
    )
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert json.loads(result.output)["ref"] == 1343
    assert api.calls[0][1]["description"] == "Body"


def test_cli_new_json_before_command(monkeypatch):
    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(cli.taiga, ["--json", "new", "issue", "Crash"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert json.loads(result.output)["ref"] == 1343


def test_cli_new_task_story_option(monkeypatch):
    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(cli.taiga, ["new", "task", "Write tests", "--story", "3"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert api.calls[0][1]["user_story"] == 17
```

Update `test_cli_help_lists_commands` to include `"new"` in the tuple.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_new.py tests/test_cli_and_helpers.py::test_cli_help_lists_commands -v`
Expected: FAIL because `new` is not registered.

- [ ] **Step 3: Add the Click command in `src/taigacli/cli.py` (before `set_cmd`)**

```python
@taiga.command(name="new", help="create a user story, task, or issue")
@click.argument("resource", metavar="RESOURCE")
@click.argument("subject", metavar="SUBJECT")
@click.option("--description", "-d", default=None, help="Markdown description")
@click.option("--status", default=None, help="initial status by name, slug, or id")
@click.option("--story", "story_ref", type=int, default=None, metavar="REF", help="parent user story ref (tasks only)")
@click.option("--json", "cmd_json", is_flag=True, help="raw JSON output")
@click.option("--plain", "cmd_plain", is_flag=True, help="no color, ASCII only")
@click.pass_context
def new_cmd(ctx, resource, subject, description, status, story_ref, cmd_json, cmd_plain):
    _ui(ctx)
    commands.cmd_new(_api(), ctx, resource, subject, description, status, story_ref)
```

- [ ] **Step 4: Run the CLI tests**

Run: `.venv/bin/python -m pytest tests/test_new.py tests/test_cli_and_helpers.py::test_cli_help_lists_commands -v` — all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest` — all PASS.

- [ ] **Step 6: Verify help manually**

Run: `.venv/bin/taiga new --help`

- [ ] **Step 7: Commit**

```bash
git add src/taigacli/cli.py tests/test_new.py tests/test_cli_and_helpers.py
git commit -m "feat: wire taiga new command"
```

---

### Task 4: Update documentation

**Files:**
- Modify: `README.md`, `AGENTS.md`

- [ ] **Step 1: README usage examples** — add `taiga new story ...`, `taiga new task ... --story`, `taiga new issue ...`.
- [ ] **Step 2: README command table + flags** — `new` row; `--description/-d`, `--status`, `--story` flag docs.
- [ ] **Step 3: README "Creating tickets" section** — aliases, required subject, Markdown description pass-through, default status, tasks with/without parent, output.
- [ ] **Step 4: AGENTS.md** — add `cmd_new` to `commands.py` bullet, `new` to `cli.py` bullet, `post` to `api.py` bullet, change "`set` is the only default write command" to include `new`.
- [ ] **Step 5: Verify** `.venv/bin/taiga --help` and `.venv/bin/taiga new --help` match README.
- [ ] **Step 6: Full suite** `.venv/bin/python -m pytest` — all PASS.
- [ ] **Step 7: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document taiga new"
```
