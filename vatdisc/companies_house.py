"""Companies House 'Free Company Data Product' loader.

The bulk CSV has ~5M rows, so everything here streams in chunks. Column names in the real file
have stray leading spaces (e.g. ' CompanyNumber'); we strip them. Category/status vocabularies
are not hard-coded as truth: run `python -m vatdisc.cli inspect-ch` on your snapshot and adjust
the eligibility filters if the values differ from the defaults below.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable, Iterable, Iterator

import numpy as np
import pandas as pd
import requests

BULK_BASE = "https://download.companieshouse.gov.uk/"

PREV_COLS = [f"PreviousName_{i}.CompanyName" for i in range(1, 11)]
WANTED = {
    "CompanyName", "CompanyNumber",
    "RegAddress.AddressLine1", "RegAddress.AddressLine2", "RegAddress.PostTown",
    "RegAddress.County", "RegAddress.Country", "RegAddress.PostCode",
    "CompanyCategory", "CompanyStatus", "IncorporationDate",
    "Accounts.AccountCategory", "SICCode.SicText_1",
    *PREV_COLS,
}

# SIC 2007 division -> section letter
_SECTION_RANGES = [
    ("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39), ("F", 41, 43),
    ("G", 45, 47), ("H", 49, 53), ("I", 55, 56), ("J", 58, 63), ("K", 64, 66), ("L", 68, 68),
    ("M", 69, 75), ("N", 77, 82), ("O", 84, 84), ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93),
    ("S", 94, 96), ("T", 97, 98), ("U", 99, 99),
]
DIV_TO_SECTION = {f"{d:02d}": s for s, lo, hi in _SECTION_RANGES for d in range(lo, hi + 1)}

DEFAULT_CATEGORIES = (
    "private limited company", "public limited company", "limited liability partnership",
)


def bulk_url(month_first: dt.date) -> str:
    return f"{BULK_BASE}BasicCompanyDataAsOneFile-{month_first:%Y-%m-01}.zip"


def candidate_bulk_urls(today: dt.date | None = None) -> list[str]:
    """Current month's file, then the previous month's (publication lags the 1st by hours-days)."""
    today = today or dt.date.today()
    first = today.replace(day=1)
    prev = (first - dt.timedelta(days=1)).replace(day=1)
    return [bulk_url(first), bulk_url(prev)]


def download(url: str, dest: Path, chunk: int = 1 << 20) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for part in r.iter_content(chunk):
                f.write(part)
    return dest


# ------------------------------------------------------------------ classification helpers

def acct_group_of(raw: str) -> str:
    s = (raw or "").upper()
    if not s:
        return "unknown"
    if "DORMANT" in s:
        return "dormant"
    if "NO ACCOUNTS" in s:
        return "none_filed"
    if "GROUP" in s:
        return "group"
    if "MICRO" in s:
        return "micro"
    if "SMALL" in s or "TOTAL EXEMPTION" in s or "ABRIDGED" in s:
        return "small"
    if "FULL" in s or "MEDIUM" in s or "LARGE" in s or "AUDIT" in s:
        return "full"
    if "SUBSIDIARY" in s:
        return "subsidiary"
    return "other"


def _map_unique(s: pd.Series, fn: Callable[[str], str]) -> pd.Series:
    mapping = {u: fn(u) for u in s.unique()}
    return s.map(mapping)


def _col(raw: pd.DataFrame, name: str) -> pd.Series:
    if name in raw.columns:
        return raw[name].fillna("").astype(str)
    return pd.Series("", index=raw.index, dtype=str)


def clean_chunk(raw: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    raw = raw.copy()
    raw.columns = [c.strip() for c in raw.columns]
    as_of = as_of or pd.Timestamp.today().normalize()

    df = pd.DataFrame(index=raw.index)
    df["company_number"] = _col(raw, "CompanyNumber").str.strip().str.upper()
    df["name"] = _col(raw, "CompanyName").str.strip()
    df["status"] = _col(raw, "CompanyStatus").str.strip()
    df["category"] = _col(raw, "CompanyCategory").str.strip()
    df["accounts_category"] = _col(raw, "Accounts.AccountCategory").str.strip()
    df["acct_group"] = _map_unique(df["accounts_category"], acct_group_of)

    inc = pd.to_datetime(_col(raw, "IncorporationDate"), format="%d/%m/%Y", errors="coerce")
    df["incorporation_date"] = inc.dt.strftime("%Y-%m-%d").fillna("")
    age = (as_of - inc).dt.days / 365.25
    df["age_years"] = age
    df["age_bucket"] = pd.cut(
        age, bins=[-np.inf, 2, 5, 15, np.inf], labels=["<2y", "2-5y", "5-15y", "15y+"]
    ).astype(object).where(age.notna(), "unknown")

    sic = _col(raw, "SICCode.SicText_1").str.extract(r"^\s*(\d{4,5})")[0].fillna("")
    df["sic_primary"] = sic
    df["sic_section"] = sic.str[:2].map(DIV_TO_SECTION).fillna("?")

    df["postcode"] = _col(raw, "RegAddress.PostCode").str.strip().str.upper()
    addr_parts = ["RegAddress.AddressLine1", "RegAddress.AddressLine2", "RegAddress.PostTown",
                  "RegAddress.County", "RegAddress.Country", "RegAddress.PostCode"]
    joined = pd.Series("", index=raw.index)
    for p in addr_parts:
        joined = joined + "|" + _col(raw, p).str.strip()
    df["address"] = (joined.str.replace(r"\|+", "|", regex=True).str.strip("|")
                     .str.replace("|", ", ", regex=False))

    prev = pd.Series("", index=raw.index)
    for p in PREV_COLS:
        prev = prev + "|" + _col(raw, p).str.strip()
    df["prev_names"] = prev.str.replace(r"\|+", "|", regex=True).str.strip("|")  # pipe-separated
    return df


def read_chunks(path: str | Path, chunksize: int = 250_000) -> Iterator[pd.DataFrame]:
    """Stream the bulk file (a .zip with one CSV, or a plain .csv) as cleaned DataFrames."""
    reader = pd.read_csv(
        path,
        usecols=lambda c: c.strip() in WANTED,
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
        encoding_errors="replace",
        on_bad_lines="skip",
    )
    for raw in reader:
        yield clean_chunk(raw)


def eligible(
    df: pd.DataFrame,
    statuses: Iterable[str] = ("active",),
    categories: Iterable[str] = DEFAULT_CATEGORIES,
    include_dormant: bool = False,
) -> pd.DataFrame:
    """Rows that could plausibly be a supplier: live, a company-like legal form, not dormant."""
    m = df["status"].str.lower().isin({s.lower() for s in statuses})
    m &= df["category"].str.lower().isin({c.lower() for c in categories})
    m &= df["company_number"].ne("") & df["name"].ne("")
    if not include_dormant:
        m &= df["acct_group"].ne("dormant")
    return df[m]


def load_companies_for(path: str | Path, numbers: set[str]) -> pd.DataFrame:
    """Pull only the given company numbers out of the bulk file (used for corpus-found pairs)."""
    parts = [c[c["company_number"].isin(numbers)] for c in read_chunks(path)]
    return pd.concat(parts) if parts else pd.DataFrame()


def inspect(path: str | Path, max_chunks: int | None = None) -> dict[str, pd.Series]:
    """Value counts of the categorical columns, so filters can be checked against reality."""
    acc: dict[str, pd.Series] = {}
    for i, c in enumerate(read_chunks(path)):
        for col in ("status", "category", "accounts_category", "acct_group", "age_bucket", "sic_section"):
            vc = c[col].value_counts()
            acc[col] = vc if col not in acc else acc[col].add(vc, fill_value=0)
        if max_chunks and i + 1 >= max_chunks:
            break
    return {k: v.sort_values(ascending=False).astype(int) for k, v in acc.items()}
