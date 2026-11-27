"""Terminal text and the SVG contribution heatmap."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from html import escape

from .stats import WEEKDAYS

# One hue, light -> dark (dark theme: dark -> light, its own steps). Level 0 = no commits.
LIGHT = ("#ebebeb", "#b6d5f8", "#6aabf1", "#257de0", "#0f4a96")
DARK = ("#2a2a2a", "#0f4a96", "#1b64be", "#338ced", "#84b9f3")
TERM = ("238", "153", "75", "33", "25")      # 256-colour approximations of LIGHT
BLOCKS = ("·", "░", "▒", "▓", "█")           # when colour is off
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def color_on(stream=sys.stdout) -> bool:
    return stream.isatty() and not os.environ.get("NO_COLOR")


def paint(text: str, code: str, on: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if on else text


def grid(first: date, last: date) -> list[list[date | None]]:
    """Weeks (columns, Monday first) covering first..last; days outside are None."""
    start = first - timedelta(days=first.weekday())
    weeks = []
    d = start
    while d <= last:
        weeks.append([d + timedelta(days=i) if first <= d + timedelta(days=i) <= last else None
                      for i in range(7)])
        d += timedelta(days=7)
    return weeks


def _day_levels(s: dict) -> dict[str, tuple[int, int]]:
    return {k: (v[0], v[1]) for k, v in s["days"].items()}


def heatmap_text(s: dict, color: bool) -> str:
    first, last = date.fromisoformat(s["range"]["from"]), date.fromisoformat(s["today"])
    weeks = grid(first, last)
    days = _day_levels(s)
    head = [" "] * (len(weeks) + 3)
    free = 0            # first column a new label may start at
    prev_month = None
    for i, week in enumerate(weeks):
        top = next(d for d in week if d)
        if top.month != prev_month:
            prev_month = top.month
            if i >= free and i + 3 <= len(weeks):
                head[i:i + 3] = MONTHS[top.month - 1]
                free = i + 4
    lines = ["   " + "".join(head).rstrip()]
    for row in range(7):
        label = WEEKDAYS[row][:2] + " " if row in (0, 2, 4) else "   "
        cells = []
        for week in weeks:
            d = week[row]
            if d is None:
                cells.append(" ")
                continue
            lv = days.get(d.isoformat(), (0, 0))[1]
            cells.append(paint("■", "38;5;" + TERM[lv], True) if color else BLOCKS[lv])
        lines.append(label + "".join(cells))
    legend = " ".join(paint("■", "38;5;" + t, True) for t in TERM) if color else " ".join(BLOCKS)
    lines.append(f"   less {legend} more")
    return "\n".join(lines)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def summary_text(s: dict, color: bool) -> str:
    t, st, w, lw = s["totals"], s["streak"], s["this_week"], s["last_week"]
    out = [paint(f"Chronos · last {s['range']['days']} days", "1", color),
           f"  {_plural(t['commits'], 'commit')} on {_plural(t['active_days'], 'day')} in "
           f"{_plural(t['repos'], 'project')} (+{t['added']:,} / -{t['deleted']:,} lines; "
           f"{s['repos_scanned']} repositories looked at)"]
    streak = f"  streak: {_plural(st['current'], 'day')}"
    if st["current"] and not st["today_done"]:
        streak += paint(" — nothing yet today, one commit keeps it going", "33", color)
    streak += f" · longest {_plural(st['longest'], 'day')}"
    if st["longest_from"]:
        streak += f" ({st['longest_from']} → {st['longest_to']})"
    out.append(streak)
    if s["busiest_day"]:
        out.append(f"  busiest day: {s['busiest_day']['date']} with {_plural(s['busiest_day']['commits'], 'commit')}")
    diff = w["commits"] - lw["commits"]
    arrow = "same as" if diff == 0 else (f"{diff} more than" if diff > 0 else f"{-diff} fewer than")
    out.append(f"  this week: {_plural(w['commits'], 'commit')} ({arrow} last week), "
               f"today: {_plural(s['today_commits'], 'commit')}")
    out.append("")
    out.append(heatmap_text(s, color))
    if s["repos"]:
        out.append("")
        width = max(len(r["repo"]) for r in s["repos"][:10])
        top = s["repos"][0]["commits"]
        for r in s["repos"][:10]:
            bar = "▇" * max(1, round(24 * r["commits"] / top))
            out.append(f"  {r['repo']:<{width}}  {paint(bar, '38;5;33', color)} {r['commits']}")
        if len(s["repos"]) > 10:
            rest = sum(r["commits"] for r in s["repos"][10:])
            out.append(f"  {'and ' + str(len(s['repos']) - 10) + ' more':<{width}}  {rest}")
    return "\n".join(out)


def week_text(s: dict, color: bool) -> str:
    w, lw = s["this_week"], s["last_week"]
    out = [paint(f"Chronos · week of {w['from']}", "1", color),
           f"  {_plural(w['commits'], 'commit')} on {_plural(w['active_days'], 'day')} in "
           f"{_plural(w['repos'], 'project')} (+{w['added']:,} / -{w['deleted']:,} lines)",
           f"  last week: {_plural(lw['commits'], 'commit')} on {_plural(lw['active_days'], 'day')}",
           f"  streak: {_plural(s['streak']['current'], 'day')}"]
    for r in w["top"]:
        out.append(f"    {r['repo']}: {r['commits']}")
    return "\n".join(out)


def heatmap_svg(s: dict, title: str = "Commits") -> str:
    """A self-contained SVG (light and dark) with no project names: safe for a public README."""
    first, last = date.fromisoformat(s["range"]["from"]), date.fromisoformat(s["today"])
    weeks = grid(first, last)
    days = _day_levels(s)
    cell, gap, left, top = 11, 3, 32, 34
    pitch = cell + gap
    width = left + len(weeks) * pitch + 8
    height = top + 7 * pitch + 30
    t = s["totals"]
    css_l = "".join(f".l{i}{{fill:{c}}}" for i, c in enumerate(LIGHT))
    css_d = "".join(f".l{i}{{fill:{c}}}" for i, c in enumerate(DARK))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}: '
        f'{t["commits"]} commits on {t["active_days"]} days">',
        "<style>text{font:11px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:#555}"
        f".h{{font-size:13px;font-weight:600;fill:#222}}{css_l}"
        f"@media (prefers-color-scheme:dark){{text{{fill:#a8a8a8}}.h{{fill:#eee}}{css_d}}}</style>",
        f'<text class="h" x="{left}" y="16">{escape(title)}: {t["commits"]:,} commits on '
        f'{t["active_days"]} days · longest streak {s["streak"]["longest"]} days</text>',
    ]
    prev_month, free = None, 0
    for i, week in enumerate(weeks):
        topday = next(d for d in week if d)
        if topday.month != prev_month:
            prev_month = topday.month
            if i >= free and i < len(weeks) - 2:     # never two labels on top of each other
                parts.append(f'<text x="{left + i * pitch}" y="{top - 6}">{MONTHS[topday.month - 1]}</text>')
                free = i + 3
    for row in (0, 2, 4):
        parts.append(f'<text x="2" y="{top + row * pitch + cell - 1}">{WEEKDAYS[row]}</text>')
    for i, week in enumerate(weeks):
        for row, d in enumerate(week):
            if d is None:
                continue
            n, lv = days.get(d.isoformat(), (0, 0))
            parts.append(f'<rect class="l{lv}" x="{left + i * pitch}" y="{top + row * pitch}" '
                         f'width="{cell}" height="{cell}" rx="2"><title>{d.isoformat()}: '
                         f'{n} commit{"" if n == 1 else "s"}</title></rect>')
    ly = top + 7 * pitch + 12
    lx = width - 8 - 5 * pitch - 64
    parts.append(f'<text x="{lx}" y="{ly + cell - 1}">Less</text>')
    for i in range(5):
        parts.append(f'<rect class="l{i}" x="{lx + 30 + i * pitch}" y="{ly}" width="{cell}" height="{cell}" rx="2"/>')
    parts.append(f'<text x="{lx + 34 + 5 * pitch}" y="{ly + cell - 1}">More</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
