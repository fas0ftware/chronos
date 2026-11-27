"""Find git repositories and read their commits (read-only, no shell, no network)."""

from __future__ import annotations

import subprocess  # nosec B404
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .config import Settings

# A repository's own config must never run code: fsmonitor is a command git would start.
SAFE = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "--no-pager")
GIT_TIMEOUT = 60
SKIP = {"node_modules", ".venv", "venv", "target", "__pycache__", ".git", "build", "dist"}
REC, FLD = "\x1e", "\x00"


@dataclass
class Commit:
    repo: str          # folder name (or "private project")
    hash: str
    time: datetime     # aware, the author's own time zone
    subject: str
    added: int = 0
    deleted: int = 0


def git(path: Path, *args: str) -> str:
    out = subprocess.run(["git", *SAFE, "-C", str(path), *args],  # nosec B603 B607
                         capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        err = out.stderr.strip().splitlines()
        raise RuntimeError(err[-1] if err else f"git {args[0]} failed")
    return out.stdout


def find_repos(roots: list[Path], depth: int = 2, exclude: list[str] | None = None) -> list[Path]:
    """Every folder that holds a .git (folder or file) at most `depth` levels under a root."""
    skip = SKIP | set(exclude or [])
    found: list[Path] = []
    seen: set[Path] = set()

    def walk(folder: Path, level: int) -> None:
        if (folder / ".git").exists():
            real = folder.resolve()
            if real not in seen:
                seen.add(real)
                found.append(folder)
        if level >= depth:
            return
        try:
            children = sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            return
        for child in children:
            if child.name not in skip and not child.name.startswith("."):
                walk(child, level + 1)

    for root in roots:
        if root.is_dir():
            walk(root, 0)
    return found


def repo_emails(path: Path) -> set[str]:
    try:
        return {git(path, "config", "user.email").strip().lower()} - {""}
    except RuntimeError:
        return set()


def parse_log(text: str, repo: str, authors: set[str]) -> list[Commit]:
    """Parse `git log --format=REC%H FLD %aI FLD %ae FLD %s --numstat`."""
    commits = []
    for record in text.split(REC):
        if not record.strip():
            continue
        head, _, rest = record.partition("\n")
        parts = head.split(FLD)
        if len(parts) != 4:
            continue
        sha, when, email, subject = parts
        if authors and email.strip().lower() not in authors:
            continue
        try:
            time = datetime.fromisoformat(when)
        except ValueError:
            continue
        added = deleted = 0
        for line in rest.splitlines():
            cols = line.split("\t")
            if len(cols) == 3:
                # binary files show "-"
                added += int(cols[0]) if cols[0].isdigit() else 0
                deleted += int(cols[1]) if cols[1].isdigit() else 0
        commits.append(Commit(repo, sha, time, subject[:200], added, deleted))
    return commits


def read_commits(path: Path, authors: set[str], since: datetime, all_branches: bool = True,
                 label: str | None = None) -> list[Commit]:
    args = ["log", "--no-merges", f"--since={since.isoformat()}",
            "--format=%x1e%H%x00%aI%x00%ae%x00%s", "--numstat"]
    if all_branches:
        args.append("--branches")
    try:
        text = git(path, *args)
    except RuntimeError:
        return []   # empty repository, or not readable
    return parse_log(text, label or path.name, authors)


def collect(settings: Settings, days: int = 366, now: datetime | None = None) -> tuple[list[Commit], int]:
    """All of your commits from the last `days` days, each counted once. Returns (commits, repos)."""
    now = now or datetime.now().astimezone()
    since = now - timedelta(days=days)
    repos = find_repos(settings.roots, settings.depth, settings.exclude)
    fixed = set(settings.authors)
    private = set(settings.private)
    seen: set[str] = set()
    out: list[Commit] = []
    for repo in repos:
        authors = fixed or repo_emails(repo)
        if not authors:
            continue    # no identity to match: better nothing than everybody's commits
        label = "private project" if repo.name in private else repo.name
        for c in read_commits(repo, authors, since, settings.all_branches, label):
            if c.hash not in seen:
                seen.add(c.hash)
                out.append(c)
    out.sort(key=lambda c: c.time)
    return out, len(repos)
