import sqlite3

c = sqlite3.connect("data/vatdisc.sqlite")
rows = c.execute(
    "SELECT company_number, vat, kind, url, context FROM candidates WHERE source='cc_wet' ORDER BY url"
).fetchall()
print(len(rows), "pairs")
for cn, vat, kind, url, ctx in rows:
    print(f"\n{cn}  |  {vat}  |  {kind}\n  {url}\n  {(ctx or '')[:200]!r}")