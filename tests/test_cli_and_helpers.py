from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import taigacli.cli as cli
from taigacli.commands import _match_status, cmd_set
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
    for name in ("mine", "stories", "tasks", "issues", "epics", "milestones", "wiki", "timeline", "set", "whoami", "project", "help"):
        assert name in out


def test_help_alias_flags_accepted():
    result = CliRunner().invoke(cli.taiga, ["help", "--plain"])
    assert "--plain" not in result.output or result.exit_code == 0


class FakeApi:
    story_only: bool = True

    def __init__(self, ref=1343):
        self.cfg = {"slug": "proj", "api_url": "http://x", "username": "u", "password": "p"}
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
