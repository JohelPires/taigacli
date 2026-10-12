from __future__ import annotations

import pytest

from taigacli.export import (
    auto_name,
    body_markdown,
    front_matter,
    html_to_md,
    render_markdown,
    slugify,
    ticket_url,
    web_base,
    write_markdown,
)
from taigacli.errors import CliError
from taigacli.theme import ui_init


@pytest.fixture(autouse=True)
def _plain():
    ui_init(plain=True)


STORY = {
    "ref": 1343,
    "id": 9606719,
    "subject": "Set tutor test level thresholds",
    "status_extra_info": {"name": "In progress"},
    "assigned_to_extra_info": {"full_name_display": "Johel Pires"},
    "milestone_name": "Sprint 12",
    "tags": [["frontend", "#3563"], "scoring"],
    "created_date": "2026-10-06T10:00:00.000Z",
    "modified_date": "2026-10-09T11:30:00.000Z",
    "description": "<p>Hello <strong>world</strong></p><ul><li>one</li><li>two</li></ul>",
    "client_requirement": "<p>Client says <em>yes</em></p>",
}


def test_html_to_md_basics():
    out = html_to_md("<p>Hello <b>bold</b> and <i>it</i></p>")
    assert "Hello" in out and "bold" in out
    list_out = html_to_md("<ul><li>one</li><li>two</li></ul>")
    assert "- one" in list_out and "- two" in list_out


def test_html_to_md_fallback():
    assert "123" in html_to_md(123)  # scalars pass through as text
    assert "plain text" in html_to_md("plain text")
    assert html_to_md("<p><br></p>") == "" or html_to_md("<p><br></p>").strip() == ""


def test_html_to_md_empty():
    assert html_to_md("") == ""
    assert html_to_md(None) == ""


def test_slugify():
    assert slugify("Hello, World! This is a ticket") == "hello-world-this-is-a-ticket"
    assert len(slugify("x" * 200)) <= 60


def test_auto_name():
    name = auto_name("userstories", STORY)
    assert name.startswith("story-1343-") and name.endswith(".md")
    assert auto_name("milestones", {"id": 5, "subject": "QA Backlog"}) == "milestone-5-qa-backlog.md"


def test_front_matter_fields():
    fm = "\n".join(front_matter(STORY, "userstories"))
    assert "type: story" in fm
    assert "ref: 1343" in fm
    assert "status: In progress" in fm
    assert "assignee: Johel Pires" in fm
    assert "tags: [frontend, scoring]" in fm
    assert fm.splitlines()[0] == "---" and fm.splitlines()[-1].rstrip() == "---"


def test_web_base_hosted():
    assert web_base("https://api.taiga.io/api/v1") == "https://tree.taiga.io"


def test_web_base_self_hosted():
    assert web_base("https://taiga.example.com/api/v1") == "https://taiga.example.com"
    assert web_base("https://team.example.org/taiga/api/v1") == "https://team.example.org/taiga"


def test_web_base_invalid():
    assert web_base("") == ""
    assert web_base("not-a-url") == ""


def test_ticket_url_per_resource():
    hosted = "https://api.taiga.io/api/v1"
    assert ticket_url(hosted, "my-slug", "userstories", STORY) == "https://tree.taiga.io/project/my-slug/us/1343"
    assert ticket_url(hosted, "my-slug", "tasks", {"ref": 7, "id": 99}) == "https://tree.taiga.io/project/my-slug/task/7"
    assert ticket_url(hosted, "my-slug", "issues", {"ref": 8}) == "https://tree.taiga.io/project/my-slug/issue/8"
    assert ticket_url(hosted, "my-slug", "epics", {"ref": 9}) == "https://tree.taiga.io/project/my-slug/epic/9"


def test_ticket_url_falls_back_to_id():
    hosted = "https://api.taiga.io/api/v1"
    assert ticket_url(hosted, "s", "tasks", {"id": 42}) == "https://tree.taiga.io/project/s/task/42"


def test_ticket_url_none_cases():
    hosted = "https://api.taiga.io/api/v1"
    assert ticket_url(hosted, "s", "wiki", {"slug": "home"}) is None
    assert ticket_url(hosted, "s", "milestones", {"id": 5}) is None
    assert ticket_url(hosted, None, "tasks", {"ref": 1}) is None
    assert ticket_url("", "s", "tasks", {"ref": 1}) is None


def test_front_matter_includes_url():
    fm = "\n".join(front_matter(STORY, "userstories", url="https://tree.taiga.io/project/s/us/1343"))
    assert "url: https://tree.taiga.io/project/s/us/1343" in fm
    # id line directly precedes the url line
    lines = fm.splitlines()
    assert lines[lines.index("url: https://tree.taiga.io/project/s/us/1343") - 1].startswith("id:")


def test_front_matter_without_url():
    assert not any(line.startswith("url:") for line in front_matter(STORY, "userstories"))


def test_render_markdown_includes_url():
    md = render_markdown(STORY, "userstories", {}, url="https://tree.taiga.io/project/s/us/1343")
    assert md.startswith("---\ntype: story")
    assert "url: https://tree.taiga.io/project/s/us/1343" in md


def test_render_markdown_sections():
    extras = {
        "tasks": [{"ref": 424, "subject": "client work", "status_extra_info": {"name": "In progress"}, "assigned_to_extra_info": {}}],
        "comments": [{"user": {"name": "Rosalia"}, "created_at": "2025-07-11T15:44:29.000Z", "comment": "Closing", "comment_html": "<p>Closing</p>"}],
        "attachments": [{"name": "shot.png", "size": 1024, "url": "http://f/shot.png"}],
    }
    md = render_markdown(STORY, "userstories", extras)
    assert md.startswith("---\ntype: story")
    assert "# Set tutor test level thresholds" in md
    assert "Hello" in md and "**world**" in md
    assert "## Client requirement" in md
    assert "## Tasks" in md and "#424 client work" in md
    assert "## Comments" in md and "Rosalia" in md
    assert "## Attachments" in md and "shot.png" in md and "(1.0 KB)" in md
    assert md.endswith("\n")


def test_render_markdown_wiki_uses_content():
    md = render_markdown({"id": 7, "subject": "Home", "content": "# Welcome"}, "wiki", {})
    assert "# Welcome" in md


def test_write_markdown_new_file(tmp_path):
    target = tmp_path / "sub" / "out.md"
    written = write_markdown(str(target), "hello", force=False)
    assert written.read_text() == "hello"
    assert (tmp_path / "sub" / "out.md").exists()


def test_write_markdown_directory_autoname(tmp_path):
    path = write_markdown(str(tmp_path), "data", force=True, default_name="story-1-a.md")
    assert path == tmp_path / "story-1-a.md"
    assert path.read_text() == "data"


def test_write_markdown_creates_new_folder(tmp_path):
    path = write_markdown(str(tmp_path / "newdir"), "data", force=True, default_name="story-1-a.md")
    assert path == tmp_path / "newdir" / "story-1-a.md"
    assert path.read_text() == "data"


def test_write_markdown_overwrite_refused_non_tty(tmp_path):
    target = tmp_path / "x.md"
    target.write_text("old")
    with pytest.raises(CliError):
        write_markdown(str(target), "new", force=False)


def test_write_markdown_overwrite_force(tmp_path):
    target = tmp_path / "x.md"
    target.write_text("old")
    write_markdown(str(target), "new", force=True)
    assert target.read_text() == "new"


def test_body_markdown_empty():
    assert body_markdown({"subject": "x"}, "tasks") == []
