"""List what the website scan found: one line per candidate, with where it came from."""
import sqlite3

c = sqlite3.connect("data/vatdisc.sqlite")
rows = c.execute(
    "SELECT c.company_number, co.name, c.vat, c.kind, c.checksum_ok, c.url, c.context "
    "FROM candidates c LEFT JOIN companies co USING(company_number) WHERE c.source='website' "
    "ORDER BY c.company_number").fetchall()
print(len(rows), "website candidates;", len({r[0] for r in rows}), "companies;",
      sum(1 for r in rows if r[4]), "checksum-valid")
for cn, name, vat, kind, ok, url, ctx in rows:
    print(f"\n{cn}  {name}\n  vat={vat}  kind={kind}  checksum_ok={ok}\n  {url}\n  {(ctx or '')[:160]!r}")
