"""Polite HTTP fetcher: identifies itself, honours robots.txt, throttles per host, caps response size."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    text: str = ""
    content_type: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and bool(self.text)


class PoliteFetcher:
    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 10.0,
                 max_bytes: int = 1_500_000, respect_robots: bool = True):
        self.ua = user_agent
        self.delay = delay
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # -------------------------------------------------------------- throttling
    def _wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready = self._last.get(host, 0.0) + self.delay
            self._last[host] = max(now, ready)
        sleep = ready - now
        if sleep > 0:
            time.sleep(sleep)

    # -------------------------------------------------------------- robots.txt
    def _robots_for(self, scheme: str, host: str):
        key = f"{scheme}://{host}"
        with self._lock:
            if key in self._robots:
                return self._robots[key]
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        try:
            self._wait(host)
            r = self._session.get(f"{key}/robots.txt", timeout=self.timeout)
            if r.status_code in (401, 403) or r.status_code >= 500:
                rp.parse(["User-agent: *", "Disallow: /"])      # fail closed
            elif r.status_code >= 400:
                rp.parse([])                                    # no robots.txt: allowed
            else:
                rp.parse(r.text.splitlines())
        except requests.RequestException:
            rp = None                                           # unreachable: caller will fail anyway
        with self._lock:
            self._robots[key] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        rp = self._robots_for(p.scheme, p.netloc)
        if rp is None:
            return False
        return rp.can_fetch(self.ua, url)

    # -------------------------------------------------------------- fetch
    def get(self, url: str) -> FetchResult:
        res = FetchResult(url=url)
        try:
            if not self.allowed(url):
                res.error = "blocked_by_robots_or_unreachable"
                return res
            host = urlparse(url).netloc
            self._wait(host)
            with self._session.get(url, timeout=self.timeout, stream=True, allow_redirects=True) as r:
                res.status = r.status_code
                res.final_url = r.url
                res.content_type = r.headers.get("Content-Type", "")
                if "html" not in res.content_type.lower() and "text" not in res.content_type.lower():
                    res.error = f"non_text_content_type:{res.content_type}"
                    return res
                buf = bytearray()
                for part in r.iter_content(65536):
                    buf.extend(part)
                    if len(buf) >= self.max_bytes:
                        break
                res.text = bytes(buf).decode("utf-8", errors="replace")
        except requests.RequestException as e:
            res.error = f"{type(e).__name__}"
        return res
