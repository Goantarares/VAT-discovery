"""Client for HMRC's 'Check a UK VAT number' API (v2, application-restricted OAuth).

  GET {base}/organisations/vat/check-vat-number/lookup/{targetVrn}
  -> 200 {"target": {"name": ..., "vatNumber": ..., "address": {"line1".."line5", "postcode", "countryCode"}}}
  -> 404 {"code": "NOT_FOUND"}   (number not registered)
  -> 400 invalid format,  429 rate limited,  5xx transient

Safeguards built in on purpose:
  * every response is cached in SQLite by VRN, so a number is never asked twice;
  * a hard per-process call budget (HMRC_MAX_CALLS);
  * requests/second limiter and Retry-After aware backoff on 429;
  * the only public entry point verifies ONE number handed to it. There is no enumeration helper.

Check the current endpoint, scopes and rate limits in the HMRC developer hub before production use;
this was written from the published API description and is untested against the live service.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import time
from dataclasses import dataclass

import requests

from .config import Settings
from .vat import base9, normalise_vrn

ACCEPT = "application/vnd.hmrc.2.0+json"


class CallBudgetExceeded(RuntimeError):
    pass


@dataclass
class HMRCResult:
    vrn: str
    status: str                 # valid | not_found | invalid | error
    name: str = ""
    address: str = ""
    postcode: str = ""
    http_status: int = 0
    from_cache: bool = False


class HMRCClient:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, session: requests.Session | None = None):
        self.s = settings
        self.conn = conn
        self.http = session or requests.Session()
        self.calls = 0
        self._token: str | None = None
        self._token_expiry = 0.0
        self._last_call = 0.0

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        if not (self.s.hmrc_client_id and self.s.hmrc_client_secret):
            raise RuntimeError("HMRC_CLIENT_ID / HMRC_CLIENT_SECRET are not set")
        data = {
            "client_id": self.s.hmrc_client_id,
            "client_secret": self.s.hmrc_client_secret,
            "grant_type": "client_credentials",
        }
        if self.s.hmrc_scope:
            data["scope"] = self.s.hmrc_scope
        r = self.http.post(f"{self.s.hmrc_base_url}/oauth/token", data=data, timeout=30)
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + float(body.get("expires_in", 3600))
        return self._token

    # ------------------------------------------------------------------ cache
    def _cached(self, vrn: str) -> HMRCResult | None:
        row = self.conn.execute("SELECT * FROM hmrc WHERE vrn=?", (vrn,)).fetchone()
        if not row:
            return None
        return HMRCResult(vrn, row["status"], row["name"] or "", row["address"] or "",
                          row["postcode"] or "", row["http_status"] or 0, True)

    def _store(self, r: HMRCResult) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO hmrc(vrn,status,name,address,postcode,http_status,checked_at) VALUES(?,?,?,?,?,?,?)",
                (r.vrn, r.status, r.name, r.address, r.postcode, r.http_status,
                 dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
            )

    # ------------------------------------------------------------------ request
    def _throttle(self) -> None:
        gap = 1.0 / max(self.s.hmrc_rps, 0.1)
        wait = self._last_call + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def lookup(self, vrn_raw: str, refresh: bool = False) -> HMRCResult:
        vrn = normalise_vrn(vrn_raw)
        if vrn is None:
            return HMRCResult(str(vrn_raw), "invalid")
        vrn = base9(vrn)
        if not refresh:
            hit = self._cached(vrn)
            if hit:
                return hit
        if self.calls >= self.s.hmrc_max_calls:
            raise CallBudgetExceeded(f"HMRC call budget of {self.s.hmrc_max_calls} reached")

        url = f"{self.s.hmrc_base_url}/organisations/vat/check-vat-number/lookup/{vrn}"
        backoff = 2.0
        for attempt in range(6):
            self._throttle()
            self.calls += 1
            try:
                r = self.http.get(url, headers={"Accept": ACCEPT, "Authorization": f"Bearer {self._get_token()}"}, timeout=30)
            except requests.RequestException:
                time.sleep(backoff); backoff *= 2
                continue
            if r.status_code == 200:
                t = (r.json() or {}).get("target", {})
                a = t.get("address", {}) or {}
                lines = [a.get(f"line{i}", "") for i in range(1, 6)]
                addr = ", ".join(x for x in lines + [a.get("postcode", "")] if x)
                res = HMRCResult(vrn, "valid", t.get("name", ""), addr, a.get("postcode", ""), 200)
                self._store(res)
                return res
            if r.status_code == 404:
                res = HMRCResult(vrn, "not_found", http_status=404)
                self._store(res)
                return res
            if r.status_code == 400:
                res = HMRCResult(vrn, "invalid", http_status=400)
                self._store(res)
                return res
            if r.status_code == 401:
                self._token = None            # refresh and retry
                continue
            if r.status_code == 429:
                try:
                    wait = float(r.headers.get("Retry-After", backoff))
                except ValueError:
                    wait = backoff
                time.sleep(wait); backoff *= 2
                continue
            if r.status_code >= 500:
                time.sleep(backoff); backoff *= 2
                continue
            return HMRCResult(vrn, "error", http_status=r.status_code)   # not cached
        return HMRCResult(vrn, "error", http_status=0)                  # not cached
