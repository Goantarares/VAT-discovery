"""Back up the database, then remove earlier Common Crawl results so the improved pairing starts clean."""
import shutil
import sqlite3

shutil.copy("data/vatdisc.sqlite", "data/vatdisc_v1_backup.sqlite")
c = sqlite3.connect("data/vatdisc.sqlite")
with c:
    n = c.execute("DELETE FROM candidates WHERE source='cc_wet'").rowcount
    m = c.execute("DELETE FROM scan_log WHERE source='cc_wet'").rowcount
print(f"backup saved to data/vatdisc_v1_backup.sqlite; removed {n} candidate rows and {m} scan_log rows")
