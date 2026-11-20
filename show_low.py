import sqlite3

c = sqlite3.connect("data/vatdisc.sqlite")
q = """SELECT d.company_number, co.name, d.vat, h.name, d.tier, d.name_score, d.reasons, d.sources,
              (SELECT url FROM candidates x WHERE x.company_number=d.company_number AND x.vat=d.vat LIMIT 1),
              (SELECT context FROM candidates x WHERE x.company_number=d.company_number AND x.vat=d.vat LIMIT 1)
       FROM decisions d JOIN companies co USING(company_number) JOIN hmrc h ON h.vrn = d.vat
       WHERE d.tier != 'HIGH' ORDER BY d.vat, d.company_number"""
for cn, ch_name, vat, hmrc_name, tier, score, reasons, sources, url, ctx in c.execute(q):
    print(f"\n{vat}  {sources}  {cn}  {tier}  score={score}\n  CH:   {ch_name}\n  HMRC: {hmrc_name}\n  {url}\n  {(ctx or '')[:200]!r}")