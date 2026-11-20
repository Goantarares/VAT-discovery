"""Stratified random sampling of the eligible Companies House population.

Design goals
  * Independent of anything we know about VAT or websites: the draw looks only at Companies House
    attributes, so it cannot be biased toward companies that publish their number.
  * Deterministic and streaming: each company gets a pseudo-random key = hash(company_number, seed);
    within each stratum we keep the n_h smallest keys (a bottom-k sample, i.e. simple random
    sampling without replacement). Same seed + same snapshot => same sample.
  * Weighted: weight = N_h / n_h so results can be reweighted to the whole eligible population,
    even though allocation floors oversample small strata.
Strata = accounts group x age bucket (VAT registration correlates strongly with size and age).
SIC section is a reporting dimension, checked after the fact by `representativeness`.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Callable, Iterable

import numpy as np
import pandas as pd


def add_stratum(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["stratum"] = df["acct_group"] + "|" + df["age_bucket"]
    return df


def sampling_key(company_numbers: pd.Series, seed: int) -> np.ndarray:
    h = pd.util.hash_pandas_object(company_numbers + f"#{seed}", index=False).to_numpy()
    return h.astype("float64") / 2.0**64


def allocate(counts: dict[str, int], n: int, min_per_stratum: int = 5) -> dict[str, int]:
    """Proportional allocation with a per-stratum floor. The result can slightly exceed `n`
    when floors dominate (many strata, small n); it never exceeds a stratum's population."""
    total = sum(counts.values())
    if total == 0:
        return {}
    alloc = {s: min(c, max(min_per_stratum, int(round(n * c / total)))) for s, c in counts.items()}
    # trim down to n if proportional rounding overshot (never below the floor)
    while sum(alloc.values()) > n:
        movable = [s for s in alloc if alloc[s] > min(min_per_stratum, counts[s])]
        if not movable:
            break
        s = max(movable, key=lambda k: alloc[k])
        alloc[s] -= 1
    # top up to n using remaining capacity, largest strata first
    while sum(alloc.values()) < n:
        room = [s for s in alloc if alloc[s] < counts[s]]
        if not room:
            break
        s = max(room, key=lambda k: counts[k] - alloc[k])
        alloc[s] += 1
    return alloc


def draw_sample(
    chunks_fn: Callable[[], Iterable[pd.DataFrame]],
    n: int,
    seed: int,
    min_per_stratum: int = 5,
) -> tuple[pd.DataFrame, dict]:
    """`chunks_fn` must return a fresh iterable of *eligible, cleaned* chunks each call (two passes)."""
    # pass 1: population counts
    strata: Counter = Counter()
    sic: Counter = Counter()
    for df in chunks_fn():
        df = add_stratum(df)
        strata.update(df["stratum"].value_counts().to_dict())
        sic.update(df["sic_section"].value_counts().to_dict())
    alloc = allocate(dict(strata), n, min_per_stratum)

    # pass 2: bottom-k by hash key per stratum
    best: dict[str, pd.DataFrame] = {}
    for df in chunks_fn():
        df = add_stratum(df)
        df["_key"] = sampling_key(df["company_number"], seed)
        for s, g in df.groupby("stratum"):
            k = alloc.get(s, 0)
            if k == 0:
                continue
            merged = g if s not in best else pd.concat([best[s], g])
            best[s] = merged.nsmallest(k, "_key")

    out = pd.concat(best.values()).drop(columns="_key").reset_index(drop=True) if best else pd.DataFrame()
    if not out.empty:
        out["stratum_pop"] = out["stratum"].map(dict(strata)).astype(int)
        out["stratum_n"] = out["stratum"].map(out["stratum"].value_counts()).astype(int)
        out["weight"] = out["stratum_pop"] / out["stratum_n"]
        out["seed"] = seed
    info = {
        "seed": seed,
        "population_total": int(sum(strata.values())),
        "population_by_stratum": {k: int(v) for k, v in strata.items()},
        "population_by_sic_section": {k: int(v) for k, v in sic.items()},
        "allocation": alloc,
        "n_drawn": int(len(out)),
        "min_per_stratum": min_per_stratum,
    }
    return out, info


def representativeness(sample: pd.DataFrame, info: dict) -> pd.DataFrame:
    """Compare SIC-section shares: population vs weighted sample vs raw (unweighted) sample.
    The weighted share should track the population; the raw share shows the effect of floors."""
    pop = pd.Series(info["population_by_sic_section"], dtype=float)
    pop_share = pop / pop.sum()
    w = sample.groupby("sic_section")["weight"].sum()
    wtd_share = (w / w.sum()).reindex(pop.index).fillna(0.0)
    raw = sample["sic_section"].value_counts()
    raw_share = (raw / raw.sum()).reindex(pop.index).fillna(0.0)
    t = pd.DataFrame({"population": pop_share, "sample_weighted": wtd_share, "sample_raw": raw_share})
    t["n_in_sample"] = raw.reindex(pop.index).fillna(0).astype(int)
    return t.sort_values("population", ascending=False)


def kish_effective_n(weights: Iterable[float]) -> float:
    w = np.asarray(list(weights), dtype=float)
    if len(w) == 0 or w.sum() == 0:
        return 0.0
    return float(w.sum() ** 2 / (w**2).sum())
