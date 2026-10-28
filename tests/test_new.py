from __future__ import annotations

import json

import pytest

from taigacli.commands import cmd_new
from taigacli.errors import CliError
from taigacli.theme import ui_init


@pytest.fixture(autouse=True)
def _plain():
    ui_init(plain=True)


class _Ctx:
    def __init__(self, json_mode=False):
        self.obj = {"json": json_mode, "plain": True}
        self.params = {}


class NewApi:
    def __init__(self):
        self.cfg = {"slug": "proj", "api_url": "http://x", "username": "u"}
        self.calls = []

    def project_id(self):
        return 1

    def load_statuses(self, pid, resource):
        assert pid == 1
        return [
            {"id": 1, "name": "New", "slug": "new"},
            {"id": 2, "name": "In Progress", "slug": "in-progress"},
        ]

    def by_ref(self, kind, ref, soft=False):
        assert kind == "userstories"
        if ref == 3:
            return {"id": 17, "ref": 3, "subject": "Parent story"}
        return None

    def post(self, path, body):
        self.calls.append((path, body))
        return {
            "id": 99,
            "ref": 1343,
            "subject": body["subject"],
            "status_extra_info": {"name": "New"},
            "description": body.get("description", ""),
        }


def test_new_story_minimal_payload(capsys):
    api = NewApi()
    cmd_new(api, _Ctx(), "story", "  Fix login  ")
    assert api.calls == [("userstories", {"project": 1, "subject": "Fix login"})]
    out = capsys.readouterr().out
    assert "user story" in out
    assert "#1343" in out
    assert "Fix login" in out


@pytest.mark.parametrize(
    "alias,path",
    [
        ("story", "userstories"),
        ("stories", "userstories"),
        ("userstory", "userstories"),
        ("userstories", "userstories"),
        ("task", "tasks"),
        ("tasks", "tasks"),
        ("issue", "issues"),
        ("issues", "issues"),
    ],
)
def test_new_resource_aliases(alias, path):
    api = NewApi()
    cmd_new(api, _Ctx(), alias, "Subject")
    assert api.calls[0][0] == path


def test_new_description_and_status_mapping():
    api = NewApi()
    cmd_new(api, _Ctx(), "issue", "Crash", "**Steps**\n\n1. Open", "in-progress")
    assert api.calls[0] == (
        "issues",
        {
            "project": 1,
            "subject": "Crash",
            "description": "**Steps**\n\n1. Open",
            "status": 2,
        },
    )


def test_new_task_with_parent_story():
    api = NewApi()
    cmd_new(api, _Ctx(), "task", "Write tests", story_ref=3)
    assert api.calls[0] == (
        "tasks",
        {"project": 1, "subject": "Write tests", "user_story": 17},
    )


def test_new_task_without_parent_story():
    api = NewApi()
    cmd_new(api, _Ctx(), "task", "Standalone")
    assert api.calls[0] == ("tasks", {"project": 1, "subject": "Standalone"})


def test_new_rejects_unsupported_resource():
    with pytest.raises(CliError, match="stories, tasks, or issues"):
        cmd_new(NewApi(), _Ctx(), "epic", "Nope")


def test_new_rejects_empty_subject():
    with pytest.raises(CliError, match="Subject cannot be empty"):
        cmd_new(NewApi(), _Ctx(), "story", "   ")


def test_new_unknown_status_lists_options():
    with pytest.raises(CliError) as exc:
        cmd_new(NewApi(), _Ctx(), "story", "Subject", status_opt="nope")
    assert "No status matches 'nope'" in str(exc.value)
    assert "New" in str(exc.value)
    assert "In Progress" in str(exc.value)


def test_new_missing_story_ref():
    with pytest.raises(CliError, match="Story not found: #404"):
        cmd_new(NewApi(), _Ctx(), "task", "Task", story_ref=404)


def test_new_story_flag_rejected_for_non_task():
    with pytest.raises(CliError, match="--story only applies to tasks"):
        cmd_new(NewApi(), _Ctx(), "issue", "Issue", story_ref=3)


def test_new_json_prints_raw_payload(capsys):
    cmd_new(NewApi(), _Ctx(json_mode=True), "story", "Subject")
    data = json.loads(capsys.readouterr().out)
    assert data["ref"] == 1343
    assert data["subject"] == "Subject"


# --- cli wiring -------------------------------------------------------------


def test_cli_new_invocation(monkeypatch):
    import taigacli.cli as cli
    from click.testing import CliRunner

    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(
        cli.taiga, ["new", "story", "Fix login", "--description", "Body", "--json"]
    )
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert json.loads(result.output)["ref"] == 1343
    assert api.calls[0][1]["description"] == "Body"


def test_cli_new_json_before_command(monkeypatch):
    import taigacli.cli as cli
    from click.testing import CliRunner

    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(cli.taiga, ["--json", "new", "issue", "Crash"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert json.loads(result.output)["ref"] == 1343


def test_cli_new_task_story_option(monkeypatch):
    import taigacli.cli as cli
    from click.testing import CliRunner

    api = NewApi()
    monkeypatch.setattr(cli, "_api", lambda: api)
    result = CliRunner().invoke(cli.taiga, ["new", "task", "Write tests", "--story", "3"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert api.calls[0][1]["user_story"] == 17


def test_cli_new_listed_in_help():
    import taigacli.cli as cli
    from click.testing import CliRunner

    result = CliRunner().invoke(cli.taiga, ["--help"])
    assert result.exit_code == 0
    assert "new" in result.output
