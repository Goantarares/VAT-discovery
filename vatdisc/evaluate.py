"""Evaluation maths and the results report.

What these numbers can and cannot say:
  * Precision (1 - false-positive rate) is measured from a manual audit of a random subset of accepted
    pairs, reported with a Wilson interval; with zero observed errors we also give the rule-of-three bound.
  * Coverage is reported as a *weighted share of the eligible population* by outcome class, using the
    sampling weights. It is not recall: 'no_vat_on_verified_site' cannot be split into
    'unregistered' vs 'registered but unpublished' from this data.
  * Capture-recapture needs two independent detection methods. Website- and corpus-based methods both favour
    web-active companies, so independence is violated and the estimate is a lower-bound-ish illustration.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd

from .sampling import kish_effective_n


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rule_of_three(n: int) -> float:
    """Approximate 95% upper bound on an error rate when 0 errors were seen in n trials."""
    return 3.0 / n if n else 1.0


def chapman(n1: int, n2: int, m: int) -> dict:
    """Chapman capture-recapture estimator with a 95% normal-approx interval (Seber variance)."""
    n_hat = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = ((n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m)) / ((m + 1) ** 2 * (m + 2))
    se = math.sqrt(max(var, 0.0))
    return {"n_hat": n_hat, "lo": max(n1 + n2 - m, n_hat - 1.96 * se), "hi": n_hat + 1.96 * se,
            "n1": n1, "n2": n2, "overlap": m}


def weighted_outcome_table(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT o.outcome, s.weight FROM outcomes o JOIN sample s USING(company_number)", conn)
    if df.empty:
        return pd.DataFrame(columns=["outcome", "n", "weighted_share", "wilson_lo_approx", "wilson_hi_approx"])
    total_w = df["weight"].sum()
    n_eff = kish_effective_n(df["weight"])
    rows = []
    for outcome, g in df.groupby("outcome"):
        share = g["weight"].sum() / total_w
        k_eff = share * n_eff
        lo, hi = wilson(int(round(k_eff)), int(round(n_eff)))
        rows.append({"outcome": outcome, "n": len(g), "weighted_share": share,
                     "wilson_lo_approx": lo, "wilson_hi_approx": hi})
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)


def funnel(conn: sqlite3.Connection) -> dict:
    q = lambda s: conn.execute(s).fetchone()[0]
    return {
        "sample_size": q("SELECT count(*) FROM sample"),
        "domains_found": q("SELECT count(*) FROM domains WHERE status='found'"),
        "domains_attempted": q("SELECT count(*) FROM domains"),
        "companies_with_any_candidate": q("SELECT count(DISTINCT company_number) FROM candidates"),
        "candidates_total": q("SELECT count(*) FROM candidates"),
        "candidates_checksum_ok": q("SELECT count(*) FROM candidates WHERE checksum_ok=1"),
        "distinct_vrns_checked_at_hmrc": q("SELECT count(*) FROM hmrc WHERE status IN ('valid','not_found','invalid')"),
        "hmrc_valid": q("SELECT count(*) FROM hmrc WHERE status='valid'"),
        "hmrc_not_found": q("SELECT count(*) FROM hmrc WHERE status='not_found'"),
        "decisions_HIGH": q("SELECT count(*) FROM decisions WHERE tier='HIGH'"),
        "decisions_MEDIUM": q("SELECT count(*) FROM decisions WHERE tier='MEDIUM'"),
        "decisions_LOW": q("SELECT count(*) FROM decisions WHERE tier='LOW'"),
    }


def source_yield(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT c.source,
               count(*) AS candidates,
               sum(c.checksum_ok) AS checksum_ok,
               count(DISTINCT c.company_number) AS companies,
               count(DISTINCT CASE WHEN d.tier='HIGH' THEN c.company_number END) AS companies_high,
               count(DISTINCT CASE WHEN d.tier='MEDIUM' THEN c.company_number END) AS companies_medium
        FROM candidates c
        LEFT JOIN decisions d ON d.company_number=c.company_number AND d.vat=c.vat
        GROUP BY c.source""", conn)


def scan_yield(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT source, count(*) AS units, sum(pages) AS pages, sum(pages_with_vat_kw) AS pages_vat_kw,
               sum(pages_with_vat) AS pages_vat_valid, sum(pages_with_both) AS pages_vat_and_cn,
               sum(pairs) AS pairs, sum(skipped_multi) AS skipped_multi, sum(seconds) AS seconds
        FROM scan_log GROUP BY source""", conn)


def method_overlap(conn: sqlite3.Connection, a: str, b: str) -> dict | None:
    """Capture-recapture between two sources over companies with a HIGH decision from each."""
    def high(src: str) -> set[str]:
        return {r[0] for r in conn.execute(
            "SELECT company_number FROM decisions WHERE tier='HIGH' AND (',' || sources || ',') LIKE ?",
            (f"%,{src},%",))}
    A, B = high(a), high(b)
    if not A or not B:
        return None
    return chapman(len(A), len(B), len(A & B))


def _md(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_\n"
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda x: f"{x:.3f}")
    head = "| " + " | ".join(map(str, d.columns)) + " |\n|" + "|".join("---" for _ in d.columns) + "|\n"
    return head + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in d.itertuples(index=False)) + "\n"


def build_report(conn: sqlite3.Connection, path: Path, precision_md: str = "") -> str:
    parts = ["# Results (auto-generated)\n"]
    parts.append("## Funnel\n" + _md(pd.DataFrame([funnel(conn)]).T.reset_index().rename(columns={"index": "step", 0: "count"})))
    parts.append("## Outcome classes (weighted to eligible population)\n" + _md(weighted_outcome_table(conn)))
    parts.append("## Yield by source\n" + _md(source_yield(conn)))
    parts.append("## Corpus/scan yield\n" + _md(scan_yield(conn)))
    ov = method_overlap(conn, "website", "cc_wet")
    parts.append("## Capture-recapture (website vs cc_wet)\n" + (str(ov) if ov else "_not enough overlap data_") + "\n")
    if precision_md:
        parts.append("## Precision (manual audit)\n" + precision_md)
    parts.append(
        "## What these numbers do not capture\n"
        "- `no_vat_on_verified_site` mixes unregistered and registered-but-unpublished companies.\n"
        "- `no_domain_found` is a method failure, not evidence of absence.\n"
        "- Companies without a name-like domain are systematically missed by the website source.\n"
        "- Precision is measured only on audited pairs; unaudited tiers have no error estimate.\n"
        "- Sole traders and VAT groups are not separable from Companies House data alone.\n")
    text = "\n".join(parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
