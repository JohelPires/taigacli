from __future__ import annotations

import json
import os
import sys
import textwrap

from taigacli import credentials
from taigacli.config import load_current_project, save_current_project
from taigacli.errors import CliError
from taigacli.render import (
    eyebrow,
    header_line,
    render_change,
    render_projects,
    render_record,
    render_rows,
    render_status_menu,
    ribbon,
    show_summary,
    squeeze,
    status_cell,
    _merge_counts,
)
from taigacli.resources import (
    LABELS,
    REF_RESOURCES,
    RESOURCES,
    SET_ALIASES,
    _norm_item,
    normalize_name,
)
from taigacli.theme import GUTTER, g, paint


def cmd_list(api, ctx, resource: str, limit: int | None, filters: list[str] | None):
    flt: dict[str, str] = {}
    for f in filters or []:
        k, _, v = f.partition("=")
        flt[k] = v
    if resource == "timeline":
        pid = api.project_id()
        data = api.get(f"timeline/project/{pid}")
    else:
        path = RESOURCES[resource]
        flt.setdefault("project", api.project_id())
        data = api.get(path, params=flt)
    if isinstance(data, list) and limit:
        data = data[:limit]
    if is_json(ctx):
        print(json.dumps(data, indent=2))
        return
    if resource in ("userstories", "stories", "tasks", "issues", "epics", "milestones", "wiki"):
        count = len(data) if isinstance(data, list) else 0
        print(header_line(resource, f"{count} shown"))
        print()
    show_summary(data, resource)


def cmd_get(api, ctx, resource: str, item_id: int):
    path = RESOURCES.get(resource, resource)
    if path in REF_RESOURCES:
        item = api.by_ref(path, item_id)
        if is_json(ctx):
            print(json.dumps(item, indent=2))
        else:
            print(render_record(item, LABELS.get(path, path)))
        return
    data = api.get(f"{path}/{item_id}")
    if is_json(ctx):
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, dict):
        print(render_record(data, LABELS.get(path, path)))
    else:
        print(json.dumps(data, indent=2))


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


def cmd_mine(api, ctx, limit: int | None, md_path: str | None = None):
    proj = api.project()
    me = api.get("users/me")
    uid = me.get("id")
    if not uid:
        raise CliError("Could not resolve current user id")
    full_name = me.get("full_name") or me.get("username") or "?"
    groups = {"userstories": [], "tasks": [], "issues": []}
    for resource in groups:
        filters = {"project": proj["id"], "assigned_to": uid, "status__is_closed": "false"}
        data = api.get(RESOURCES[resource], params=filters)
        if isinstance(data, list) and limit:
            data = data[:limit]
        groups[resource] = data if isinstance(data, list) else ([] if data is None else [data])
    if md_path:
        _mine_export(api, groups, md_path)
        return
    if is_json(ctx):
        print(json.dumps(groups, indent=2))
        return
    total = sum(len(v) for v in groups.values())
    print(header_line(proj.get("slug", ""), f"{full_name} · {total} open"))
    print()
    print(ribbon(_merge_counts({k: [_norm_item(i) for i in v if isinstance(i, dict)] for k, v in groups.items()})))
    print()
    labels = {"userstories": "USER STORIES", "tasks": "TASKS", "issues": "ISSUES"}
    for resource, label in labels.items():
        rows = [_norm_item(i) for i in groups[resource] if isinstance(i, dict)]
        print(eyebrow(label, f"{len(rows)} open"))
        print(render_rows(rows, compact=True, empty_text="nothing assigned to you"))
        print()


def _mine_export(api, groups: dict, md_path: str) -> None:
    from taigacli import export

    written = []
    for resource, items in groups.items():
        for item in items:
            if not isinstance(item, dict) or not item.get("ref"):
                continue
            detail = api.by_ref(resource, item["ref"], soft=True)
            if not isinstance(detail, dict):
                continue
            path = export.export_item(api, resource, detail, md_path, force=True)
            written.append(path)
            print(GUTTER + paint(f"saved {path}", "muted"), file=sys.stderr)
    print(GUTTER + paint(f"{len(written)} tickets saved to {md_path}", "muted"), file=sys.stderr)


def cmd_whoami(api, ctx):
    user = api.get("users/me")
    if is_json(ctx):
        print(json.dumps(user, indent=2))
        return
    full_name = user.get("full_name", user.get("username", "?"))
    proj = api.cfg.get("slug") or "none - run `taiga projects`"
    line = paint(g("dot"), "ready") + " " + paint(str(full_name), "ink", bold=True)
    line += paint(f"  ·  id {user.get('id')}  ·  project {proj}", "muted")
    print()
    print(line)
    print()


def cmd_projects(api, ctx, limit: int | None = None):
    me = api.get("users/me")
    uid = me.get("id") if isinstance(me, dict) else None
    if not uid:
        raise CliError("Could not resolve current user id")
    data = api.get(
        "projects",
        params={"member": uid, "order_by": "memberships__user_order"},
    )
    if isinstance(data, dict):
        data = [data]
    if isinstance(data, list) and limit:
        data = data[:limit]
    if is_json(ctx):
        print(json.dumps(data, indent=2))
        return
    print(header_line("projects", f"{len(data) if isinstance(data, list) else 0} shown"))
    print()
    print(render_projects(data if isinstance(data, list) else [], api.cfg.get("slug")))
    print()


def _slug_source(slug: str | None) -> str:
    if not slug:
        return "none"
    stored = load_current_project()
    if stored and stored.get("slug") == slug:
        return "switched"
    if os.environ.get("TAIGA_PROJECT_SLUG") == slug:
        return "env"
    return ".env"


def cmd_project(api, ctx, target: str | None = None):
    target = str(target).strip() if target else ""
    if not target:
        slug = api.cfg.get("slug")
        if not slug:
            if is_json(ctx):
                print(json.dumps(None))
                return
            print()
            print(GUTTER + paint("no project selected - run `taiga projects`, then `taiga project <slug|id>`", "muted"))
            print()
            return
        proj = api.get("projects/by_slug", params={"slug": slug})
        if is_json(ctx):
            print(json.dumps(proj, indent=2))
            return
        line = paint(g("dot"), "ready") + " " + paint(str(proj.get("name", proj.get("slug", "?"))), "ink", bold=True)
        line += paint(f"  ·  id {proj.get('id')}  ·  slug {proj.get('slug')}  ·  {squeeze(_slug_source(slug), 10)}", "muted")
        print()
        print(line)
        print()
        return
    if target.isdigit():
        proj = api.get(f"projects/{int(target)}", soft=True)
    else:
        proj = api.get("projects/by_slug", params={"slug": target}, soft=True)
    if not isinstance(proj, dict) or not proj.get("id"):
        raise CliError(f"Project not found: {target} - run `taiga projects`")
    path = save_current_project(proj, api_url_val=api.cfg.get("api_url"))
    if is_json(ctx):
        print(json.dumps(proj, indent=2))
        return
    print()
    print(GUTTER + paint(g("dot"), "ready") + " " + paint(str(proj.get("name") or proj.get("slug")), "ink", bold=True))
    print(GUTTER + paint(f"now using  ·  id {proj.get('id')}  ·  slug {proj.get('slug')}  ·  saved {path}", "muted"))
    print()


def _match_status(options: list[dict], flag_token: str | None, status_opt: str | None) -> dict | None:
    if status_opt:
        want_id_value = None
        if str(status_opt).isdigit():
            want_id_value = int(status_opt)
        for option in options:
            if want_id_value is not None and option.get("id") == want_id_value:
                return option
            if option.get("name", "").lower() == str(status_opt).lower():
                return option
            if normalize_name(option.get("name", "")) == normalize_name(str(status_opt)):
                return option
            if (option.get("slug") or "").lower() == normalize_name(str(status_opt)):
                return option
        return None
    if not flag_token:
        return None
    token = normalize_name(flag_token)
    for option in options:
        if normalize_name(option.get("name", "")) == token or (option.get("slug") or "").lower() == token:
            return option
    return None


def cmd_set(api, ctx, tokens: list, status_opt: str | None, dry_run: bool):
    tokens = [str(t) for t in tokens if str(t).strip()]
    flags = [t.lstrip("-") for t in tokens if t.startswith("--")]
    tokens = [t for t in tokens if not t.startswith("--")]
    single_dash = [t for t in tokens if t.startswith("-")]
    if single_dash:
        raise CliError(f"Unrecognized arguments: {' '.join(single_dash)}")
    if len(flags) > 1:
        raise CliError(f"Give exactly one status flag, got: {', '.join(flags)}")
    flag_token = flags[0] if flags else None
    if status_opt and flag_token:
        raise CliError(f"Use --status or the status flag, not both ('--{flag_token}')")
    if len(tokens) > 2:
        raise CliError(f"Too many arguments: {' '.join(tokens)} - use: set [resource] <ref> --<status>")

    resource_hint = None
    ref = None
    if len(tokens) == 1:
        if tokens[0].isdigit():
            ref = int(tokens[0])
        elif tokens[0] in SET_ALIASES:
            resource_hint = SET_ALIASES[tokens[0]]
        else:
            raise CliError(f"Unknown resource '{tokens[0]}' - use one of: story, task, issue, or a ref number")
    elif len(tokens) == 2:
        if tokens[0].isdigit():
            raise CliError(f"Unexpected '{tokens[1]}' after ref {tokens[0]} - the status goes after the ref: set {tokens[0]} --<status>")
        if tokens[0] not in SET_ALIASES:
            raise CliError(f"Unknown resource '{tokens[0]}' - use one of: story, task, issue")
        if not tokens[1].isdigit():
            raise CliError(f"Ref must be a number, got '{tokens[1]}'")
        resource_hint, ref = SET_ALIASES[tokens[0]], int(tokens[1])
    elif len(tokens) == 0 and flag_token is None and status_opt is None:
        raise CliError(f"usage: set [resource] <ref> --<status>   e.g. set 1344 --in-review")

    pid = api.project_id()
    kinds = [resource_hint] if resource_hint else ["userstories", "tasks", "issues"]

    item = None
    resource = resource_hint
    if ref is not None:
        candidates = []
        for kind in kinds:
            found = api.by_ref(kind, ref, soft=True)
            if found:
                candidates.append((kind, found))
        if not candidates:
            plurals = {"userstories": "user stories", "tasks": "tasks", "issues": "issues"}
            wanted = ", ".join(plurals.get(k, k) for k in kinds)
            raise CliError(f"Not found: no {wanted} with ref #{ref}")
        if len(candidates) > 1:
            if is_json(ctx):
                data = [
                    {"resource": kind, "id": it.get("id"), "ref": ref, "subject": _norm_item(it).get("subject", "")}
                    for kind, it in candidates
                ]
                print(json.dumps(data, indent=2))
                return
            out = [header_line("ambiguous ref", f"#{ref}"), ""]
            for kind, it in candidates:
                out.append(GUTTER + paint(LABELS.get(kind, kind) + f" #{ref}", "accent") + paint(f"  {squeeze(_norm_item(it).get('subject', ''), 60)}", "ink"))
            out.append("")
            examples = {"userstories": "story", "tasks": "task", "issues": "issue"}
            hint = "|".join(examples.get(k, k) for k, _ in candidates)
            out.append(GUTTER + paint(f"prefix the resource: taiga set ({hint}) {ref} --<status>", "muted"))
            print("\n".join(out))
            return
        resource, item = candidates[0]
    if resource is None:
        raise CliError("Tell me the resource to list statuses for: set story, set task, set issue")

    options = api.load_statuses(pid, resource)

    target_status = _match_status(options, flag_token, status_opt)
    if target_status is None:
        if is_json(ctx):
            print(json.dumps(options, indent=2))
            return
        if flag_token:
            print(paint(g("dot"), "danger") + paint(f" no status matches '--{flag_token}'", "danger"), file=sys.stderr)
        if item is not None:
            n = _norm_item(item)
            menu = render_status_menu(LABELS.get(resource, resource), item.get("ref") or ref, n.get("subject", ""), {"name": n.get("status", "")}, options)
        else:
            menu = render_status_menu(resource, None, "", None, options)
        print(menu)
        return

    if item is None:
        raise CliError(f"Give a ref: set {resource} <ref> --{normalize_name(new_status_name(target_status))}")

    n = _norm_item(item)
    current_name = n.get("status", "")
    new_name = new_status_name(target_status)
    if dry_run and is_json(ctx):
        print(json.dumps({"ref": item.get("ref"), "resource": resource, "from": current_name, "to": new_name}, indent=2))
        return
    if current_name.lower() == new_name.lower():
        print()
        print(GUTTER + paint(f"already {status_cell(current_name)}", "muted"))
        print()
        return
    if dry_run:
        print(render_change(LABELS.get(resource, resource), item.get("ref"), n.get("subject", ""), current_name, new_name, True))
        return
    patch_body: dict = {"status": target_status["id"]}
    if item.get("version"):
        patch_body["version"] = item["version"]
    patched = api.patch(f"{RESOURCES.get(resource, resource)}/{item['id']}", patch_body)
    if is_json(ctx):
        print(json.dumps(patched, indent=2))
        return
    changed = _norm_item(patched) if isinstance(patched, dict) else n
    print(render_change(LABELS.get(resource, resource), item.get("ref"), n.get("subject", ""), current_name, changed.get("status") or new_name, False))
    print()


def cmd_get_md(api, ctx, resource: str, item_id: int, md_path: str, force: bool):
    from taigacli import export
    from taigacli.theme import g

    path = RESOURCES.get(resource, resource)
    if path in REF_RESOURCES:
        item = api.by_ref(path, item_id)
    else:
        item = api.get(f"{path}/{item_id}")
    if not isinstance(item, dict):
        raise CliError(f"Not found: {LABELS.get(path, path)} {item_id}")
    written = export.export_item(api, resource, item, md_path, force=force)
    print(paint(g("dot"), "ready") + " " + paint(f"saved {written}", "muted"), file=sys.stderr)


def cmd_login(api_url: str, username: str | None, password: str | None, ctx, remember: bool = True):
    import click
    import httpx

    from taigacli import api as api_mod
    from taigacli.config import load_env

    client = httpx.Client(base_url=api_url, follow_redirects=False)
    if not _print_session(api_mod, client, api_url, username, ctx):
        return
    if username is None:
        default = load_env().get("TAIGA_USERNAME")
        username = click.prompt("Username", default=default, show_default=bool(default))
    if password is None:
        password = click.prompt("Password", hide_input=True)
    token = api_mod.login(api_url, username, password, client)
    remembered = remember and credentials.save(api_url, username, password)
    me = _me(api_mod, client, token, api_url)
    user = me if isinstance(me, dict) else {}
    if is_json(ctx):
        print(json.dumps({"already_logged_in": False, "user": user, "remembered": remembered}))
        return
    name = user.get("full_name") or user.get("username") or username
    print()
    print(GUTTER + paint(g("dot"), "ready") + " " + paint(str(name), "ink", bold=True))
    if remembered:
        print(GUTTER + paint("logged in - token saved - remembered via OS keyring", "muted"))
    else:
        print(GUTTER + paint("logged in - token saved", "muted"))
        if remember:
            print(GUTTER + paint(
                "keyring unavailable; you will be asked to log in again when the token expires",
                "muted",
            ))
    print()


def _me(api_mod, client, token: str, api_url: str):
    try:
        return api_mod.request({"api_url": api_url}, client, token, "GET", "users/me")
    except CliError:
        return None


def _print_session(api_mod, client, api_url: str, username: str | None, ctx) -> bool:
    """Verify any cached session; True means a fresh login should proceed.

    A 401 clears the token inside request(), so a stale session re-logins.
    Explicit credentials are ignored while a valid session exists: switching
    users always goes through `taiga logout` first.
    """
    token = api_mod.load_token()
    if not token:
        return True
    me = _me(api_mod, client, token, api_url)
    if not isinstance(me, dict):
        return True
    if is_json(ctx):
        print(json.dumps({"already_logged_in": True, "user": me}))
        return False
    name = me.get("full_name") or me.get("username") or "?"
    print()
    print(GUTTER + paint(g("dot"), "ready") + " " + paint(str(name), "ink", bold=True))
    print(GUTTER + paint("already logged in - run `taiga logout` first to sign in as another user", "muted"))
    print()
    return False


def cmd_logout(ctx):
    from taigacli import api as api_mod
    from taigacli.api import clear_token
    from taigacli.config import api_url, token_file

    path = token_file()
    remembered_removed = credentials.forget(api_url())
    if clear_token():
        if is_json(ctx):
            print(json.dumps({"logged_out": True, "token_file": str(path), "remembered_removed": remembered_removed}))
            return
        print(GUTTER + paint(f"removed {path}", "muted"))
        if remembered_removed:
            print(GUTTER + paint("forgot the remembered login", "muted"))
    else:
        if is_json(ctx):
            print(json.dumps({"logged_out": False, "token_file": str(path), "remembered_removed": remembered_removed}))
            return
        if remembered_removed:
            print(GUTTER + paint("forgot the remembered login", "muted"))
        else:
            print(GUTTER + paint("not logged in", "muted"))


def new_status_name(status: dict) -> str:
    return str(status.get("name", ""))


def is_json(ctx) -> bool:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    return bool(obj.get("json"))


def is_plain(ctx) -> bool:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    return bool(obj.get("plain"))
