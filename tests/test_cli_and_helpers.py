from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

import taigacli.cli as cli
from taigacli.commands import _match_status, cmd_set, cmd_project, cmd_projects, cmd_whoami
from taigacli.config import parse_env_file
from taigacli.errors import CliError
from taigacli.render import header_line, strip_html, squeeze
from taigacli.resources import _norm_item, normalize_name
from taigacli.theme import paint, ui_init


@pytest.fixture(autouse=True)
def _plain():
    ui_init(plain=True)


def test_normalize_name():
    assert normalize_name("In Progress") == "in-progress"
    assert normalize_name("  Ready  ") == "ready"
    assert normalize_name("") == ""


def test_strip_html_keeps_line_breaks():
    src = "<p>First<br>second</p><p>&amp; more</p>"
    assert strip_html(src) == "First\nsecond\n\n& more"


def test_strip_html_blank():
    assert strip_html("<p>   </p>") == ""


def test_squeeze():
    assert squeeze("abcdef", 10) == "abcdef"
    assert squeeze("abcdef", 4) == "ab.."
    assert squeeze("abc", 0) == ""


def test_paint_plain_returns_text_with_glyphs_ascii():
    assert paint("x", "danger", bold=True) == "x"


def test_header_line_plain():
    ui_init(plain=True)
    line = header_line("user story", "#1343")
    assert "taiga" in line and "#1343" in line


def test_parse_env_file(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("# c\nTAIGA_USERNAME=a@b.c\n\nBADLINE\nTAIGA_PROJECT_SLUG=sl\n")
    values = parse_env_file(f)
    assert values == {"TAIGA_USERNAME": "a@b.c", "TAIGA_PROJECT_SLUG": "sl"}


def test_norm_item():
    item = {
        "ref": 1343,
        "subject": "Title",
        "status_extra_info": {"name": "New"},
        "assigned_to_extra_info": {"full_name_display": "Jane"},
        "milestone_name": "Sprint 1",
    }
    assert _norm_item(item) == {
        "ref": "1343", "subject": "Title", "status": "New",
        "assignee": "Jane", "sprint": "Sprint 1",
    }


def test_match_status_flag_and_name():
    options = [
        {"id": 1, "name": "New", "slug": "new"},
        {"id": 2, "name": "In Progress", "slug": "in-progress"},
    ]
    assert _match_status(options, "in-progress", None)["id"] == 2
    assert _match_status(options, None, "new")["id"] == 1
    assert _match_status(options, "nope", None) is None


def test_cli_alias_resolution():
    ctx = cli.taiga.make_context("taiga", ["--help"], resilient_parsing=True) if False else None
    from click import Context

    cctx = Context(cli.taiga)
    assert cli.taiga.get_command(cctx, "story").name == "story"
    s = cli.taiga.get_command(cctx, "stories")
    assert s.callback == cli.taiga.get_command(cctx, "story").callback


def test_cli_help_lists_commands():
    result = CliRunner().invoke(cli.taiga, ["--help"])
    assert result.exit_code == 0
    out = result.output
    for name in ("mine", "stories", "tasks", "issues", "epics", "milestones", "wiki", "timeline", "set", "whoami", "project", "projects", "login", "logout", "help"):
        assert name in out


def test_help_alias_flags_accepted():
    result = CliRunner().invoke(cli.taiga, ["help", "--plain"])
    assert "--plain" not in result.output or result.exit_code == 0


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


class FakeApi:
    story_only: bool = True

    def __init__(self, ref=1343):
        self.cfg = {"slug": "proj", "api_url": "http://x", "username": "u"}
        self._ref = ref
        self.item = _norm_item({"ref": self._ref, "subject": "Subj", "status_extra_info": {"name": "New"}, "id": 5})

    def project_id(self):
        return 1

    def load_statuses(self, pid, resource):
        return [
            {"id": 1, "name": "New", "slug": "new"},
            {"id": 2, "name": "In Progress", "slug": "in-progress"},
        ]

    def by_ref(self, kind, ref, soft=False):
        hit = ref == self._ref and (kind == "userstories" if self.story_only else True)
        if hit:
            return {"ref": self._ref, "subject": "Subj", "status_extra_info": {"name": "New"}, "status": 1, "version": 3, "id": 5}
        if soft:
            return None
        raise CliError("Not found")

    def patch(self, path, body):
        return {"ref": self._ref, "subject": "Subj", "status_extra_info": {"name": "In Progress"}}


def test_dry_run_renders_change(capsys):
    ui_init(plain=True)

    class Ctx:
        obj = {"json": False, "plain": True}
        params = {}

    cmd_set(FakeApi(), Ctx(), ["1343"], "In Progress", True)
    out = capsys.readouterr().out
    assert "New" in out and "->" in out and "dry run" in out


def test_already_current_noop(capsys):
    ui_init(plain=True)

    class Statuses(FakeApi):
        def load_statuses(self, pid, resource):
            return [{"id": 1, "name": "New", "slug": "new"}]

    class Ctx:
        obj = {"json": False, "plain": True}
        params = {}

    cmd_set(Statuses(), Ctx(), ["1343"], "New", False)
    out = capsys.readouterr().out
    assert "already" in out


def test_mine_md_exports(tmp_path, monkeypatch):
    ui_init(plain=True)
    story = {"ref": 1343, "id": 5, "subject": "Story subj", "status_extra_info": {"name": "New"}}
    task = {"ref": 9, "id": 6, "subject": "Task subj", "status_extra_info": {"name": "New"}}

    class MineApi:
        cfg = {"slug": "proj", "api_url": "https://api.taiga.io/api/v1"}

        def project(self):
            return {"id": 1, "slug": "proj"}

        def get(self, path, params=None, soft=False):
            if path == "users/me":
                return {"id": 42, "full_name": "Jane"}
            if path == "userstories":
                return [story]
            if path == "tasks":
                return [task]
            return []

        def by_ref(self, resource, ref, soft=False):
            return dict(story if resource == "userstories" else task)

        def history(self, resource, item_id):
            return None

        def attachments(self, resource, item_id):
            return None

        def child_tasks(self, story_id):
            return None

    monkeypatch.setattr(cli, "_api", lambda: MineApi())
    result = CliRunner().invoke(cli.taiga, ["mine", "--md", str(tmp_path)])
    assert result.exit_code == 0, result.output + result.stderr
    names = sorted(p.name for p in tmp_path.glob("*.md"))
    assert len(names) == 2
    assert any(n.startswith("story-1343-") for n in names)
    assert any(n.startswith("task-9-") for n in names)
    assert "2 tickets saved" in result.stderr
    assert "Story subj" in (tmp_path / names[0]).read_text() or "Story subj" in (tmp_path / names[1]).read_text()



# --- projects list / switch -------------------------------------------------


class _Ctx:
    def __init__(self, json_mode=False):
        self.obj = {"json": json_mode, "plain": True}
        self.params = {}


class ProjectsApi:
    def __init__(self, slug="acme-web"):
        self.cfg = {"slug": slug, "api_url": "http://x", "username": "u"}

    def get(self, path, params=None, soft=False):
        if path == "users/me":
            return {"id": 42}
        if path == "projects":
            assert params["member"] == 42
            return [
                {"id": 1, "name": "Acme Web", "slug": "acme-web"},
                {"id": 2, "name": "Design Sys", "slug": "design-system"},
            ]
        if path == "projects/by_slug":
            if params and params.get("slug") == "acme-web":
                return {"id": 1, "name": "Acme Web", "slug": "acme-web"}
            return None
        if path == "projects/2":
            return {"id": 2, "name": "Design Sys", "slug": "design-system"}
        return None


def _read_capsys(capsys):
    out = capsys.readouterr().out
    ui_init(plain=True)
    return out


def test_cmd_projects_lists_with_current_marker(capsys):
    cmd_projects(ProjectsApi(), _Ctx(), None)
    out = capsys.readouterr().out
    assert "projects" in out and "2 shown" in out
    assert "Acme Web" in out and "Design Sys" in out
    assert "acme-web" in out and "design-system" in out
    assert "id 1" in out and "id 2" in out


def test_cmd_projects_limit_and_json(capsys):
    cmd_projects(ProjectsApi(), _Ctx(), 1)
    out = capsys.readouterr().out
    assert "1 shown" in out and "Design Sys" not in out
    cmd_projects(ProjectsApi(), _Ctx(True), None)
    data = json.loads(capsys.readouterr().out)
    assert [p["slug"] for p in data] == ["acme-web", "design-system"]


def test_cmd_projects_no_current_marker_when_unset(capsys):
    import taigacli.render as render_mod

    rows = render_mod.render_projects(
        [{"id": 1, "name": "Acme Web", "slug": "acme-web"}], None
    )
    assert "*" not in rows


def test_cmd_project_switch_by_slug(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cmd_project(ProjectsApi(slug=None), _Ctx(), "acme-web")
    out = capsys.readouterr().out
    assert "Acme Web" in out and "now using" in out
    record = json.loads((tmp_path / "xdg" / "taigacli" / "current_project.json").read_text())
    assert record == {
        "api_url": "http://x",
        "id": 1,
        "slug": "acme-web",
        "name": "Acme Web",
    }


def test_cmd_project_switch_by_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cmd_project(ProjectsApi(slug=None), _Ctx(), "2")
    record = json.loads((tmp_path / "xdg" / "taigacli" / "current_project.json").read_text())
    assert record["slug"] == "design-system"


def test_cmd_project_switch_not_found():
    with pytest.raises(CliError) as exc:
        cmd_project(ProjectsApi(slug=None), _Ctx(), "nope")
    assert "Project not found: nope" in str(exc.value)
    assert "taiga projects" in str(exc.value)


def test_cmd_project_show_with_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "taigacli").mkdir(parents=True)
    (tmp_path / "xdg" / "taigacli" / "current_project.json").write_text(
        json.dumps({"api_url": "http://x", "id": 1, "slug": "acme-web", "name": "Acme Web"})
    )
    cmd_project(ProjectsApi(), _Ctx())
    out = capsys.readouterr().out
    assert "Acme Web" in out and "switched" in out


def test_cmd_project_no_arg_retry_env_source(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TAIGA_PROJECT_SLUG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cmd_project(ProjectsApi(), _Ctx())
    out = capsys.readouterr().out
    assert ".env" in out


def test_cmd_project_no_project_selected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cmd_project(ProjectsApi(slug=None), _Ctx())
    out = capsys.readouterr().out
    assert "no project selected" in out and "taiga projects" in out


def test_whoami_without_project(capsys):
    cmd_whoami(ProjectsApi(slug=None), _Ctx())
    out = capsys.readouterr().out
    assert "taiga projects" in out


def test_api_project_guard_without_project(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("TAIGA_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TAIGA_TOKEN_FILE", str(tmp_path / ".token"))
    (tmp_path / ".token").write_text("tok")
    from taigacli.api import Api

    api = Api(require_project=False)
    assert api.cfg["slug"] is None
    with pytest.raises(CliError) as exc:
        api.project()
    assert "No project selected" in str(exc.value)


def test_cli_projects_command(monkeypatch):
    monkeypatch.setattr(cli, "Api", _MiniApi)
    result = CliRunner().invoke(cli.taiga, ["projects", "--limit", "1"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Acme Web" in result.output and "Design Sys" not in result.output


def test_cli_project_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(cli, "Api", _MiniApi)
    result = CliRunner().invoke(cli.taiga, ["project", "acme-web"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    record = json.loads((tmp_path / "xdg" / "taigacli" / "current_project.json").read_text())
    assert record["slug"] == "acme-web"


def test_cli_projects_json(monkeypatch):
    monkeypatch.setattr(cli, "Api", _MiniApi)
    result = CliRunner().invoke(cli.taiga, ["projects", "--json"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert [p["slug"] for p in json.loads(result.output)] == ["acme-web", "design-system"]


class _MiniApi:
    def __init__(self, require_project=True):
        self.cfg = {"slug": None, "api_url": "http://x", "username": "u"}

    def get(self, path, params=None, soft=False):
        if path == "users/me":
            return {"id": 42}
        if path == "projects":
            return [
                {"id": 1, "name": "Acme Web", "slug": "acme-web"},
                {"id": 2, "name": "Design Sys", "slug": "design-system"},
            ]
        if path == "projects/by_slug":
            if params and params.get("slug") == "acme-web":
                return {"id": 1, "name": "Acme Web", "slug": "acme-web"}
            return None
        return None
