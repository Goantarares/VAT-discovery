import sqlite3
from urllib.parse import urlparse

c = sqlite3.connect("data/vatdisc.sqlite")
rows = c.execute("SELECT company_number, vat, url FROM candidates WHERE source='cc_wet'").fetchall()
pairs = {(cn, v) for cn, v, _ in rows}
print("rows (page x pair):", len(rows))
print("distinct (company, VAT) pairs:", len(pairs))
print("distinct company numbers:", len({cn for cn, _ in pairs}))
print("distinct domains:", len({urlparse(u).netloc for _, _, u in rows}))
by_cn, by_vat = {}, {}
for cn, v in pairs:
    by_cn.setdefault(cn, set()).add(v)
    by_vat.setdefault(v, set()).add(cn)
print("company numbers with >1 VAT:", {k: sorted(v) for k, v in by_cn.items() if len(v) > 1})
print("VATs with >1 company number:", {k: sorted(v) for k, v in by_vat.items() if len(v) > 1})
for r in c.execute("SELECT unit, pages, pairs, skipped_multi, seconds FROM scan_log WHERE source='cc_wet'"):
    print("scan:", r)
