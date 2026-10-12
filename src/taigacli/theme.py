from __future__ import annotations

import os
import shutil
import sys
from taigacli.errors import CliError

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
    "mark": ("\u25b2", "^"),
    "dot": ("\u25cf", "*"),
    "rule": ("\u2500", "-"),
    "block": ("\u2588", "#"),
    "slice": ("\u2014", "-"),
    "ellipsis": ("\u2026", ".."),
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


def fail(msg: str):
    raise CliError(msg)
