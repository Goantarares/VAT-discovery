import sqlite3

from vatdisc.sources import commoncrawl_wet as wet

KNOWN = ["990773966", "512854400", "857712693", "503312840", "344516995", "800537562"]

c = sqlite3.connect("data/vatdisc.sqlite")

# 1. did the corpus scan find any of the six numbers you found by hand?
q = "SELECT vat, company_number FROM candidates WHERE vat IN (%s)" % ",".join("?" * len(KNOWN))
found = c.execute(q, KNOWN).fetchall()
print("known numbers found by the corpus scan:", found, f"({len(found)} of {len(KNOWN)})")

# 2. remove the duplicate scan_log row left by re-running file 0
with c:
    removed = c.execute(
        "DELETE FROM scan_log WHERE id NOT IN (SELECT MIN(id) FROM scan_log GROUP BY source, unit)").rowcount
print("duplicate scan_log rows removed:", removed)

# 3. how many WET files does the crawl have?
paths = wet.wet_paths("CC-MAIN-2026-43")
print("WET files in CC-MAIN-2026-43:", len(paths))