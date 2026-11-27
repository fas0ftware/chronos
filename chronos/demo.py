"""Made-up commits for screenshots and trying it out (--demo). Same every run.

random (not secrets) on purpose: the demo must be identical every time."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from .scan import Commit

PROJECTS = ("cerberus", "olympos", "janus", "mnemosyne", "lynceus", "iris", "themis",
            "hestia", "charon", "aegis", "pythia", "maze", "ariadne")
SUBJECTS = ("Fix a typo in the README", "Tests for the new parser", "Faster scan of large folders",
            "Dark theme for the page", "Escape names in notifications", "Version 0.{n}.0",
            "Retry when the network is down", "Screenshots with demo data", "Deps: update within semver",
            "Explain the settings in the README", "Smaller memory use while reading logs",
            "CI: newer actions")


def commits(now: datetime, days: int = 366) -> list[Commit]:
    rnd = random.Random(7)  # nosec B311
    tz = now.tzinfo
    out = []
    today = now.date()
    weights = [1.0 + i / 4 for i in range(len(PROJECTS))][::-1]
    for back in range(days, -1, -1):
        day = today - timedelta(days=back)
        busy = 0.55 if day.weekday() < 5 else 0.35
        if back < 120:
            busy += 0.25          # a busier last few months
        if rnd.random() > busy:
            continue
        for _ in range(rnd.choice((1, 1, 2, 2, 3, 4, 6, 9))):
            hour = rnd.choice((10, 11, 14, 15, 16, 17, 20, 21, 22, 23))
            when = datetime.combine(day, time(hour, rnd.randrange(60)), tz)
            if when > now:
                continue
            project = rnd.choices(PROJECTS, weights)[0]
            subject = rnd.choice(SUBJECTS).replace("{n}", str(rnd.randrange(2, 12)))
            out.append(Commit(project, f"{rnd.getrandbits(160):040x}", when, subject,
                              rnd.randrange(1, 260), rnd.randrange(0, 90)))
    out.sort(key=lambda c: c.time)
    return out
