"""Do online shops publish a VAT number more often than other UK pages?  (exploratory, page level)

    python shop_vs_other.py CC-MAIN-2026-43 0 3        # crawl id, first file index, number of files
    python shop_vs_other.py some_file.wet.gz           # or one local file

UK page  = host ends with .uk
Shop page = text mentions 'add to basket/cart/bag', 'checkout', or 'shopping cart/basket'
Has VAT  = a checksum-valid VAT number next to a VAT keyword (same rule as the corpus scan)

Caveats to write down: pages are not companies (a shop's footer repeats on every page); .uk hosts miss .com
shops; the crawl is not a random sample of UK sites; this shows association, not that the law causes it.
"""
import re
import sys
from math import sqrt
from urllib.parse import urlparse

from vatdisc.extract import VAT_WORD, find_vat_hits
from vatdisc.sources import commoncrawl_wet as wet

SHOP = re.compile(r"add to (?:basket|cart|bag)|checkout|shopping (?:cart|basket)|your (?:basket|cart)", re.I)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h), 2), round(100 * (c + h), 2)


src = sys.argv[1]
if src.endswith(".gz"):
    paths = [src]
else:
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    paths = [wet.CC_BASE + p for p in wet.wet_paths(src)[first:first + count]]

tab = {("shop", True): 0, ("shop", False): 0, ("other", True): 0, ("other", False): 0}
hosts = {}          # host -> [has a shop page, has a page with VAT]
uk_pages = 0
for path in paths:
    for uri, text in wet.iter_wet_texts(path):
        host = (urlparse(uri).hostname or "").lower()
        if not host.endswith(".uk"):
            continue
        uk_pages += 1
        kind = "shop" if SHOP.search(text) else "other"
        has_vat = False
        if VAT_WORD.search(text):
            has_vat = any(h.checksum_ok and h.keyword_near for h in find_vat_hits(text))
        tab[(kind, has_vat)] += 1
        h = hosts.setdefault(host, [False, False])
        h[0] = h[0] or kind == "shop"
        h[1] = h[1] or has_vat

print(f"{len(paths)} file(s), {uk_pages} pages on .uk hosts")
for kind in ("shop", "other"):
    k, n = tab[(kind, True)], tab[(kind, True)] + tab[(kind, False)]
    lo, hi = wilson(k, n)
    print(f"{kind:5s}: {k} of {n} pages show a VAT number = {100 * k / n if n else float('nan'):.2f}%  (95% range {lo}% to {hi}%)")

# Same question with one vote per website instead of one per page (a shop's footer repeats on every page).
print(f"\n{len(hosts)} distinct .uk hosts (host counts as 'shop' if any of its pages looks like a shop,")
print("and as 'showing VAT' if any of its pages does):")
for label, want in (("shop", True), ("other", False)):
    sel = [v for v in hosts.values() if v[0] == want]
    k = sum(1 for v in sel if v[1])
    lo, hi = wilson(k, len(sel))
    print(f"{label:5s}: {k} of {len(sel)} hosts show a VAT number = {100 * k / len(sel) if sel else float('nan'):.2f}%  (95% range {lo}% to {hi}%)")