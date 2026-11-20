"""Command line entry point:  python -m vatdisc.cli <command> [options]

Typical order
  inspect-ch / download-ch -> sample -> scan-websites -> (scan-wet -> link-corpus) -> (peppol)
  -> verify -> decide -> outcomes -> audit-export -> (label by hand) -> audit-import -> audit-report -> report
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import companies_house as ch
from . import pipeline as pl
from .audit import export_audit, import_audit, precision_report
from .config import get_settings
from .db import connect
from .evaluate import build_report
from .hmrc import HMRCClient
from .matching import Thresholds
from .sampling import draw_sample, representativeness
from .sources import commoncrawl_wet as wet


def _conn():
    s = get_settings()
    return s, connect(s.db_path)


def cmd_inspect_ch(a):
    for col, vc in ch.inspect(a.file, a.max_chunks).items():
        print(f"\n== {col}\n{vc.head(25).to_string()}")


def cmd_download_ch(a):
    s = get_settings()
    urls = [a.url] if a.url else ch.candidate_bulk_urls()
    for u in urls:
        dest = s.data_dir / u.rsplit("/", 1)[-1]
        try:
            print("downloading", u)
            ch.download(u, dest)
            print("saved", dest)
            return
        except Exception as e:
            print("failed:", e)
    sys.exit("could not download; fetch the file manually from https://download.companieshouse.gov.uk/en_output.html")


def cmd_sample(a):
    s, conn = _conn()
    seed = a.seed if a.seed is not None else s.seed
    cats = tuple(x.strip().lower() for x in a.categories.split(",")) if a.categories else ch.DEFAULT_CATEGORIES
    fn = lambda: (ch.eligible(c, categories=cats, include_dormant=a.include_dormant) for c in ch.read_chunks(a.file))
    sample, info = draw_sample(fn, a.n, seed, a.min_per_stratum)
    pl.store_companies(conn, sample)
    pl.store_sample(conn, sample)
    (s.data_dir / "sample_info.json").write_text(json.dumps(info, indent=2))
    rep = representativeness(sample, info)
    rep.to_csv(s.data_dir / "representativeness_sic.csv")
    print(f"drew {len(sample)} companies from {info['population_total']:,} eligible (seed={seed})")
    print(rep.round(4).to_string())


def cmd_scan_websites(a):
    s, conn = _conn()
    print(pl.run_websites(conn, s, a.limit, a.workers, a.min_evidence))


def cmd_scan_wet(a):
    s, conn = _conn()
    if a.file:
        units = a.file
    else:
        paths = wet.wet_paths(a.crawl)[: a.max_files]
        units = [wet.CC_BASE + p for p in paths]
    for u in units:
        res = wet.scan_wet(u, max_pages=a.max_pages)
        pl.store_corpus_pairs(conn, res)
        print(res.stats)


def cmd_link_corpus(a):
    s, conn = _conn()
    nums = {r[0] for r in conn.execute(
        "SELECT DISTINCT company_number FROM candidates WHERE source='cc_wet'") if r[0]}
    df = ch.load_companies_for(a.file, nums)
    df = df.drop_duplicates("company_number")
    n = pl.store_companies(conn, df) if len(df) else 0
    print(f"{len(nums)} company numbers seen in corpus pairs; {n} found in Companies House file")


def cmd_peppol(a):
    s, conn = _conn()
    print(pl.run_peppol(conn, s, a.limit))


def cmd_verify(a):
    s, conn = _conn()
    if "test-api" in s.hmrc_base_url and not a.allow_sandbox:
        sys.exit("HMRC_BASE_URL is the SANDBOX. It only knows mock numbers, so every real number would come back "
                 "'not found' and be cached in data/vatdisc.sqlite as if that were true. Switch to production "
                 "credentials, or pass --allow-sandbox if you really mean it.")
    srcs = a.sources.split(",") if a.sources else None
    vrns = pl.pending_vrns(conn, srcs, a.limit, s.seed)
    print(f"{len(vrns)} distinct checksum-valid numbers to verify (budget {s.hmrc_max_calls})")
    print(pl.run_verify(conn, HMRCClient(s, conn), vrns))


def cmd_decide(a):
    s, conn = _conn()
    print(pl.run_decide(conn, Thresholds(a.high_name, a.medium_name)))


def cmd_outcomes(a):
    s, conn = _conn()
    print(pl.compute_outcomes(conn))


def cmd_audit_export(a):
    s, conn = _conn()
    sheet, key = export_audit(conn, s.data_dir, a.n_high, a.n_medium, a.n_low, a.seed)
    print(f"label the 'label' column of {sheet} (correct|wrong|unsure); keep {key} aside")


def cmd_audit_import(a):
    s, conn = _conn()
    d = s.data_dir
    print(import_audit(conn, Path(a.sheet or d / "audit_sheet.csv"), Path(a.key or d / "audit_key.csv")), "labels imported")


def cmd_audit_report(a):
    s, conn = _conn()
    table, md = precision_report(conn)
    print(md)


def cmd_report(a):
    s, conn = _conn()
    _, pmd = precision_report(conn)
    build_report(conn, s.data_dir / "results.md", pmd)
    print("wrote", s.data_dir / "results.md")


def main(argv=None):
    p = argparse.ArgumentParser(prog="vatdisc")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("inspect-ch", cmd_inspect_ch); sp.add_argument("--file", required=True); sp.add_argument("--max-chunks", type=int)
    sp = add("download-ch", cmd_download_ch); sp.add_argument("--url")
    sp = add("sample", cmd_sample)
    sp.add_argument("--file", required=True); sp.add_argument("--n", type=int, default=500)
    sp.add_argument("--seed", type=int); sp.add_argument("--min-per-stratum", type=int, default=5)
    sp.add_argument("--categories", help="comma list, default: private limited, plc, llp")
    sp.add_argument("--include-dormant", action="store_true")
    sp = add("scan-websites", cmd_scan_websites)
    sp.add_argument("--limit", type=int); sp.add_argument("--workers", type=int, default=8)
    sp.add_argument("--min-evidence", default="medium", choices=["weak", "medium", "strong"])
    sp = add("scan-wet", cmd_scan_wet)
    sp.add_argument("--crawl", default="CC-MAIN-2025-30"); sp.add_argument("--max-files", type=int, default=1)
    sp.add_argument("--file", nargs="*", help="local .wet.gz files instead of downloading")
    sp.add_argument("--max-pages", type=int)
    sp = add("link-corpus", cmd_link_corpus); sp.add_argument("--file", required=True)
    sp = add("peppol", cmd_peppol); sp.add_argument("--limit", type=int)
    sp = add("verify", cmd_verify)
    sp.add_argument("--limit", type=int); sp.add_argument("--sources", help="comma list: website,cc_wet,peppol")
    sp.add_argument("--allow-sandbox", action="store_true", help="run verify against the HMRC sandbox anyway")
    sp = add("decide", cmd_decide)
    sp.add_argument("--high-name", type=float, default=95.0); sp.add_argument("--medium-name", type=float, default=85.0)
    add("outcomes", cmd_outcomes)
    sp = add("audit-export", cmd_audit_export)
    sp.add_argument("--n-high", type=int, default=60); sp.add_argument("--n-medium", type=int, default=30)
    sp.add_argument("--n-low", type=int, default=30); sp.add_argument("--seed", type=int, default=7)
    sp = add("audit-import", cmd_audit_import); sp.add_argument("--sheet"); sp.add_argument("--key")
    add("audit-report", cmd_audit_report)
    add("report", cmd_report)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
