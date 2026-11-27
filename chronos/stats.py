"""Turn a list of commits into days, streaks and totals."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo

from .scan import Commit

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def local_day(c: Commit, tz: tzinfo | None) -> date:
    return c.time.astimezone(tz).date()


def per_day(commits: list[Commit], tz: tzinfo | None = None) -> Counter:
    return Counter(local_day(c, tz) for c in commits)


def streaks(days: Counter, today: date) -> dict:
    """Current streak (today may still be empty) and the longest one ever seen."""
    current = 0
    d = today if days.get(today) else today - timedelta(days=1)
    while days.get(d):
        current += 1
        d -= timedelta(days=1)
    longest, start, end = 0, None, None
    run, run_start, prev = 0, None, None
    for d in sorted(k for k, v in days.items() if v):
        if prev is not None and d == prev + timedelta(days=1):
            run += 1
        else:
            run, run_start = 1, d
        if run > longest:
            longest, start, end = run, run_start, d
        prev = d
    return {"current": current, "today_done": bool(days.get(today)), "longest": longest,
            "longest_from": start.isoformat() if start else None,
            "longest_to": end.isoformat() if end else None}


def levels(days: Counter) -> dict[date, int]:
    """0 for no commits, 1-4 by quarters of the busy days (like a contribution graph)."""
    counts = sorted(v for v in days.values() if v)
    if not counts:
        return {}
    cuts = [counts[min(len(counts) - 1, int(len(counts) * q))] for q in (0.25, 0.5, 0.75)]

    def level(n: int) -> int:
        if n <= 0:
            return 0
        return 1 + sum(n > c for c in cuts)

    return {d: level(n) for d, n in days.items()}


def by_repo(commits: list[Commit], tz: tzinfo | None = None) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: {"commits": 0, "added": 0, "deleted": 0, "days": set(),
                                                  "last": None})
    for c in commits:
        r = rows[c.repo]
        r["commits"] += 1
        r["added"] += c.added
        r["deleted"] += c.deleted
        r["days"].add(local_day(c, tz))
        if r["last"] is None or c.time > r["last"]:
            r["last"] = c.time
    out = [{"repo": name, "commits": r["commits"], "added": r["added"], "deleted": r["deleted"],
            "active_days": len(r["days"]), "last": r["last"].isoformat()} for name, r in rows.items()]
    out.sort(key=lambda r: (-r["commits"], r["repo"].lower()))
    return out


def window(commits: list[Commit], start: date, end: date, tz: tzinfo | None = None) -> list[Commit]:
    """Commits whose local day is in [start, end]."""
    return [c for c in commits if start <= local_day(c, tz) <= end]


def period(commits: list[Commit], start: date, end: date, tz: tzinfo | None = None) -> dict:
    sel = window(commits, start, end, tz)
    days = per_day(sel, tz)
    return {"from": start.isoformat(), "to": end.isoformat(), "commits": len(sel),
            "active_days": len(days), "repos": len({c.repo for c in sel}),
            "added": sum(c.added for c in sel), "deleted": sum(c.deleted for c in sel),
            "top": by_repo(sel, tz)[:5]}


def summarize(commits: list[Commit], now: datetime, days: int = 365, repos_scanned: int = 0,
              tz: tzinfo | None = None, recent: int = 30) -> dict:
    """Everything the terminal, the page and the JSON output show."""
    tz = tz or now.tzinfo
    today = now.astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    sel = sorted(window(commits, first, today, tz), key=lambda c: c.time)
    daily = per_day(sel, tz)
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    hours = Counter(c.time.astimezone(tz).hour for c in sel)
    weekdays = Counter(c.time.astimezone(tz).weekday() for c in sel)
    busiest = max(daily.items(), key=lambda kv: (kv[1], kv[0]), default=None)
    lv = levels(daily)
    return {
        "today": today.isoformat(),
        "range": {"from": first.isoformat(), "to": today.isoformat(), "days": days},
        "repos_scanned": repos_scanned,
        "totals": {"commits": len(sel), "active_days": len(daily), "repos": len({c.repo for c in sel}),
                   "added": sum(c.added for c in sel), "deleted": sum(c.deleted for c in sel)},
        "streak": streaks(daily, today),
        "busiest_day": {"date": busiest[0].isoformat(), "commits": busiest[1]} if busiest else None,
        "today_commits": daily.get(today, 0),
        "this_week": period(sel, week_start, today, tz),
        "last_week": period(sel, last_week_start, week_start - timedelta(days=1), tz),
        "hours": [hours.get(h, 0) for h in range(24)],
        "weekdays": [weekdays.get(w, 0) for w in range(7)],
        "days": {d.isoformat(): [n, lv.get(d, 0)] for d, n in sorted(daily.items())},
        "repos": by_repo(sel, tz),
        "recent": [{"repo": c.repo, "time": c.time.isoformat(), "subject": c.subject,
                    "added": c.added, "deleted": c.deleted} for c in reversed(sel[-recent:])],
    }
