"""Check the Peppol source code against the browser, name by name.

    python peppol_check.py "NAME ONE" "NAME TWO" ...

For each name it asks the Directory twice: the way the code does (parameter q) and the way you did it
in the browser (parameter name). Compare the counts. If they differ, the code asks the wrong question.
"""
import sys
import time

import requests

from vatdisc.config import get_settings
from vatdisc.sources import peppol

s = get_settings()
HEAD = {"User-Agent": s.user_agent}
for name in sys.argv[1:]:
    time.sleep(1.0)
    by_q = peppol.search_by_name(name, s.user_agent)
    time.sleep(1.0)
    r = requests.get(peppol.SEARCH_URL, params={"name": name, "country": "GB"}, headers=HEAD, timeout=20)
    r.raise_for_status()
    by_name = r.json().get("matches", [])
    kept = peppol.extract_vat_candidates(by_q, name)
    print(f"\n{name!r}: code (q=) -> {len(by_q)} matches, {len(kept)} kept | browser style (name=) -> {len(by_name)} matches")
    for m in by_name[:3]:
        names = [n.get("name") for e in (m.get("entities") or []) for n in (e.get("name") or [])]
        print("   name= result:", (m.get("participantID") or {}).get("value"), names)
    for c in kept:
        print("   kept by code:", c["vat"], c["context"])
