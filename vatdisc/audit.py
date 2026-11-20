"""Blind manual audit: measures how often the automated decision is wrong ("verifying the verifier").

Workflow
  1. audit-export: draws a random, tier-stratified set of decided pairs. Writes
       audit_sheet.csv  - what the human sees (NO tier, NO score: labelling is blind to the algorithm)
       audit_key.csv    - the tier for each row, kept apart
  2. Label each row in audit_sheet.csv:  correct | wrong | unsure
       correct = the VAT number genuinely belongs to this Companies House company. Judge from the HMRC
                 name/address, the source URL/context, the company's own website, accountant/registered-
                 office patterns. Trading-name or accountant-address differences are NOT errors.
       wrong   = the number belongs to a different legal entity (parent, group member, namesake, client...).
       unsure  = cannot tell. Counted as wrong in the conservative figure.
  3. audit-import: loads labels. audit-report: precision per tier with Wilson interval / rule of three.
Auditing LOW rows too tells you how many true matches the matcher throws away.
"""
from __future__ import annotations

import random
import sqlite3
from pathlib import Path

import pandas as pd

from .evaluate import rule_of_three, wilson

CH_URL = "https://find-and-update.company-information.service.gov.uk/company/"


def export_audit(conn: sqlite3.Connection, out_dir: Path, n_high: int = 60, n_medium: int = 30,
                 n_low: int = 30, seed: int = 7) -> tuple[Path, Path]:
    rng = random.Random(seed)
    rows = conn.execute("""
        SELECT d.company_number, d.vat, d.tier, d.name_score, d.postcode_match,
               co.name AS ch_name, co.address AS ch_address,
               h.name AS hmrc_name, h.address AS hmrc_address,
               (SELECT url FROM candidates c WHERE c.company_number=d.company_number AND c.vat=d.vat LIMIT 1) AS source_url,
               (SELECT context FROM candidates c WHERE c.company_number=d.company_number AND c.vat=d.vat LIMIT 1) AS context
        FROM decisions d
        JOIN companies co USING(company_number)
        JOIN hmrc h ON h.vrn=d.vat""").fetchall()
    chosen = []
    for tier, n in (("HIGH", n_high), ("MEDIUM", n_medium), ("LOW", n_low)):
        pool = [r for r in rows if r["tier"] == tier]
        chosen += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(chosen)

    sheet = pd.DataFrame([{
        "company_number": r["company_number"], "vat": r["vat"],
        "ch_name": r["ch_name"], "ch_address": r["ch_address"],
        "hmrc_name": r["hmrc_name"], "hmrc_address": r["hmrc_address"],
        "source_url": r["source_url"], "context": r["context"],
        "companies_house_link": CH_URL + r["company_number"],
        "label": "", "notes": "",
    } for r in chosen])
    key = pd.DataFrame([{"company_number": r["company_number"], "vat": r["vat"], "tier": r["tier"]} for r in chosen])
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_p, key_p = out_dir / "audit_sheet.csv", out_dir / "audit_key.csv"
    sheet.to_csv(sheet_p, index=False)
    key.to_csv(key_p, index=False)
    return sheet_p, key_p


def import_audit(conn: sqlite3.Connection, sheet_path: Path, key_path: Path) -> int:
    sheet = pd.read_csv(sheet_path, dtype=str).fillna("")
    key = pd.read_csv(key_path, dtype=str)
    m = sheet.merge(key, on=["company_number", "vat"])
    m = m[m["label"].str.strip().str.lower().isin({"correct", "wrong", "unsure"})]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO audit(company_number,vat,tier,label,notes) VALUES(?,?,?,?,?)",
            [(r.company_number, r.vat, r.tier, r.label.strip().lower(), r.notes) for r in m.itertuples(index=False)])
    return len(m)


def precision_report(conn: sqlite3.Connection) -> tuple[pd.DataFrame, str]:
    df = pd.read_sql_query("SELECT tier, label FROM audit", conn)
    rows = []
    for tier, g in df.groupby("tier"):
        n = len(g)
        wrong = int((g["label"] == "wrong").sum())
        unsure = int((g["label"] == "unsure").sum())
        correct = n - wrong - unsure
        fp_lo, fp_hi = wilson(wrong, n)
        cons_lo, cons_hi = wilson(wrong + unsure, n)
        rows.append({
            "tier": tier, "audited": n, "correct": correct, "wrong": wrong, "unsure": unsure,
            "fp_rate": wrong / n, "fp_ci95_lo": fp_lo, "fp_ci95_hi": fp_hi,
            "fp_rate_conservative(unsure=wrong)": (wrong + unsure) / n,
            "rule_of_three_upper(if wrong=0)": rule_of_three(n) if wrong == 0 else float("nan"),
        })
    table = pd.DataFrame(rows)
    note = (
        "For tier HIGH the false-positive rate is the share of audited HIGH pairs labelled 'wrong'. "
        "For tier LOW a high 'correct' share means the matcher is discarding true matches (lost recall).\n")
    from .evaluate import _md
    return table, _md(table) + note
