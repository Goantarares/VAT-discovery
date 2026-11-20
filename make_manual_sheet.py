"""Pick a random, reproducible set of pairs for you to check by hand on the GOV.UK
'Check a UK VAT number' page.

    python make_manual_sheet.py 40                 # 40 corpus pairs -> data/manual_hmrc_sheet.csv
    python make_manual_sheet.py 100 website        # website-scan candidates -> data/manual_hmrc_sheet_website.csv

Only the VAT number and the page it came from are in the sheet. You type what GOV.UK says.
Only pairs whose company number exists in the Companies House file can be judged, so only those are offered.
Numbers already checked (present in the hmrc table) are left out.
After filling a sheet:  python import_manual_hmrc.py <that csv>
"""
import csv
import random
import sqlite3
import sys

n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
source = sys.argv[2] if len(sys.argv) > 2 else "cc_wet"
out = "data/manual_hmrc_sheet.csv" if source == "cc_wet" else f"data/manual_hmrc_sheet_{source}.csv"

conn = sqlite3.connect("data/vatdisc.sqlite")
rows = conn.execute(
    "SELECT c.vat, MIN(c.url) FROM candidates c JOIN companies co USING(company_number) "
    "WHERE c.source=? AND c.checksum_ok=1 AND c.vat NOT IN (SELECT vrn FROM hmrc) "
    "GROUP BY c.vat, c.company_number ORDER BY c.vat", (source,)
).fetchall()
random.Random(42).shuffle(rows)
chosen = rows[:n]
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["vat", "source_url", "hmrc_status", "hmrc_name", "hmrc_address"])
    for vat, url in chosen:
        w.writerow([vat, url, "", "", ""])
print(f"{len(rows)} unchecked linked '{source}' pairs available; wrote {len(chosen)} to {out}")
print("fill hmrc_status with: valid | not_found   (leave blank if the page failed)")
