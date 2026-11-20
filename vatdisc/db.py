"""SQLite schema and connection helper. Everything the pipeline learns is persisted so stages are resumable."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies(
    company_number TEXT PRIMARY KEY,
    name TEXT, prev_names TEXT, status TEXT, category TEXT, accounts_category TEXT,
    sic_section TEXT, incorporation_date TEXT, postcode TEXT, address TEXT
);
CREATE TABLE IF NOT EXISTS sample(
    company_number TEXT PRIMARY KEY,
    stratum TEXT, stratum_pop INTEGER, stratum_n INTEGER, weight REAL,
    seed INTEGER, drawn_at TEXT
);
CREATE TABLE IF NOT EXISTS domains(
    company_number TEXT PRIMARY KEY,
    domain TEXT, evidence TEXT, detail TEXT, tried TEXT, n_pages INTEGER,
    status TEXT, updated_at TEXT
);
-- every (company, VAT-looking number) pair any source produced, before verification
CREATE TABLE IF NOT EXISTS candidates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_number TEXT, vat TEXT, kind TEXT, source TEXT, url TEXT, context TEXT,
    checksum_ok INTEGER, cn_linked INTEGER, found_at TEXT,
    UNIQUE(company_number, vat, source, url)
);
CREATE INDEX IF NOT EXISTS idx_cand_vat ON candidates(vat);
CREATE INDEX IF NOT EXISTS idx_cand_cn ON candidates(company_number);
-- HMRC responses, cached by VRN. Transient errors are never cached.
CREATE TABLE IF NOT EXISTS hmrc(
    vrn TEXT PRIMARY KEY,
    status TEXT, name TEXT, address TEXT, postcode TEXT, http_status INTEGER, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions(
    company_number TEXT, vat TEXT, tier TEXT, name_score REAL, postcode_match TEXT,
    reasons TEXT, n_sources INTEGER, sources TEXT, decided_at TEXT,
    PRIMARY KEY(company_number, vat)
);
CREATE TABLE IF NOT EXISTS audit(
    company_number TEXT, vat TEXT, tier TEXT, label TEXT, notes TEXT,
    PRIMARY KEY(company_number, vat)
);
CREATE TABLE IF NOT EXISTS outcomes(
    company_number TEXT PRIMARY KEY, outcome TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS scan_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, unit TEXT, pages INTEGER, pages_with_vat_kw INTEGER, pages_with_vat INTEGER,
    pages_with_both INTEGER, pairs INTEGER, skipped_multi INTEGER, seconds REAL, finished_at TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
