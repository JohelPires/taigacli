from __future__ import annotations

import html
import re
import textwrap

from taigacli.errors import CliError
from taigacli.resources import LABELS, _norm_item, normalize_name
from taigacli.theme import (
    GUTTER,
    STATUS_ORDER,
    _STATE,
    g,
    paint,
    status_hue,
)


def status_cell(name: str, width: int = 0) -> str:
    if not name:
        return pad_left("", width)
    raw = f"{g('dot')} {name}"
    return paint(pad_left(raw, width), status_hue(name))


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


def pad_right(text: str, width: int) -> str:
    return text.ljust(width)


def pad_left(text: str, width: int) -> str:
    return text.rjust(width) if width > 0 else text


def squeeze(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    mark = g("ellipsis")
    if width <= len(mark):
        return text[:width]
    return text[: width - len(mark)] + mark


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
            marker = paint("  \u2190" if not _STATE["ascii"] else "  <-", "accent")
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
    arrow = "\u2192" if not _STATE["ascii"] else "->"
    out.append(GUTTER + status_cell(old) + paint(f"  {arrow}  ", "muted") + status_cell(new))
    if dry_run:
        out.append("")
        out.append(GUTTER + paint("dry run · not saved", "muted"))
    return "\n".join(out)
