"""python -m chronos [summary | week | json | svg | serve | weekly | remind]"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, config, notify, render, scan, stats


def build(settings: config.Settings | None, demo: bool, days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    if demo:
        from .demo import commits as demo_commits
        found, repos = demo_commits(now, days + 7), 13
    else:
        # A few extra days so "last week" is complete even for a 7-day range.
        found, repos = scan.collect(settings, max(days, 14) + 1, now)
    summary = stats.summarize(found, now, days, repos)
    summary["version"] = __version__
    summary["demo"] = demo
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="chronos", description="A diary of your commits across every local repository.")
    p.add_argument("--version", action="version", version=f"chronos {__version__}")
    p.add_argument("--config", type=Path, help="settings file (default: chronos.toml or ~/.config/chronos/config.toml)")
    p.add_argument("--demo", action="store_true", help="made-up commits instead of your repositories")
    p.add_argument("--days", type=int, default=365, help="how far back (default 365)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("summary", help="totals, streaks, heatmap and projects (default)")
    sub.add_parser("week", help="this week against last week")
    sub.add_parser("json", help="everything as JSON")
    svg = sub.add_parser("svg", help="heatmap image without project names (for a README)")
    svg.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    svg.add_argument("--title", default="Commits")
    srv = sub.add_parser("serve", help="the page on http://127.0.0.1:8748")
    srv.add_argument("--port", type=int, default=8748)
    wk = sub.add_parser("weekly", help="send last week's summary to Iris")
    wk.add_argument("--dry-run", action="store_true", help="print instead of sending")
    rm = sub.add_parser("remind", help="tell Iris when today would break a streak")
    rm.add_argument("--dry-run", action="store_true", help="print instead of sending")
    args = p.parse_args(argv)
    cmd = args.cmd or "summary"
    if not 1 <= args.days <= 3660:
        p.error("--days must be from 1 to 3660")

    try:
        settings = None if args.demo else config.load(args.config)
    except config.ConfigError as exc:
        print(f"chronos: {exc}", file=sys.stderr)
        return 2

    if cmd == "serve":
        from .web import Cache, serve
        serve(Cache(lambda days: build(settings, args.demo, days)), args.port)
        return 0

    s = build(settings, args.demo, args.days)
    color = render.color_on()
    if cmd == "summary":
        print(render.summary_text(s, color))
    elif cmd == "week":
        print(render.week_text(s, color))
    elif cmd == "json":
        json.dump(s, sys.stdout, indent=2)
        print()
    elif cmd == "svg":
        text = render.heatmap_svg(s, args.title)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    elif cmd in ("weekly", "remind"):
        if cmd == "weekly":
            msg = notify.weekly_message(s)
        else:
            after = settings.remind_after if settings else 20
            msg = notify.reminder(s, datetime.now().astimezone(), after)
            if msg is None:
                return 0
        url = settings.iris_url if settings else ""
        if args.dry_run or not url:
            if not url and not args.dry_run:
                print("chronos: iris_url is not set; printing instead", file=sys.stderr)
            print(f"{msg[0]}\n{msg[1]}")
            return 0
        try:
            notify.send(url, *msg)
        except (OSError, ValueError) as exc:
            print(f"chronos: could not send: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
