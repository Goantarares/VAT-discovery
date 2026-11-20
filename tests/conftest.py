"""Shared fixtures: a synthetic Companies House-shaped CSV (with the real file's stray-space headers)."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HEADER = [
    "CompanyName", " CompanyNumber", "RegAddress.CareOf", "RegAddress.POBox", "RegAddress.AddressLine1",
    " RegAddress.AddressLine2", "RegAddress.PostTown", "RegAddress.County", "RegAddress.Country",
    "RegAddress.PostCode", "CompanyCategory", "CompanyStatus", "CountryOfOrigin", "DissolutionDate",
    "IncorporationDate", "Accounts.AccountCategory", "SICCode.SicText_1",
] + [f"PreviousName_{i}.CompanyName" for i in range(1, 11)]

ACCOUNTS = ["MICRO ENTITY", "SMALL", "FULL", "DORMANT", "NO ACCOUNTS FILED", "TOTAL EXEMPTION FULL"]
SICS = ["62012 - Software", "43210 - Electrical", "47110 - Retail", "70229 - Consulting", "None Supplied"]


def make_ch_csv(path: Path, n: int = 3000, seed: int = 1) -> Path:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        year = rng.choice([2024, 2022, 2018, 2010, 2000])
        rows.append({
            "CompanyName": f"TEST COMPANY {i} LIMITED",
            " CompanyNumber": f"{i + 1000:08d}",
            "RegAddress.AddressLine1": f"{i} High Street",
            "RegAddress.PostTown": "London",
            "RegAddress.PostCode": f"E{i % 20 + 1} {i % 9}AB",
            "CompanyCategory": rng.choice(["Private Limited Company"] * 8 + ["Limited Partnership"]),
            "CompanyStatus": rng.choice(["Active"] * 9 + ["Liquidation"]),
            "IncorporationDate": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{year}",
            "Accounts.AccountCategory": rng.choice(ACCOUNTS),
            "SICCode.SicText_1": rng.choice(SICS),
            "PreviousName_1.CompanyName": "OLD NAME LTD" if i % 50 == 0 else "",
        })
    pd.DataFrame(rows, columns=HEADER).fillna("").to_csv(path, index=False)
    return path


@pytest.fixture(scope="session")
def ch_csv(tmp_path_factory) -> Path:
    return make_ch_csv(tmp_path_factory.mktemp("ch") / "BasicCompanyData.csv")
