"""Messages to Iris (or any ntfy-compatible address): the weekly summary and the streak reminder."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

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


def streak_tasks(s: dict, now: datetime, after_hour: int, lang: str = "en") -> list[dict]:
    """The same condition as the reminder, as an Iris task: open while the streak is at risk,
    gone (closed by itself) once today has a commit or the day is over."""
    st = s["streak"]
    if st["today_done"] or st["current"] == 0 or now.hour < after_hour:
        return []
    n = st["current"]
    if lang == "tr":
        title = f"Bugün commit at: {n} günlük seri"
        action = "Bugün henüz commit yok. Gece yarısına kadar tek bir commit seriyi sürdürür."
    else:
        title = f"Commit today: {n}-day streak"
        action = "No commit yet today. One commit before midnight keeps the streak going."
    return [{"id": "streak", "title": title, "action": action, "priority": "high",
             "link": "http://127.0.0.1:8747/"}]


def iris_base(url: str) -> str:
    """http://127.0.0.1:8090/chronos -> http://127.0.0.1:8090"""
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def sync_tasks(url: str, items: list[dict], source: str = "chronos") -> dict:
    """PUT the whole list to Iris (raises urllib.error.HTTPError 404 on an Iris without tasks)."""
    if not url.startswith(LOOPBACK + ("https://",)):
        raise ValueError("send only to this machine (http://127.0.0.1) or over https")
    req = urllib.request.Request(iris_base(url) + f"/api/tasks/{source}", method="PUT",
                                 data=json.dumps({"tasks": items}).encode(),
                                 headers={"Content-Type": "application/json"})
    # The scheme is checked above.
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        return json.loads(resp.read() or b"{}")
