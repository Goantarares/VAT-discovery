"""Source 2: Common Crawl WET files (plain-text extractions of crawled pages).

Why this shape: the VAT number lives in the footer/T&Cs of millions of pages. Instead of mapping
company -> website first (hard), scan text in bulk and key on what a page proves about itself:
a page that shows both a company number and a VAT number is, very likely, the same entity. The
company number is the join key, so no domain guessing is needed.

Precision guards: skip pages with many company numbers or many VAT numbers (directories,
aggregators, accountants' pages); only keep checksum-valid VAT numbers. Ownership is still decided
later by HMRC name/address matching.

Yield accounting: every file scanned logs page counts so you can extrapolate (see README).
"""
from __future__ import annotations

import gzip
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import requests
from warcio.archiveiterator import ArchiveIterator

from ..extract import VAT_WORD, find_company_number_spans, find_vat_hits

CC_BASE = "https://data.commoncrawl.org/"
MAX_TEXT = 500_000
MAX_CNS_PER_PAGE = 3
MAX_VATS_PER_PAGE = 3
MAX_PAIR_DISTANCE = 300     # characters between a VAT number and its company number
AMBIGUITY_MARGIN = 40       # runner-up company number must be this much farther away


@dataclass
class WetStats:
    unit: str
    pages: int = 0
    pages_with_vat_kw: int = 0
    pages_with_vat: int = 0
    pages_with_both: int = 0
    pairs: int = 0
    skipped_multi: int = 0
    skipped_far: int = 0         # VAT with no company number within MAX_PAIR_DISTANCE
    skipped_ambiguous: int = 0   # two different company numbers about equally close
    seconds: float = 0.0


@dataclass
class WetResult:
    stats: WetStats
    pairs: list[dict] = field(default_factory=list)


def wet_paths(crawl: str) -> list[str]:
    """List WET file paths for a crawl id such as 'CC-MAIN-2025-30'."""
    r = requests.get(f"{CC_BASE}crawl-data/{crawl}/wet.paths.gz", timeout=60)
    r.raise_for_status()
    return gzip.decompress(r.content).decode().split()


def _open(path_or_url: str):
    if path_or_url.startswith("http"):
        r = requests.get(path_or_url, stream=True, timeout=120)
        r.raise_for_status()
        return r.raw
    return open(path_or_url, "rb")


def iter_wet_texts(path_or_url: str) -> Iterator[tuple[str, str]]:
    stream = _open(path_or_url)
    try:
        for rec in ArchiveIterator(stream):
            if rec.rec_type != "conversion":
                continue
            uri = rec.rec_headers.get_header("WARC-Target-URI") or ""
            raw = rec.content_stream().read(MAX_TEXT * 2)
            yield uri, raw.decode("utf-8", errors="replace")[:MAX_TEXT]
    finally:
        try:
            stream.close()
        except Exception:
            pass


def nearest_company(positions: tuple, spans: list[tuple[str, int]]) -> tuple[str | None, str]:
    """Company number closest to any occurrence of a VAT number: (cn, '') or (None, reason)."""
    if not positions:
        return None, "far"
    best: dict[str, int] = {}
    for cn, cp in spans:
        d = min(abs(cp - vp) for vp in positions)
        if cn not in best or d < best[cn]:
            best[cn] = d
    ranked = sorted(best.items(), key=lambda kv: kv[1])
    cn, d = ranked[0]
    if d > MAX_PAIR_DISTANCE:
        return None, "far"
    if len(ranked) > 1 and ranked[1][1] - d < AMBIGUITY_MARGIN:
        return None, "ambiguous"
    return cn, ""


def scan_wet(path_or_url: str, target_numbers: set[str] | None = None,
             max_pages: int | None = None) -> WetResult:
    """Scan one WET file. If `target_numbers` is given, only pairs for those companies are kept."""
    t0 = time.time()
    stats = WetStats(unit=path_or_url.rsplit("/", 1)[-1])
    pairs: list[dict] = []
    for uri, text in iter_wet_texts(path_or_url):
        stats.pages += 1
        if max_pages and stats.pages > max_pages:
            break
        if not VAT_WORD.search(text):
            continue
        stats.pages_with_vat_kw += 1
        hits = [h for h in find_vat_hits(text) if h.checksum_ok and h.keyword_near]
        if not hits:
            continue
        stats.pages_with_vat += 1
        spans = find_company_number_spans(text)
        if not spans:
            continue
        cns = {cn for cn, _ in spans}
        stats.pages_with_both += 1
        if len(cns) > MAX_CNS_PER_PAGE or len(hits) > MAX_VATS_PER_PAGE:
            stats.skipped_multi += 1
            continue
        for h in hits:
            cn, why = nearest_company(h.positions, spans)
            if cn is None:
                if why == "ambiguous":
                    stats.skipped_ambiguous += 1
                else:
                    stats.skipped_far += 1
                continue
            if target_numbers is not None and cn not in target_numbers:
                continue
            pairs.append({"company_number": cn, "vat": h.vat, "kind": h.kind, "url": uri,
                          "context": h.context, "checksum_ok": 1})
    stats.pairs = len(pairs)
    stats.seconds = round(time.time() - t0, 1)
    return WetResult(stats, pairs)
