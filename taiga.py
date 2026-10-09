#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
import stat
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
TOKEN_FILE = HERE / ".token"


# --- ui: design tokens ---------------------------------------------------

GUTTER = "  "

HUES = {
    "ink": "#E6EDF3",
    "muted": "#7D8590",
    "accent": "#8B9DFF",
    "new": "#79C0FF",
    "ready": "#4DD4AC",
    "active": "#E3B341",
    "review": "#BC8CFF",
    "done": "#56D364",
    "danger": "#FF7B72",
}

STATUS_RULES = (
    ("block", "danger"),
    ("stuck", "danger"),
    ("done", "done"),
    ("closed", "done"),
    ("resolved", "done"),
    ("complete", "done"),
    ("not a bug", "done"),
    ("review", "review"),
    ("test", "review"),
    ("qa", "review"),
    ("info", "active"),
    ("question", "active"),
    ("reopen", "active"),
    ("progress", "active"),
    ("doing", "active"),
    ("active", "active"),
    ("dev", "active"),
    ("postpon", "muted"),
    ("archive", "muted"),
    ("ready", "ready"),
    ("new", "new"),
)

STATUS_ORDER = ("new", "ready", "active", "review", "done")

GLYPHS = {
    "mark": ("▲", "^"),
    "dot": ("●", "*"),
    "rule": ("─", "-"),
    "block": ("█", "#"),
    "slice": ("—", "-"),
    "ellipsis": ("…", ".."),
}

_STATE = {"color": False, "truecolor": False, "ascii": False, "width": 80}


def ui_init(plain: bool = False) -> None:
    env = os.environ
    out_tty = sys.stdout.isatty()
    term = env.get("TERM", "")
    forced = env.get("TAIGA_COLOR", "").lower() in ("1", "true", "force")
    color = not plain and not env.get("NO_COLOR") and (out_tty or forced) and term != "dumb"
    truecolor = color and env.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    enc = (sys.stdout.encoding or "").upper()
    _STATE.update(color=color, truecolor=truecolor, width=_term_width())
    _STATE["ascii"] = bool(plain) or term == "dumb" or "UTF" not in enc


def _term_width() -> int:
    try:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except (OSError, ValueError):
        cols = 80
    return min(max(cols, 40), 110)


def _hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _x256(rgb: tuple[int, int, int]) -> int:
    cube = [0, 95, 135, 175, 215, 255]
    palette = [
        (16 + 36 * r + 6 * g + b, (cube[r], cube[g], cube[b]))
        for r in range(6)
        for g in range(6)
        for b in range(6)
    ]
    palette += [(232 + n, (8 + n * 10,) * 3) for n in range(24)]
    r, g, b = rgb
    best_i, best_d = 0, 1 << 30
    for i, (cr, cg, cb) in palette:
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def paint(text: str, hue: str | None = None, *, bold: bool = False, dim: bool = False, italic: bool = False) -> str:
    if not _STATE["color"]:
        return text
    codes = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if italic:
        codes.append("3")
    if hue and hue in HUES:
        r, g, b = _hex_rgb(HUES[hue])
        if _STATE["truecolor"]:
            codes.append(f"38;2;{r};{g};{b}")
        else:
            codes.append(f"38;5;{_x256((r, g, b))}")
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"


def g(key: str) -> str:
    return GLYPHS[key][1] if _STATE["ascii"] else GLYPHS[key][0]


def status_hue(name: str) -> str:
    n = (name or "").lower()
    for needle, hue in STATUS_RULES:
        if needle in n:
            return hue
    return "accent"


def status_cell(name: str, width: int = 0) -> str:
    if not name:
        return pad_left("", width)
    raw = f"{g('dot')} {name}"
    return paint(pad_left(raw, width), status_hue(name))


def squeeze(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    mark = g("ellipsis")
    if width <= len(mark):
        return text[:width]
    return text[: width - len(mark)] + mark


def pad_right(text: str, width: int) -> str:
    return text.ljust(width)


def pad_left(text: str, width: int) -> str:
    return text.rjust(width) if width > 0 else text


def counter(text: str) -> str:
    num, _, rest = text.partition(" ")
    out = paint(num, "accent", bold=True)
    if rest:
        out += paint(" " + rest, "muted")
    return out


def eyebrow(label: str, right: str = "") -> str:
    w = _STATE["width"]
    line = GUTTER + paint(label, "accent", bold=True)
    right_styled = counter(right) if right else ""
    fill = w - len(GUTTER) - len(label) - (len(right) + 1 if right else 0) - 2
    if fill >= 3:
        line += " " + paint(g("rule") * fill, "muted")
    if right_styled:
        line += " " + right_styled
    return line


def header_line(left_label: str = "", right_text: str = "") -> str:
    w = _STATE["width"]
    raw_left = f"{g('mark')} taiga" + (f" · {left_label}" if left_label else "")
    left = paint(g("mark"), "accent", bold=True) + " " + paint("taiga", "ink", bold=True)
    if left_label:
        left += paint(f" · {left_label}", "muted")
    raw_right = len(right_text)
    gap = w - len(GUTTER) - len(raw_left) - raw_right
    line = GUTTER + left
    if right_text:
        if gap >= 2:
            line += " " * gap + paint(right_text, "muted")
    return line


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


def render_rows(rows: list[dict], compact: bool = False, empty_text: str = "no results") -> str:
    if not rows:
        return GUTTER + paint(f"{g('slice')} {empty_text} {g('slice')}", "muted")
    w = _STATE["width"]
    use_sprint = not compact and any(r["sprint"] for r in rows)
    use_assignee = not compact and any(r["assignee"] for r in rows)
    use_status = any(r["status"] for r in rows)

    ref_w = max([4] + [len(f"#{r['ref']}") for r in rows])
    status_w = max([len(r["status"]) + 2 for r in rows if r["status"]], default=0)
    assignee_w = min(max([len(r["assignee"]) for r in rows], default=0), 18) if use_assignee else 0
    sprint_w = min(max([len(r["sprint"]) for r in rows], default=0), 20) if use_sprint else 0

    if not compact:
        if use_status:
            status_w = max(status_w, len("STATUS") + 2)
        if use_assignee:
            assignee_w = max(assignee_w, len("ASSIGNEE"))
        if use_sprint:
            sprint_w = max(sprint_w, len("SPRINT") + 2)

    left = len(GUTTER) + ref_w + 1
    right = 0
    if use_sprint:
        right += 2 + sprint_w
    if use_status:
        right += 1 + status_w
    if use_assignee:
        right += 2 + assignee_w
    subject_w = max(12, w - left - right)

    lines = []
    if not compact:
        hdr = GUTTER + paint(pad_right("REF", ref_w), "muted") + " " + paint("SUBJECT" if not (use_sprint or use_status) else pad_right("SUBJECT", subject_w), "muted")
        if use_sprint:
            hdr += "  " + paint(pad_right("SPRINT", sprint_w), "muted")
        if use_status:
            hdr += " " + paint(pad_left("STATUS", status_w), "muted")
        if use_assignee:
            hdr += "  " + paint(pad_left("ASSIGNEE", assignee_w), "muted")
        lines.append(hdr)

    for r in rows:
        ref_raw = "#" + squeeze(r["ref"], ref_w - 1)
        line = GUTTER + paint(pad_right(ref_raw, ref_w), "accent") + " "
        subj_raw = squeeze(r["subject"], subject_w)
        if use_sprint or use_status:
            line += paint(pad_right(subj_raw, subject_w), "ink")
        else:
            line += paint(subj_raw, "ink")
        if use_sprint:
            line += "  " + paint(pad_right(squeeze(r["sprint"], sprint_w), sprint_w), "muted")
        if use_status:
            line += " " + status_cell(r["status"], status_w)
        if use_assignee:
            line += "  " + paint(pad_left(squeeze(r["assignee"], assignee_w), assignee_w), "muted")
        lines.append(line)
    return "\n".join(lines)


def render_timeline(items: list) -> str:
    lines = []
    w = _STATE["width"]
    for item in items if isinstance(items, list) else [items]:
        d = item.get("data", {})
        obj = d.get("userstory") or d.get("task") or d.get("issue") or d.get("epic") or {}
        who = (d.get("user", {}) or {}).get("name", "")
        ev = (item.get("event_type", "").split(".") or [""])[-1]
        created = str(item.get("created", ""))[:19].replace("T", " ")
        ref = str(obj.get("ref", ""))
        subject = str(obj.get("subject", ""))
        comment = str(d.get("comment", ""))

        head = squeeze(created, 19) + "  " + ev
        who_raw = f"  · {who}" if who else ""
        raw_ref = "#" + ref
        subject_w = max(12, w - len(GUTTER) - len(head) - len(raw_ref) - len(who_raw) - 2)
        line = GUTTER + paint(head, "muted") + " " + paint(raw_ref, "accent")
        line += " " + paint(pad_right(squeeze(subject, subject_w), subject_w), "ink")
        line += paint(who_raw, "muted")
        if comment:
            used = len(GUTTER) + len(head) + 1 + len(raw_ref) + 1 + subject_w + len(who_raw)
            room = w - used - 4
            if room >= 10:
                line += paint(f'  "{squeeze(comment, room)}"', "muted", italic=True)
        lines.append(line)
    return "\n".join(lines)


def render_members(items: list) -> str:
    lines = []
    for item in items if isinstance(items, list) else [items]:
        name = item.get("full_name", item.get("id"))
        role = item.get("role_name", "-")
        line = GUTTER + paint(str(name), "ink") + "  " + paint(str(role), "muted")
        if item.get("is_admin"):
            line += " " + paint("admin", "accent")
        if item.get("is_user_active") is False:
            line += " " + paint("inactive", "danger")
        lines.append(line)
    return "\n".join(lines)


def show_summary(data, resource: str) -> None:
    if isinstance(data, dict):
        data = [data]
    if not data:
        print(GUTTER + paint(g("slice") + " no results " + g("slice"), "muted"))
        return
    if resource == "timeline":
        print(render_timeline(data))
        return
    if resource in ("members", "memberships"):
        print(render_members(data))
        return
    rows = [_norm_item(item) for item in data if isinstance(item, dict)]
    print(render_rows(rows))


def _merge_counts(groups: dict[str, list]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for rows in groups.values():
        for r in rows:
            if r["status"]:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
    ordered = [s for s in STATUS_ORDER if s in counts]
    ordered += sorted(s for s in counts if s not in ordered)
    return [(s, counts[s]) for s in ordered]


def ribbon(counts: list[tuple[str, int]]) -> str:
    if not counts:
        return ""
    w = _STATE["width"]
    dot_ch = g("dot")
    raw_legend = "   ".join(f"{dot_ch} {status} {count}" for status, count in counts)
    legend = "   ".join(
        paint(dot_ch, status_hue(status)) + paint(f" {status} {count}", "ink") for status, count in counts
    )
    bar_budget = w - len(GUTTER) - len(raw_legend) - 2
    single = bar_budget >= 16
    bar_w = bar_budget if single else max(20, w - len(GUTTER))
    total = sum(c for _, c in counts)
    cells = [max(1, int(round(c / total * bar_w))) for c in (count for _, count in counts)]
    while sum(cells) > bar_w:
        cells[cells.index(max(cells))] -= 1
    while sum(cells) < bar_w:
        cells[cells.index(max(cells))] += 1
    bar = "".join(paint(g("block") * n, status_hue(status)) for (status, _), n in zip(counts, cells))
    if single:
        return GUTTER + bar + "  " + legend
    return GUTTER + bar + "\n" + GUTTER + legend


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip()


def kv_rows(pairs: list[tuple[str, str]], width: int) -> list[str]:
    out = []
    if not pairs:
        return out
    lab_w = min(12, max(len(label) for label, _ in pairs))
    indent = " " * (len(GUTTER) + lab_w + 3)
    usable = max(16, width - len(indent))
    for label, value in pairs:
        wrapped = textwrap.fill(str(value), width=usable, subsequent_indent=indent)
        head = GUTTER + paint(label.upper().ljust(lab_w + 3), "muted") + paint(wrapped.splitlines()[0], "ink")
        out.append(head)
        out.extend(paint(ln, "ink") for ln in wrapped.splitlines()[1:])
    return out


def description_block(text: str, width: int) -> list[str]:
    if not text:
        return []
    plain = strip_html(str(text))
    if not plain:
        return []
    lab_w = 12
    indent = " " * (len(GUTTER) + lab_w + 3)
    usable = max(16, width - len(indent))
    lines_plain = textwrap.wrap(re.sub(r"\s+", " ", plain), width=usable)
    cap = 8
    remaining = len(plain) - sum(len(ln) for ln in lines_plain[:cap])
    out = [GUTTER + paint("DESCRIPTION".ljust(lab_w + 3), "muted") + paint(lines_plain[0], "ink")]
    out.extend(paint(indent + ln, "ink") for ln in lines_plain[1:cap])
    if remaining > 0:
        out.append(indent + paint(f'{g("ellipsis")} +{remaining} characters', "muted"))
    return out


def render_record(item: dict, label: str) -> str:
    w = _STATE["width"]
    n = _norm_item(item)
    ref = n["ref"] if item.get("ref") else ""
    out = [header_line(label, f"#{ref}" if ref else ""), ""]
    heading = n["subject"] or ref or "?"
    out.append(GUTTER + paint(squeeze(heading, w - 4), "ink", bold=True))
    if n["status"]:
        out.append("")
        out.append(GUTTER + status_cell(n["status"]))
    pairs = []
    if n["assignee"]:
        pairs.append(("assigned", n["assignee"]))
    sprint = item.get("milestone_name")
    if sprint:
        pairs.append(("sprint", str(sprint)))
    tags = item.get("tags")
    if tags:
        pairs.append(("tags", ", ".join(str(t) for t in tags)))
    if item.get("created_date"):
        pairs.append(("created", str(item["created_date"])[:10]))
    if item.get("id"):
        pairs.append(("id", str(item["id"])))
    if pairs:
        out.append("")
        out.extend(kv_rows(pairs, w))
    out.append("")
    out.extend(description_block(item.get("description"), w))
    return "\n".join(out)


def fail(msg: str) -> None:
    print(paint(g("dot"), "danger") + " " + paint(msg, "danger"), file=sys.stderr)
    sys.exit(1)


# --- taiga api ------------------------------------------------------------


def load_env() -> dict:
    if not ENV_FILE.exists():
        fail(f"Missing env file: {ENV_FILE}")
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def config() -> dict:
    env = os.environ
    cfg = load_env()
    out = {
        "api_url": env.get("TAIGA_API_URL") or cfg.get("TAIGA_API_URL", "https://api.taiga.io/api/v1").rstrip("/"),
        "username": env.get("TAIGA_USERNAME") or cfg.get("TAIGA_USERNAME"),
        "password": env.get("TAIGA_PASSWORD") or cfg.get("TAIGA_PASSWORD"),
        "slug": env.get("TAIGA_PROJECT_SLUG") or cfg.get("TAIGA_PROJECT_SLUG"),
    }
    missing = [k for k in ("username", "password", "slug") if not out[k] or "your_taiga" in out[k]]
    if missing:
        fail(f"Missing config keys: {', '.join(missing)} - edit {ENV_FILE}")
    return out


def secure(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def login(cfg: dict) -> str:
    print(paint("Authenticating to Taiga...", "muted"), file=sys.stderr)
    payload = json.dumps({"type": "normal", "username": cfg["username"], "password": cfg["password"]}).encode()
    req = urllib.request.Request(
        f"{cfg['api_url']}/auth",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            token = json.load(res).get("auth_token")
    except urllib.error.HTTPError as e:
        fail(f"Auth failed ({e.code}): {e.read().decode(errors='replace')}")
    if not token:
        fail("Auth succeeded but no auth_token returned")
    TOKEN_FILE.write_text(token)
    secure(TOKEN_FILE)
    return token


def get_token(cfg: dict, refresh: bool = False) -> str:
    if not refresh and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    return login(cfg)


def http(cfg: dict, method: str, path: str, token: str, params: dict | None = None, body: dict | None = None, soft: bool = False, retry: bool = True):
    url = path if path.startswith("http") else f"{cfg['api_url']}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            resp_body = res.read().decode()
            next_link = res.headers.get("x-next") or res.headers.get("X-Next")
    except urllib.error.HTTPError as e:
        if e.code == 404 and soft:
            return None
        if e.code == 401 and retry:
            token = get_token(cfg, refresh=True)
            return http(cfg, method, path, token, params, body, soft, retry=False)
        fail(f"API error {e.code} on {path}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        fail(f"Connection error: {e.reason}")
    resp = json.loads(resp_body) if resp_body else None
    if next_link and url != next_link:
        more = http(cfg, method, next_link, token, retry=False)
        if isinstance(resp, list) and isinstance(more, list):
            resp.extend(more)
    return resp


def by_ref(cfg, token: str, path: str, ref: int, soft: bool = False) -> dict:
    item = http(cfg, "GET", f"{path}/by_ref", token, params={"ref": ref, "project": project_id(cfg, token)}, soft=soft)
    if item is None and soft:
        return None
    if isinstance(item, list):
        if not item:
            if soft:
                return None
            fail(f"Not found: {path} ref {ref}")
        item = item[0]
    else:
        if item is None and soft:
            return None
        if item is None:
            fail(f"Not found: {path} ref {ref}")
    return item


def project(cfg: dict, token: str) -> dict:
    proj = http(cfg, "GET", "projects/by_slug", token, params={"slug": cfg["slug"]})
    if isinstance(proj, dict) and proj.get("id"):
        return proj
    fail(f"Could not resolve project by slug '{cfg['slug']}': {proj}")


def project_id(cfg: dict, token: str) -> int:
    return project(cfg, token)["id"]


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


def load_statuses(cfg, token: str, project_id_val: int, resource: str) -> list[dict]:
    kinds = STATUS_KINDS.get(resource)
    if not kinds:
        fail(f"No statuses for resource '{resource}' - choose from: userstories, tasks, issues")
    data = http(cfg, "GET", kinds, token, params={"project": project_id_val}) or []
    return sorted(data, key=lambda s: (s.get("order") or 0, s.get("id") or 0))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def match_status(options: list[dict], flag_token: str, status_opt: str | None, want_id: int | None) -> dict | None:
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
    if want_id is not None:
        for option in options:
            if option.get("id") == want_id:
                return option
    if not flag_token:
        return None
    token = normalize_name(flag_token)
    for option in options:
        if normalize_name(option.get("name", "")) == token or (option.get("slug") or "").lower() == token:
            return option
    return None


def render_status_menu(label: str, ref: int, subject: str, current: dict | None, options: list[dict]) -> str:
    w = _STATE["width"]
    current_name = (current or {}).get("name", "")
    out = [header_line(label, f"#{ref}" if ref else ""), ""]
    if subject:
        out.append(GUTTER + paint(squeeze(subject, w - 4), "ink", bold=True))
    if current:
        out.append(GUTTER + paint("now ", "muted") + status_cell(current_name))
        out.append("")
        out.append(GUTTER + paint("choose a status:", "muted"))
    else:
        out.append("")
        out.append(GUTTER + paint("choose a status:", "muted"))
    flag_w = max([10] + [len("--" + normalize_name(o["name"])) for o in options])
    for option in options:
        name = option.get("name", "")
        hue = status_hue(name)
        flag = paint("--" + normalize_name(name), "ink", bold=True)
        marker = ""
        if current_name and name.lower() == current_name.lower():
            marker = paint("  ←" if not _STATE["ascii"] else "  <-", "accent")
            marker += paint(" current", "accent")
        elif option.get("is_closed"):
            marker = paint("  closed", "muted")
        line = GUTTER + paint(pad_right("--" + normalize_name(name), flag_w), "accent", bold=True)
        line += "  " + paint(name, hue) + marker
        out.append(line)
    if current_name and not any(o.get("name", "").lower() == current_name.lower() for o in options):
        out.append(GUTTER + paint("(!) current status not in list", "danger"))
    return "\n".join(out)


def render_change(label: str, ref: int, subject: str, old: str, new: str, dry_run: bool) -> str:
    w = _STATE["width"]
    out = [header_line(label, f"#{ref}" if ref else ""), ""]
    if subject:
        out.append(GUTTER + paint(squeeze(subject, w - 4), "ink", bold=True))
        out.append("")
    arrow = "→" if not _STATE["ascii"] else "->"
    out.append(GUTTER + status_cell(old) + paint(f"  {arrow}  ", "muted") + status_cell(new))
    if dry_run:
        out.append("")
        out.append(GUTTER + paint("dry run · not saved", "muted"))
    return "\n".join(out)


def cmd_set(cfg, token: str, args, extras: list[str]) -> None:
    tokens = list(getattr(args, "args", []) or [])
    flags = [e.lstrip("-") for e in extras if e.startswith("--")]
    stray = [e for e in extras if not e.startswith("--")]
    if stray:
        fail(f"Unrecognized arguments: {' '.join(stray)}")
    if len(flags) > 1:
        fail(f"Give exactly one status flag, got: {', '.join(flags)}")
    flag_token = flags[0] if flags else None
    status_opt = getattr(args, "status", None)
    if status_opt and flag_token:
        fail(f"Use --status or the status flag, not both ('--{flag_token}')")
    if len(tokens) > 2:
        fail(f"Too many arguments: {' '.join(tokens)} - use: set [resource] <ref> --<status>")

    resource_hint = None
    ref = None
    if len(tokens) == 1:
        if tokens[0].isdigit():
            ref = int(tokens[0])
        elif tokens[0] in SET_ALIASES:
            resource_hint = SET_ALIASES[tokens[0]]
        else:
            fail(f"Unknown resource '{tokens[0]}' - use one of: story, task, issue, or a ref number")
    elif len(tokens) == 2:
        if tokens[0].isdigit():
            fail(f"Unexpected '{tokens[1]}' after ref {tokens[0]} - the status goes after the ref: set {tokens[0]} --<status>")
        if tokens[0] not in SET_ALIASES:
            fail(f"Unknown resource '{tokens[0]}' - use one of: story, task, issue")
        if not tokens[1].isdigit():
            fail(f"Ref must be a number, got '{tokens[1]}'")
        resource_hint, ref = SET_ALIASES[tokens[0]], int(tokens[1])
    elif len(tokens) == 0 and flag_token is None and status_opt is None:
        fail("usage: set [resource] <ref> --<status>   e.g. set 1344 --in-review")

    pid = project_id(cfg, token)
    kinds = [resource_hint] if resource_hint else ["userstories", "tasks", "issues"]

    item = None
    resource = resource_hint
    if ref is not None:
        candidates = []
        for kind in kinds:
            found = by_ref(cfg, token, kind, ref, soft=True)
            if found:
                candidates.append((kind, found))
        if not candidates:
            plurals = {"userstories": "user stories", "tasks": "tasks", "issues": "issues"}
            wanted = ", ".join(plurals.get(k, k) for k in kinds)
            fail(f"Not found: no {wanted} with ref #{ref}")
        if len(candidates) > 1:
            if args.json:
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
            out.append(GUTTER + paint(f"prefix the resource: taiga.py set ({hint}) {ref} --<status>", "muted"))
            print("\n".join(out))
            return
        resource, item = candidates[0]
    if resource is None:
        fail("Tell me the resource to list statuses for: set story, set task, set issue")

    options = load_statuses(cfg, token, pid, resource)

    target_status = match_status(options, flag_token, status_opt, None)
    if target_status is None:
        if args.json:
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
        fail(f"Give a ref: set {resource} <ref> --{normalize_name(new_status_name(target_status))}")
        return

    n = _norm_item(item)
    current_name = n.get("status", "")
    new_name = new_status_name(target_status)
    if getattr(args, "dry_run", False) and args.json:
        print(json.dumps({"ref": item.get("ref"), "resource": resource, "from": current_name, "to": new_name}, indent=2))
        return
    if current_name.lower() == new_name.lower():
        print()
        print(GUTTER + paint(f"already {status_cell(current_name)}", "muted"))
        print()
        return
    if getattr(args, "dry_run", False):
        print(render_change(LABELS.get(resource, resource), item.get("ref"), n.get("subject", ""), current_name, new_name, True))
        return
    patch_body: dict = {"status": target_status["id"]}
    if item.get("version"):
        patch_body["version"] = item["version"]
    patched = http(cfg, "PATCH", f"{RESOURCES.get(resource, resource)}/{item['id']}", token, body=patch_body)
    if args.json:
        print(json.dumps(patched, indent=2))
        return
    changed = _norm_item(patched) if isinstance(patched, dict) else n
    print(render_change(LABELS.get(resource, resource), item.get("ref"), n.get("subject", ""), current_name, changed.get("status") or new_name, False))
    print()


def new_status_name(status: dict) -> str:
    return str(status.get("name", ""))


def cmd_list(cfg: dict, token: str, args):
    filters = {}
    for f in args.filter:
        k, _, v = f.partition("=")
        filters[k] = v
    if args.resource == "timeline":
        pid = project_id(cfg, token)
        data = http(cfg, "GET", f"timeline/project/{pid}", token)
    else:
        path = RESOURCES[args.resource]
        filters.setdefault("project", project_id(cfg, token))
        data = http(cfg, "GET", path, token, params=filters)
    if isinstance(data, list) and args.limit:
        data = data[: args.limit]
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if args.resource in ("userstories", "stories", "tasks", "issues", "epics", "milestones", "wiki"):
        count = len(data) if isinstance(data, list) else 0
        print(header_line(args.resource, f"{count} shown"))
        print()
    show_summary(data, args.resource)


def cmd_get(cfg: dict, token: str, args):
    path = RESOURCES.get(args.resource, args.resource)
    if path in ("userstories", "tasks", "issues"):
        item = by_ref(cfg, token, path, args.id)
        if args.json:
            print(json.dumps(item, indent=2))
        else:
            print(render_record(item, LABELS.get(path, path)))
        return
    data = http(cfg, "GET", f"{path}/{args.id}", token)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    if isinstance(data, dict):
        print(render_record(data, LABELS.get(path, path)))
    else:
        print(json.dumps(data, indent=2))


def cmd_mine(cfg: dict, token: str, args) -> None:
    proj = project(cfg, token)
    me = http(cfg, "GET", "users/me", token)
    uid = me.get("id")
    if not uid:
        fail("Could not resolve current user id")
    full_name = me.get("full_name") or me.get("username") or "?"
    groups = {"userstories": [], "tasks": [], "issues": []}
    for resource in groups:
        filters = {"project": proj["id"], "assigned_to": uid, "status__is_closed": "false"}
        data = http(cfg, "GET", RESOURCES[resource], token, params=filters)
        if isinstance(data, list) and args.limit:
            data = data[: args.limit]
        groups[resource] = data if isinstance(data, list) else ([] if data is None else [data])
    if args.json:
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


def cmd_help() -> None:
    resources = "epics stories userstories tasks issues milestones members wiki timeline"
    w = _STATE["width"]

    print(header_line("board client"))
    print()
    print(GUTTER + paint(f"config {ENV_FILE}  ·  token cache {TOKEN_FILE.name}", "muted"))

    def section(title: str) -> None:
        print()
        print(eyebrow(title))

    commands = [
        ("mine", "open user stories, tasks and issues assigned to you"),
        ("set <ref> --<status>", "change a status; bare set <ref> shows the options"),
        ("list <resource>", f"filterable list of {len(resources.split())} resources"),
        ("get <resource> <id>", "one item in full detail"),
        ("whoami", "the signed-in account"),
        ("project", "the resolved project"),
        ("help", "this page"),
    ]
    section("usage")
    print(GUTTER + paint("taiga.py", "ink", bold=True) + paint(" <command> [options]", "muted"))
    section("commands")
    name_w = max(len(name) for name, _ in commands)
    for name, desc in commands:
        wrapped = textwrap.wrap(desc, width=max(20, w - name_w - 8)) or [""]
        print(GUTTER + paint(pad_right(name, name_w), "ink", bold=True) + paint("  " + wrapped[0], "muted"))
        print("\n".join(GUTTER + " " * (name_w + 2) + paint(ln, "muted") for ln in wrapped[1:]))
    section("resources")
    print(GUTTER + paint(resources, "muted"))
    flags = [
        ("--filter k=v", "repeatable; keys: project, status, milestone, assigned_to, page_size"),
        ("--limit N", "cap the number of results"),
        ("--json", "raw JSON payload on stdout"),
        ("--plain", "no color, ASCII only; also honors NO_COLOR and non-tty output"),
        ("set: --dry-run", "preview the change"),
        ("set: --status NAME", "target status by name/slug/id instead of a flag"),
    ]
    section("flags")
    flag_w = max(len(flag) for flag, _ in flags)
    for flag, desc in flags:
        wrapped = textwrap.wrap(desc, width=max(20, w - flag_w - 8)) or [""]
        print(GUTTER + paint(pad_right(flag, flag_w), "ink", bold=True) + paint("  " + wrapped[0], "muted"))
        print("\n".join(GUTTER + " " * (flag_w + 2) + paint(ln, "muted") for ln in wrapped[1:]))
    section("examples")
    for ex in [
        "taiga.py mine",
        "taiga.py set 1344 --in-review",
        "taiga.py set 1344 --done --dry-run",
        "taiga.py list tasks --filter assigned_to=115",
        "taiga.py get userstories 1344",
        "taiga.py get issues 12 --json",
    ]:
        print(GUTTER + paint("$ ", "muted") + paint(ex, "ink"))
    print()
    print(GUTTER + paint("force color when piped: TAIGA_COLOR=1", "muted"))
    print()


def cmd_whoami(cfg: dict, token: str, args) -> None:
    user = http(cfg, "GET", "users/me", token)
    if args.json:
        print(json.dumps(user, indent=2))
        return
    full_name = user.get("full_name", user.get("username", "?"))
    line = paint(g("dot"), "ready") + " " + paint(str(full_name), "ink", bold=True)
    line += paint(f"  ·  id {user.get('id')}  ·  project {cfg['slug']}", "muted")
    print()
    print(line)
    print()


def cmd_project(cfg: dict, token: str, args) -> None:
    proj = http(cfg, "GET", "projects/by_slug", token, params={"slug": cfg["slug"]})
    if args.json:
        print(json.dumps(proj, indent=2))
        return
    line = paint(g("dot"), "ready") + " " + paint(str(proj.get("name", proj.get("slug", "?"))), "ink", bold=True)
    line += paint(f"  ·  id {proj.get('id')}  ·  slug {proj.get('slug')}", "muted")
    print()
    print(line)
    print()


def main() -> None:
    filtered = []
    global_json = global_plain = False
    for token in sys.argv[1:]:
        if token == "--json":
            global_json = True
        elif token == "--plain":
            global_plain = True
        else:
            filtered.append(token)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--json", action="store_true", help="raw JSON output")
    shared.add_argument("--plain", action="store_true", help="no color, ASCII only")
    parser = argparse.ArgumentParser(description="Taiga board client")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", parents=[shared])
    sub.add_parser("project", parents=[shared])

    p_list = sub.add_parser("list", parents=[shared], help="list a resource: epics stories tasks issues milestones members wiki timeline")
    p_list.add_argument("resource")
    p_list.add_argument("--limit", type=int, default=None)
    p_list.add_argument("--filter", action="append", default=[])

    p_get = sub.add_parser("get", parents=[shared], help="fetch single object")
    p_get.add_argument("resource")
    p_get.add_argument("id", type=int)

    p_mine = sub.add_parser("mine", parents=[shared], help="list open userstories/tasks/issues assigned to me")
    p_mine.add_argument("--limit", type=int, default=None)

    p_set = sub.add_parser("set", parents=[shared], allow_abbrev=False, help="change an item's status (e.g. set 1344 --in-review)")
    p_set.add_argument("args", nargs="*", metavar="[resource] <ref>")
    p_set.add_argument("--dry-run", action="store_true", help="show the change without saving")
    p_set.add_argument("--status", help="target status by name, slug or id (instead of a --flag)")

    sub.add_parser("help", parents=[shared], help="show available commands and usage")

    args, extras = parser.parse_known_args(filtered)
    args.json = args.json or global_json
    args.plain = args.plain or global_plain

    ui_init(plain=args.plain)

    if args.command != "set" and extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")

    if args.command == "help":
        cmd_help()
        return

    cfg = config()
    token = get_token(cfg)
    if args.command == "mine":
        cmd_mine(cfg, token, args)
    elif args.command == "whoami":
        cmd_whoami(cfg, token, args)
    elif args.command == "project":
        cmd_project(cfg, token, args)
    elif args.command == "list":
        cmd_list(cfg, token, args)
    elif args.command == "get":
        cmd_get(cfg, token, args)
    elif args.command == "set":
        cmd_set(cfg, token, args, extras)


if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
