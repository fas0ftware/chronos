import json
import subprocess
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest

from chronos import __main__ as cli
from chronos import config, notify, render, scan, stats
from chronos.demo import commits as demo_commits
from chronos.scan import Commit
from chronos.web import Cache, create_app

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 11, 27, 18, 0, tzinfo=TZ)   # a Friday


def c(repo, day, hour=12, added=1, deleted=0, tz=TZ, sha=None):
    t = datetime.combine(day, datetime.min.time(), tz).replace(hour=hour)
    return Commit(repo, sha or f"{repo}{day}{hour}", t, "msg", added, deleted)


# --- git log parsing -------------------------------------------------------------

def test_parse_log_reads_numstat_and_filters_authors():
    text = ("\x1eaaa\x002026-11-27T10:00:00+03:00\x00Me@Example.com\x00First\n\n3\t1\ta.py\n-\t-\timg.png\n"
            "\x1ebbb\x002026-11-27T11:00:00+03:00\x00other@example.com\x00Not mine\n\n5\t0\tb.py\n")
    out = scan.parse_log(text, "repo", {"me@example.com"})
    assert [x.hash for x in out] == ["aaa"]
    assert (out[0].added, out[0].deleted, out[0].subject) == (3, 1, "First")


def test_parse_log_skips_broken_records():
    assert scan.parse_log("\x1egarbage\n\x1ea\x00not-a-date\x00x@y\x00s\n", "r", set()) == []


# --- streaks, levels, summary ----------------------------------------------------

def test_streak_counts_back_from_yesterday_when_today_is_empty():
    today = date(2026, 11, 27)
    days = Counter({today - timedelta(days=i): 1 for i in (1, 2, 3, 10, 11)})
    s = stats.streaks(days, today)
    assert s["current"] == 3 and not s["today_done"]
    assert s["longest"] == 3 and s["longest_to"] == "2026-11-26"


def test_streak_includes_today_and_breaks_on_gaps():
    today = date(2026, 11, 27)
    days = Counter({today: 2, today - timedelta(days=1): 1, today - timedelta(days=3): 1})
    s = stats.streaks(days, today)
    assert (s["current"], s["today_done"], s["longest"]) == (2, True, 2)
    assert stats.streaks(Counter(), today)["current"] == 0


def test_levels_are_quartiles_and_zero_stays_zero():
    days = Counter({date(2026, 1, d): n for d, n in enumerate([1, 2, 3, 4, 5, 6, 7, 20], start=1)})
    lv = stats.levels(days)
    assert lv[date(2026, 1, 1)] == 1 and lv[date(2026, 1, 8)] == 4
    assert set(lv.values()) <= {1, 2, 3, 4}
    assert stats.levels(Counter()) == {}


def test_days_are_counted_in_the_local_time_zone():
    # 23:30 in UTC-5 is already the next day at UTC+3
    late = Commit("r", "x", datetime(2026, 11, 26, 23, 30, tzinfo=timezone(timedelta(hours=-5))), "s")
    assert stats.local_day(late, TZ) == date(2026, 11, 27)


def test_summary_weeks_and_repos():
    today = NOW.date()
    monday = today - timedelta(days=today.weekday())
    commits = [c("a", monday), c("a", monday + timedelta(days=1)), c("b", today, added=10, deleted=4),
               c("a", monday - timedelta(days=3)), c("old", today - timedelta(days=400))]
    s = stats.summarize(commits, NOW, days=365, repos_scanned=3)
    assert s["totals"]["commits"] == 4          # the 400-day-old one is outside the range
    assert s["this_week"]["commits"] == 3 and s["last_week"]["commits"] == 1
    assert s["repos"][0]["repo"] == "a" and s["repos"][0]["commits"] == 3
    assert s["today_commits"] == 1 and s["streak"]["today_done"]
    assert sum(s["hours"]) == 4 and len(s["weekdays"]) == 7
    assert s["recent"][0]["repo"] == "b"


# --- real repositories ------------------------------------------------------------

def _git(path, *args, env=None):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)


def _repo(path, email):
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", email)
    _git(path, "config", "user.name", "Test")
    return path


def _commit(path, name, author=None, when="2026-11-27T12:00:00+03:00"):
    (path / name).write_text(name)
    _git(path, "add", name)
    args = ["commit", "-q", "-m", f"add {name}", f"--date={when}"]
    if author:
        args.insert(1, f"--author={author}")
    _git(path, *args)


def test_collect_reads_only_your_commits_once(tmp_path):
    a = _repo(tmp_path / "root" / "alpha", "me@example.com")
    _commit(a, "one")
    _commit(a, "two", author="Someone <else@example.com>")
    _git(a, "checkout", "-q", "-b", "feature")
    _commit(a, "three")
    _git(a, "checkout", "-q", "main")
    b = _repo(tmp_path / "root" / "group" / "beta", "me@example.com")
    _commit(b, "four")
    (tmp_path / "root" / "node_modules" / "x").mkdir(parents=True)
    s = config.Settings(roots=[tmp_path / "root"], private=["beta"])
    found, n = scan.collect(s, 30, NOW)
    assert n == 2
    assert sorted(x.repo for x in found) == ["alpha", "alpha", "private project"]   # feature branch counted
    s.all_branches = False
    found, _ = scan.collect(s, 30, NOW)
    assert sorted(x.repo for x in found) == ["alpha", "private project"]


def test_find_repos_respects_depth_and_excludes(tmp_path):
    _repo(tmp_path / "a" / "b" / "c" / "deep", "x@y")
    _repo(tmp_path / "skipme", "x@y")
    _repo(tmp_path / "ok", "x@y")
    found = scan.find_repos([tmp_path], depth=2, exclude=["skipme"])
    assert [p.name for p in found] == ["ok"]


def test_repo_config_cannot_run_a_command(tmp_path):
    repo = _repo(tmp_path / "evil", "me@example.com")
    _commit(repo, "one")
    marker = tmp_path / "ran"
    _git(repo, "config", "core.fsmonitor", f"touch {marker}; false")
    scan.read_commits(repo, {"me@example.com"}, NOW - timedelta(days=5))
    assert not marker.exists()


# --- output ------------------------------------------------------------------------

def test_svg_has_no_project_names_and_escapes_title():
    s = stats.summarize(demo_commits(NOW), NOW)
    svg = render.heatmap_svg(s, title="<b>mine</b>")
    for name in ("cerberus", "olympos", "janus"):
        assert name not in svg
    assert "&lt;b&gt;mine&lt;/b&gt;" in svg and "<b>" not in svg
    assert svg.count("<rect") >= 365 + 5


def test_terminal_heatmap_has_seven_rows_and_month_labels():
    s = stats.summarize(demo_commits(NOW), NOW)
    text = render.heatmap_text(s, color=False)
    lines = text.splitlines()
    assert len(lines) == 9   # months, 7 days, legend
    assert "Nov" in lines[0] and lines[1].startswith("Mo ")
    summary = render.summary_text(s, color=False)
    assert "streak" in summary and "\033[" not in summary


def test_demo_is_stable():
    a, b = demo_commits(NOW), demo_commits(NOW)
    assert [x.hash for x in a] == [x.hash for x in b] and len(a) > 300
    assert all(x.time <= NOW for x in a)


# --- notifications ----------------------------------------------------------------

def _streak_summary(current, today_done):
    return {"streak": {"current": current, "today_done": today_done, "longest": current}}


def test_reminder_only_when_a_streak_is_at_risk_late_in_the_day():
    late, early = NOW.replace(hour=21), NOW.replace(hour=9)
    assert notify.reminder(_streak_summary(4, False), late, 20)[0] == "Chronos: 4-day streak"
    assert notify.reminder(_streak_summary(4, False), early, 20) is None
    assert notify.reminder(_streak_summary(4, True), late, 20) is None
    assert notify.reminder(_streak_summary(0, False), late, 20) is None


def test_send_refuses_plain_http_to_other_machines():
    with pytest.raises(ValueError):
        notify.send("http://10.0.0.5/chronos", "t", "b")
    with pytest.raises(ValueError):
        notify.send("file:///etc/passwd", "t", "b")


def test_weekly_message_uses_the_finished_week():
    s = stats.summarize(demo_commits(NOW), NOW)
    title, body = notify.weekly_message(s)
    assert str(s["last_week"]["commits"]) in title and "Streak" in body
    one = dict(s, streak={"current": 1, "today_done": True, "longest": 1})
    assert "Streak: 1 day (longest 1 day)." in notify.weekly_message(one)[1]


# --- settings ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", [{"roots": "x"}, {"depth": 9}, {"depth": True}, {"iris_url": "ftp://x"},
                                 {"remind_after": 24}, {"all_branches": "yes"}])
def test_config_rejects_bad_values(bad):
    with pytest.raises(config.ConfigError):
        config.parse(bad)


def test_config_lowercases_authors(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('roots = ["~/src"]\nauthors = ["Me@Example.COM"]\n')
    s = config.load(f)
    assert s.authors == ["me@example.com"] and s.roots[0].name == "src"


# --- web ----------------------------------------------------------------------------

@pytest.fixture()
def server():
    s = stats.summarize(demo_commits(NOW), NOW)
    cache = Cache(lambda days: dict(s, asked=days))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = srv.server_address[1]
    srv.RequestHandlerClass = create_app(cache).handler(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()
    srv.server_close()


def _get(port, path, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host or f"127.0.0.1:{port}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.headers, r.read()


def test_web_serves_stats_svg_and_page(server):
    status, headers, body = _get(server, "/api/stats?days=90")
    assert status == 200 and json.loads(body)["asked"] == 90
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert json.loads(_get(server, "/api/stats?days=7")[2])["asked"] == 365   # only known ranges
    status, headers, body = _get(server, "/api/heatmap.svg")
    assert headers["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg")
    assert b"Chronos" in _get(server, "/")[2]


def test_web_refuses_foreign_host(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server, "/api/stats", host="evil.example:80")
    assert exc.value.code == 403


def test_web_refresh_needs_same_origin(server):
    req = urllib.request.Request(f"http://127.0.0.1:{server}/api/refresh", data=b'{"days": 30}', method="POST",
                                 headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 403


# --- command line -------------------------------------------------------------------

def test_cli_demo_json_and_svg(capsys, tmp_path):
    assert cli.main(["--demo", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["demo"] and data["totals"]["commits"] > 300
    out = tmp_path / "h.svg"
    assert cli.main(["--demo", "svg", "-o", str(out)]) == 0
    assert out.read_text().startswith("<svg")


def test_cli_rejects_bad_days(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--demo", "--days", "0"])


def test_streak_task_opens_only_when_at_risk_and_in_turkish():
    late = NOW.replace(hour=21)
    assert notify.streak_tasks(_streak_summary(4, True), late, 20) == []
    assert notify.streak_tasks(_streak_summary(4, False), NOW.replace(hour=9), 20) == []
    [t] = notify.streak_tasks(_streak_summary(4, False), late, 20, "tr")
    assert t["id"] == "streak" and t["priority"] == "high" and t["title"] == "Bugün commit at: 4 günlük seri"
    assert notify.iris_base("http://127.0.0.1:8090/chronos") == "http://127.0.0.1:8090"
    with pytest.raises(ValueError):
        notify.sync_tasks("http://10.0.0.5:8090/chronos", [])


def test_config_lang():
    assert config.parse({"lang": "tr"}).lang == "tr"
    with pytest.raises(config.ConfigError):
        config.parse({"lang": "de"})
