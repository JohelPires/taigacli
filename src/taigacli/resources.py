from __future__ import annotations

import re


RESOURCES = {
    "epics": "epics",
    "stories": "userstories",
    "userstories": "userstories",
    "tasks": "tasks",
    "issues": "issues",
    "milestones": "milestones",
    "members": "memberships",
    "memberships": "memberships",
    "wiki": "wiki",
    "timeline": "",
}

LABELS = {
    "userstories": "user story",
    "stories": "user story",
    "tasks": "task",
    "issues": "issue",
    "epics": "epic",
    "milestones": "milestone",
    "wiki": "wiki page",
}

STATUS_KINDS = {
    "userstories": "userstory-statuses",
    "stories": "userstory-statuses",
    "tasks": "task-statuses",
    "issues": "issue-statuses",
}

SET_ALIASES = {
    "story": "userstories",
    "stories": "userstories",
    "userstory": "userstories",
    "userstories": "userstories",
    "task": "tasks",
    "tasks": "tasks",
    "issue": "issues",
    "issues": "issues",
}

# resource-as-command: canonical command name -> (resource key, aliases)
RESOURCE_SPECS = {
    "stories": ("userstories", ("story", "userstories", "userstory")),
    "tasks": ("tasks", ("task",)),
    "issues": ("issues", ("issue",)),
    "epics": ("epics", ("epic",)),
    "milestones": ("milestones", ("milestone",)),
    "members": ("memberships", ("memberships", "membership")),
    "wiki": ("wiki", ()),
    "timeline": ("timeline", ()),
}

# any spelling a user may type (command or alias) -> canonical resource key
RESOURCE_CANONICAL: dict[str, str] = {}
for _cmd, (_res, _aliases) in RESOURCE_SPECS.items():
    RESOURCE_CANONICAL[_cmd] = _res
    for _alias in _aliases:
        RESOURCE_CANONICAL[_alias] = _res

# resources resolved by ref (as opposed to numeric API id)
REF_RESOURCES = ("userstories", "tasks", "issues", "epics")

# audit-trail/history kinds per canonical resource
HISTORY_KINDS = {
    "userstories": "userstory",
    "tasks": "task",
    "issues": "issue",
    "epics": "epic",
}


RESOURCE_HELP = {
    "stories": "list user stories; add a ref to show one",
    "tasks": "list tasks; add a ref to show one",
    "issues": "list issues; add a ref to show one",
    "epics": "list epics; add a ref to show one",
    "milestones": "list milestones; add an id to show one",
    "members": "list project members; add an id to show one",
    "wiki": "list wiki pages; add an id to show one",
    "timeline": "recent project activity (list only)",
}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _norm_item(item: dict) -> dict:
    status_info = item.get("status_extra_info")
    status = status_info.get("name") if isinstance(status_info, dict) else (item.get("status") or "")
    info = item.get("assigned_to_extra_info")
    assignee = ""
    if isinstance(info, dict):
        assignee = info.get("full_name_display") or info.get("username") or ""
    return {
        "ref": str(item.get("ref", item.get("id", ""))),
        "subject": str(item.get("subject") or item.get("title") or item.get("name") or item.get("slug") or ""),
        "status": str(status or ""),
        "assignee": str(assignee),
        "sprint": str(item.get("milestone_name") or ""),
    }
