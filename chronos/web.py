"""The browser page: python -m chronos serve (127.0.0.1 only, read-only)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .render import heatmap_svg
from .web_base import App

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8747
CACHE_SECONDS = 60
RANGES = (30, 90, 182, 365)


class Cache:
    """Reading every repository takes a moment: keep the result for a minute per range."""

    def __init__(self, build: Callable[[int], dict]):
        self.build = build
        self.lock = threading.Lock()
        self.items: dict[int, tuple[float, dict]] = {}

    def get(self, days: int, force: bool = False) -> dict:
        with self.lock:
            hit = self.items.get(days)
            if hit and not force and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
            value = self.build(days)
            self.items[days] = (time.monotonic(), value)
            return value


def _days(query: dict) -> int:
    try:
        n = int(query.get("days", "365"))
    except ValueError:
        return 365
    return n if n in RANGES else 365


def create_app(cache: Cache) -> App:
    app = App(STATIC)

    @app.get("/api/stats")
    def stats(query):
        return cache.get(_days(query))

    @app.get("/api/heatmap.svg")
    def heatmap(query):
        return heatmap_svg(cache.get(_days(query))).encode(), "image/svg+xml", {}

    @app.post("/api/refresh")
    def refresh(body):
        days = body.get("days") if isinstance(body, dict) else None
        return cache.get(days if days in RANGES else 365, force=True)

    return app


def serve(cache: Cache, port: int = DEFAULT_PORT) -> None:
    create_app(cache).serve(port, "Chronos")
