"""Source 3: Peppol Directory (UK participants are registered under scheme 9932 = GB VAT number).

Public REST search: https://directory.peppol.eu/search/1.0/json?q=<text>&country=GB
Caveats worth testing and writing up, not assuming:
  * listing in the directory is optional, so absence proves nothing;
  * UK adoption is small, so expect a very low yield on a random sample;
  * the response parsing below is defensive but UNTESTED against the live API from this build
    environment: run it on ~20 known names first and inspect the raw JSON.
"""
from __future__ import annotations

import time

import requests

from ..matching import name_score
from ..vat import normalise_vrn

SEARCH_URL = "https://directory.peppol.eu/search/1.0/json"


def search_by_name(name: str, user_agent: str, timeout: float = 20.0, delay: float = 1.0) -> list[dict]:
    time.sleep(delay)
    r = requests.get(
        SEARCH_URL, params={"q": name, "country": "GB"},
        headers={"User-Agent": user_agent}, timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("matches", [])


def extract_vat_candidates(matches: list[dict], company_name: str, min_name_score: float = 80.0) -> list[dict]:
    """Keep only 9932 (GB VAT) participants whose directory entity name resembles the company."""
    out: list[dict] = []
    for m in matches:
        pid = m.get("participantID", {})
        value = str(pid.get("value", ""))
        if not value.startswith("9932:"):
            continue
        vrn = normalise_vrn(value.split(":", 1)[1])
        if not vrn:
            continue
        for ent in m.get("entities", []) or [{}]:
            names = [n.get("name", "") for n in ent.get("name", []) or []]
            best = max((name_score(company_name, n) for n in names), default=0.0)
            if best >= min_name_score:
                out.append({
                    "vat": vrn[:9], "kind": "peppol", "url": f"peppol:{value}",
                    "context": f"directory_names={names}; website={ent.get('websites')}",
                    "checksum_ok": None,  # filled by caller
                })
                break
    return out
