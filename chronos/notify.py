"""Messages to Iris (or any ntfy-compatible address): the weekly summary and the streak reminder."""

from __future__ import annotations

import urllib.request
from datetime import datetime

LOOPBACK = ("http://127.0.0.1", "http://localhost", "http://[::1]")


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def weekly_message(s: dict) -> tuple[str, str]:
    w = s["last_week"]   # sent on Monday morning: "last week" is the finished one
    title = f"Chronos: {w['commits']} commits last week"
    lines = [f"{w['commits']} commits on {w['active_days']} days in {w['repos']} projects "
             f"(+{w['added']:,} / -{w['deleted']:,} lines).",
             f"Streak: {_days(s['streak']['current'])} (longest {_days(s['streak']['longest'])})."]
    if w["top"]:
        lines.append("Most: " + ", ".join(f"{r['repo']} {r['commits']}" for r in w["top"][:3]) + ".")
    return title, "\n".join(lines)


def reminder(s: dict, now: datetime, after_hour: int) -> tuple[str, str] | None:
    """Only when a streak is running, today is still empty and it is late enough."""
    st = s["streak"]
    if st["today_done"] or st["current"] == 0 or now.hour < after_hour:
        return None
    return (f"Chronos: {st['current']}-day streak",
            f"No commit yet today. One commit before midnight keeps the {st['current']}-day streak going.")


def send(url: str, title: str, body: str, priority: str = "default", tags: str = "calendar") -> None:
    if not url.startswith(LOOPBACK + ("https://",)):
        raise ValueError("send only to this machine (http://127.0.0.1) or over https")
    # Header values must be latin-1: keep titles ASCII-safe.
    safe_title = title.encode("ascii", "replace").decode()
    req = urllib.request.Request(url, data=body.encode(), method="POST",
                                 headers={"Title": safe_title, "Priority": priority, "Tags": tags})
    # The scheme is checked above, so urlopen cannot be pointed at file:// or similar.
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        resp.read()
