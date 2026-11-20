"""Load your hand-checked GOV.UK results into the hmrc table, so decide / audit / report work as normal.

    python import_manual_hmrc.py            # reads data/manual_hmrc_sheet.csv

Rows are marked as manual in checked_at. Rows with a blank hmrc_status are skipped.
"""
import csv
import datetime as dt
import re
import sqlite3
import sys

PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
path = sys.argv[1] if len(sys.argv) > 1 else "data/manual_hmrc_sheet.csv"
conn = sqlite3.connect("data/vatdisc.sqlite")
stamp = "manual " + dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
done = skipped = 0
for row in csv.DictReader(open(path, encoding="utf-8-sig", newline="")):
    status = (row.get("hmrc_status") or "").strip().lower().replace(" ", "_")
    vat = re.sub(r"\D", "", row.get("vat") or "")[:9]
    if status not in ("valid", "not_found") or len(vat) != 9:
        skipped += 1
        continue
    name = (row.get("hmrc_name") or "").strip()
    addr = (row.get("hmrc_address") or "").strip()
    if status == "valid" and not name:
        sys.exit(f"{vat}: status is valid but hmrc_name is empty")
    m = PC.search(addr)
    postcode = f"{m.group(1).upper()} {m.group(2).upper()}" if m else ""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO hmrc(vrn,status,name,address,postcode,http_status,checked_at) VALUES(?,?,?,?,?,?,?)",
            (vat, status, name, addr, postcode, 200 if status == "valid" else 404, stamp))
    done += 1
print(f"imported {done} rows, skipped {skipped} (blank or unrecognised status)")
