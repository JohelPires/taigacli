from __future__ import annotations

import re
import sys
from pathlib import Path

from markdownify import markdownify as _markdownify

from taigacli.errors import CliError
from taigacli.render import strip_html
from taigacli.resources import HISTORY_KINDS, _norm_item, normalize_name

TYPE_SLUGS = {
    "userstories": "story",
    "tasks": "task",
    "issues": "issue",
    "epics": "epic",
    "milestones": "milestone",
    "wiki": "wiki",
}


def html_to_md(text) -> str:
    if not text:
        return ""
    html = str(text)
    try:
        converted = _markdownify(html, heading_style="ATX", bullets="-")
    except Exception:
        return strip_html(html)
    converted = re.sub(r"\n{3,}", "\n\n", converted).strip()
    return converted


def slugify(subject: str) -> str:
    return normalize_name(subject)[:60].strip("-")


def auto_name(resource: str, item: dict) -> str:
    typ = TYPE_SLUGS.get(resource, normalize_name(resource))
    key = item.get("ref") or item.get("id") or "item"
    slug = slugify(_norm_item(item)["subject"]) or "ticket"
    return f"{typ}-{key}-{slug}.md"


def _one(value) -> str:
    return str(value or "").strip()


def front_matter(item: dict, resource: str) -> list[str]:
    n = _norm_item(item)
    lines = ["---"]
    if resource in TYPE_SLUGS:
        lines.append(f"type: {TYPE_SLUGS[resource]}")
    if item.get("ref"):
        lines.append(f"ref: {item['ref']}")
    if item.get("id"):
        lines.append(f"id: {item['id']}")
    if n["status"]:
        lines.append(f"status: {n['status']}")
    if n["assignee"]:
        lines.append(f"assignee: {n['assignee']}")
    if n["sprint"]:
        lines.append(f"milestone: {n['sprint']}")
    tags = item.get("tags")
    if tags:
        cleaned = [t[0] if isinstance(t, (list, tuple)) and t else t for t in tags]
        lines.append("tags: [" + ", ".join(str(t) for t in cleaned) + "]")
    for key, label in (("created_date", "created"), ("modified_date", "modified")):
        value = _one(item.get(key))
        if value:
            lines.append(f"{label}: {value[:10]}")
    lines.append("---")
    return lines


def _comments_block(history) -> list[str]:
    entries = [h for h in (history or []) if isinstance(h, dict) and _one(h.get("comment"))]
    if not entries:
        return []
    out = ["## Comments"]
    for entry in entries:
        user = entry.get("user") if isinstance(entry.get("user"), dict) else {}
        who = _one(user.get("name")) or _one(user.get("full_name")) or "unknown"
        when = _one(entry.get("created_at") or entry.get("created"))[:19].replace("T", " ")
        body = html_to_md(entry.get("comment_html") or entry.get("comment"))
        out.append(f"### {who} · {when}".rstrip(" ·"))
        out.append(body)
        out.append("")
    return out


def _attachments_block(attachments) -> list[str]:
    files = [a for a in (attachments or []) if isinstance(a, dict) and _one(a.get("name"))]
    if not files:
        return []
    lines = ["## Attachments"]
    for att in files:
        name = _one(att.get("name"))
        url = _one(att.get("url") or att.get("attached_file"))
        size = att.get("size")
        size_note = f" ({size / 1024:.1f} KB)" if isinstance(size, (int, float)) and size else ""
        lines.append(f"- [{name}]({url}){size_note}" if url else f"- {name}{size_note}")
    return lines


def _requirements_block(item: dict) -> list[str]:
    lines = []
    for field, title in (
        ("client_requirement", "Client requirement"),
        ("team_requirement", "Team requirement"),
    ):
        body = html_to_md(item.get(field))
        if body:
            lines.append(f"## {title}")
            lines.append(body)
            lines.append("")
    return lines


def _tasks_block(tasks) -> list[str]:
    rows = [_norm_item(t) for t in (tasks or []) if isinstance(t, dict)]
    if not rows:
        return []
    lines = ["## Tasks"]
    for r in rows:
        bits = [f"#{r['ref']} {r['subject']}"]
        if r["status"]:
            bits.append(r["status"])
        if r["assignee"]:
            bits.append(r["assignee"])
        lines.append("- " + " — ".join(bits))
    return lines


def body_markdown(item: dict, resource: str) -> list[str]:
    # wiki page content is already markdown source; ticket/epic fields are HTML
    if resource == "wiki" and item.get("content"):
        text = str(item["content"]).strip()
        return [text] if text else []
    return [body] if (body := html_to_md(item.get("description"))) else []


def render_markdown(item: dict, resource: str, extras: dict | None = None) -> str:
    extras = extras or {}
    n = _norm_item(item)
    lines = front_matter(item, resource)
    lines.append("")
    lines.append(f"# {n['subject'] or n['ref']}")
    for part in body_markdown(item, resource):
        lines.append("")
        lines.append(part)
    if resource == "userstories":
        lines.extend(_requirements_block(item))
        lines.extend(_tasks_block(extras.get("tasks")))
    lines.extend(_comments_block(extras.get("comments")))
    lines.extend(_attachments_block(extras.get("attachments")))
    return "\n".join(lines).rstrip() + "\n"


def _confirm_overwrite(target: Path) -> None:
    if not sys.stdin.isatty():
        raise CliError(f"{target} exists - rerun with --force to overwrite")
    import click

    click.confirm(f"overwrite {target}?", default=False, abort=True)


def write_markdown(path_arg: str, content: str, force: bool = False, default_name: str | None = None) -> Path:
    target = Path(path_arg).expanduser()
    if target.is_dir():
        if not default_name:
            raise CliError(f"{target} is a directory")
        target = target / default_name
    if target.exists() and not force:
        _confirm_overwrite(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def collect(api, resource: str, item: dict) -> dict:
    item_id = item.get("id")
    extras = {"tasks": None, "comments": None, "attachments": None}
    if HISTORY_KINDS.get(resource):
        extras["comments"] = api.history(resource, item_id)
    extras["attachments"] = api.attachments(resource, item_id)
    if resource == "userstories":
        extras["tasks"] = api.child_tasks(item_id)
    return extras
