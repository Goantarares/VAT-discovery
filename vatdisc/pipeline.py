"""Orchestration: store results, verify against HMRC, decide, classify outcomes.

Outcome classes per sampled company (the answer to "what does 'not found' mean?"):
  verified_high            HMRC-valid number, strong name match + corroboration
  needs_review             HMRC-valid number, plausible but not auto-accepted
  rejected_mismatch        HMRC-valid number found, but it does not look like this company
  hmrc_not_found           number(s) found but HMRC says they are not registered (typo / stale / third party)
  checksum_failed_only     VAT-looking strings found, all fail the checksum
  pending_verification     candidates exist but have not been through HMRC yet
  no_vat_on_verified_site  site proven to be the company's, no VAT number on it -> likely unregistered
                           OR registered-but-unpublished (indistinguishable from this data alone)
  no_domain_found          could not map the company to a website -> METHOD FAILURE, state unknown
  not_attempted            no discovery run for this company yet
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import pandas as pd
from tqdm import tqdm

from .config import Settings
from .hmrc import CallBudgetExceeded, HMRCClient
from .http import PoliteFetcher
from .matching import Thresholds, best_name_score, decide, postcode_relation
from .sources import peppol as peppol_src
from .sources.commoncrawl_wet import WetResult
from .sources.website import scan_company
from .vat import checksum_ok


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------- storage

def store_companies(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = [
        (r.company_number, r.name, r.prev_names, r.status, r.category, r.accounts_category,
         r.sic_section, r.incorporation_date, r.postcode, r.address)
        for r in df.itertuples(index=False)
    ]
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO companies VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def store_sample(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    rows = [(r.company_number, r.stratum, int(r.stratum_pop), int(r.stratum_n), float(r.weight),
             int(r.seed), _now()) for r in df.itertuples(index=False)]
    with conn:
        conn.execute("DELETE FROM sample")
        conn.executemany("INSERT INTO sample VALUES(?,?,?,?,?,?,?)", rows)


def _insert_candidates(conn: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO candidates(company_number,vat,kind,source,url,context,checksum_ok,cn_linked,found_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)", list(rows))


def store_corpus_pairs(conn: sqlite3.Connection, res: WetResult, source: str = "cc_wet") -> None:
    _insert_candidates(conn, [
        (p["company_number"], p["vat"], p["kind"], source, p["url"], p["context"], p["checksum_ok"], 1, _now())
        for p in res.pairs])
    s = res.stats
    with conn:
        conn.execute(
            "INSERT INTO scan_log(source,unit,pages,pages_with_vat_kw,pages_with_vat,pages_with_both,pairs,skipped_multi,seconds,finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (source, s.unit, s.pages, s.pages_with_vat_kw, s.pages_with_vat, s.pages_with_both,
             s.pairs, s.skipped_multi, s.seconds, _now()))


# ---------------------------------------------------------------------------- discovery stages

def run_websites(conn: sqlite3.Connection, settings: Settings, limit: int | None = None,
                 workers: int = 8, min_evidence: str = "medium") -> dict:
    todo = conn.execute(
        "SELECT co.company_number, co.name, co.postcode FROM sample s JOIN companies co USING(company_number) "
        "WHERE s.company_number NOT IN (SELECT company_number FROM domains) ORDER BY s.company_number"
    ).fetchall()
    if limit:
        todo = todo[:limit]
    fetcher = PoliteFetcher(settings.user_agent, settings.http_delay, settings.http_timeout)
    stats = defaultdict(int)

    def work(row):
        return row["company_number"], scan_company(dict(row), fetcher, settings.max_pages_per_site, min_evidence)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, r) for r in todo]
        for f in tqdm(as_completed(futs), total=len(futs), desc="websites"):
            cn, sc = f.result()
            status = "found" if sc.domain else "none_found"
            with conn:
                conn.execute("INSERT OR REPLACE INTO domains VALUES(?,?,?,?,?,?,?,?)",
                             (cn, sc.domain, sc.evidence, sc.detail, json.dumps(sc.tried), sc.n_pages, status, _now()))
            _insert_candidates(conn, [
                (cn, h["vat"], h["kind"], "website", h["url"], h["context"], h["checksum_ok"],
                 1 if sc.evidence == "strong" else 0, _now()) for h in sc.hits])
            stats[status] += 1
            stats["candidates"] += len(sc.hits)
    return dict(stats)


def run_peppol(conn: sqlite3.Connection, settings: Settings, limit: int | None = None) -> dict:
    todo = conn.execute(
        "SELECT co.company_number, co.name FROM sample s JOIN companies co USING(company_number) ORDER BY s.company_number"
    ).fetchall()
    if limit:
        todo = todo[:limit]
    n_cand = errors = 0
    for row in tqdm(todo, desc="peppol"):
        try:
            matches = peppol_src.search_by_name(row["name"], settings.user_agent)
        except Exception:
            errors += 1
            continue
        cands = peppol_src.extract_vat_candidates(matches, row["name"])
        _insert_candidates(conn, [
            (row["company_number"], c["vat"], c["kind"], "peppol", c["url"], c["context"],
             int(checksum_ok(c["vat"])), 0, _now()) for c in cands])
        n_cand += len(cands)
    with conn:
        conn.execute(
            "INSERT INTO scan_log(source,unit,pages,pages_with_vat_kw,pages_with_vat,pages_with_both,pairs,skipped_multi,seconds,finished_at) "
            "VALUES('peppol','sample',?,0,0,0,?,0,0,?)", (len(todo), n_cand, _now()))
    return {"queried": len(todo), "candidates": n_cand, "errors": errors}


# ---------------------------------------------------------------------------- verification

def pending_vrns(conn: sqlite3.Connection, sources: list[str] | None = None,
                 limit: int | None = None, seed: int = 42) -> list[str]:
    q = ("SELECT DISTINCT c.vat FROM candidates c WHERE c.checksum_ok=1 "
         "AND c.company_number IN (SELECT company_number FROM companies) "
         "AND c.vat NOT IN (SELECT vrn FROM hmrc)")
    params: list = []
    if sources:
        q += f" AND c.source IN ({','.join('?' * len(sources))})"
        params += sources
    vrns = sorted(r[0] for r in conn.execute(q, params))
    if limit and len(vrns) > limit:
        vrns = random.Random(seed).sample(vrns, limit)
    return vrns


def run_verify(conn: sqlite3.Connection, client: HMRCClient, vrns: list[str]) -> dict:
    stats = defaultdict(int)
    try:
        for v in tqdm(vrns, desc="hmrc"):
            stats[client.lookup(v).status] += 1
    except CallBudgetExceeded as e:
        stats["stopped_budget"] = 1
        print(f"STOPPED: {e}")
    stats["calls_made"] = client.calls
    return dict(stats)


# ---------------------------------------------------------------------------- decision

def run_decide(conn: sqlite3.Connection, th: Thresholds = Thresholds()) -> dict:
    rows = conn.execute("""
        SELECT c.company_number, c.vat,
               group_concat(DISTINCT c.source) AS sources,
               count(DISTINCT c.source || '|' || c.url) AS n_src,
               max(c.cn_linked) AS cn_linked,
               h.name AS hname, h.postcode AS hpc,
               co.name AS cname, co.prev_names AS prev, co.postcode AS cpc,
               d.evidence AS dev
        FROM candidates c
        JOIN hmrc h ON h.vrn = c.vat AND h.status = 'valid'
        JOIN companies co ON co.company_number = c.company_number
        LEFT JOIN domains d ON d.company_number = c.company_number
        WHERE c.checksum_ok = 1
        GROUP BY c.company_number, c.vat
    """).fetchall()

    scored = []
    for r in rows:
        names = [r["cname"]] + [p for p in (r["prev"] or "").split("|") if p]
        sc, _ = best_name_score(r["hname"], names)
        scored.append((r, sc, postcode_relation(r["cpc"], r["hpc"])))

    vat_cos: dict[str, set] = defaultdict(set)
    co_vats: dict[str, set] = defaultdict(set)
    for r, sc, _ in scored:
        if sc >= th.medium_name:
            vat_cos[r["vat"]].add(r["company_number"])
            co_vats[r["company_number"]].add(r["vat"])

    out = []
    counts: dict[str, int] = defaultdict(int)
    for r, sc, pc in scored:
        srcs = (r["sources"] or "").split(",")
        site_linked = "website" in srcs and r["dev"] in ("strong", "medium")
        d = decide(sc, pc, bool(r["cn_linked"]), site_linked,
                   vat_shared=len(vat_cos.get(r["vat"], ())) or 1,
                   company_multi_vat=len(co_vats.get(r["company_number"], ())) or 1, th=th)
        counts[d.tier] += 1
        out.append((r["company_number"], r["vat"], d.tier, sc, pc, "; ".join(d.reasons),
                    r["n_src"], r["sources"], _now()))
    with conn:
        conn.execute("DELETE FROM decisions")
        conn.executemany("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)", out)
    return dict(counts)


def compute_outcomes(conn: sqlite3.Connection) -> dict:
    sample = [r[0] for r in conn.execute("SELECT company_number FROM sample")]
    tiers = defaultdict(set)
    for r in conn.execute("SELECT company_number, tier FROM decisions"):
        tiers[r["company_number"]].add(r["tier"])
    cands = defaultdict(list)
    for r in conn.execute(
            "SELECT c.company_number, c.checksum_ok, h.status AS hs FROM candidates c LEFT JOIN hmrc h ON h.vrn=c.vat"):
        cands[r["company_number"]].append((r["checksum_ok"], r["hs"]))
    dom = {r["company_number"]: r for r in conn.execute("SELECT * FROM domains")}

    counts: dict[str, int] = defaultdict(int)
    rows = []
    for cn in sample:
        t = tiers.get(cn, set())
        cs = cands.get(cn, [])
        if "HIGH" in t:
            o, det = "verified_high", ""
        elif "MEDIUM" in t:
            o, det = "needs_review", ""
        elif "LOW" in t:
            o, det = "rejected_mismatch", ""
        elif cs:
            valid_cs = [x for x in cs if x[0]]
            if not valid_cs:
                o, det = "checksum_failed_only", ""
            elif any(hs is None for _, hs in valid_cs):
                o, det = "pending_verification", ""
            elif all(hs == "not_found" for _, hs in valid_cs):
                o, det = "hmrc_not_found", ""
            else:
                o, det = "pending_verification", "hmrc errors"
        elif cn in dom and dom[cn]["status"] == "found":
            o, det = "no_vat_on_verified_site", dom[cn]["evidence"]
        elif cn in dom:
            o, det = "no_domain_found", ""
        else:
            o, det = "not_attempted", ""
        counts[o] += 1
        rows.append((cn, o, det))
    with conn:
        conn.execute("DELETE FROM outcomes")
        conn.executemany("INSERT INTO outcomes VALUES(?,?,?)", rows)
    return dict(counts)
