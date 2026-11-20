"""Show pages where the corpus scan found a valid VAT number but NO company number, i.e. the pages it drops.

    python show_wet_dropped.py CC-MAIN-2026-43 0 15     # crawl id, file index, how many pages to show
    python show_wet_dropped.py some_file.wet.gz _ 15    # or a local file

Read the pages: is a company number really there in a form the extractor misses ("Reg No", "Co. Reg."...)?
That tells you whether recall is being lost to the company-number patterns.
"""
import sys

from vatdisc.extract import VAT_WORD, find_company_number_spans, find_vat_hits
from vatdisc.sources import commoncrawl_wet as wet

src = sys.argv[1]
idx = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
show = int(sys.argv[3]) if len(sys.argv) > 3 else 15
path = src if src.endswith(".gz") else wet.CC_BASE + wet.wet_paths(src)[idx]

shown = total = 0
for uri, text in wet.iter_wet_texts(path):
    if not VAT_WORD.search(text):
        continue
    hits = [h for h in find_vat_hits(text) if h.checksum_ok and h.keyword_near]
    if not hits or find_company_number_spans(text):
        continue
    total += 1
    if shown < show:
        shown += 1
        print(f"\n{uri}\n  vat={hits[0].vat}\n  {hits[0].context!r}")
print(f"\n{total} pages in this file have a valid VAT number but no company number (showed {shown})")
