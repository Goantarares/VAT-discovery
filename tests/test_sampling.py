import pandas as pd

from vatdisc import companies_house as ch
from vatdisc.sampling import allocate, draw_sample, kish_effective_n, representativeness


def _fn(path):
    return lambda: (ch.eligible(c) for c in ch.read_chunks(path, chunksize=700))


def test_read_and_clean(ch_csv):
    df = pd.concat(list(ch.read_chunks(ch_csv, chunksize=1000)))
    assert {"company_number", "acct_group", "age_bucket", "sic_section", "postcode"} <= set(df.columns)
    assert df["company_number"].str.len().eq(8).all()          # stray-space header handled
    assert set(df["acct_group"]) >= {"micro", "small", "full", "dormant"}
    assert df.loc[df["sic_primary"].eq("62012"), "sic_section"].eq("J").all()
    assert (df["prev_names"] != "").sum() > 0


def test_eligibility_filters(ch_csv):
    df = pd.concat(list(ch.read_chunks(ch_csv)))
    el = ch.eligible(df)
    assert (el["status"] == "Active").all()
    assert (el["acct_group"] != "dormant").all()
    assert el["category"].str.lower().isin(ch.DEFAULT_CATEGORIES).all()


def test_allocation():
    a = allocate({"a": 1000, "b": 100, "c": 3}, n=50, min_per_stratum=5)
    assert a["c"] == 3 and a["b"] >= 5 and sum(a.values()) <= 50 + 5
    assert all(v <= c for v, c in zip(a.values(), (1000, 100, 3)))


def test_sample_is_deterministic_weighted_and_representative(ch_csv):
    s1, info = draw_sample(_fn(ch_csv), n=300, seed=42, min_per_stratum=5)
    s2, _ = draw_sample(_fn(ch_csv), n=300, seed=42, min_per_stratum=5)
    s3, _ = draw_sample(_fn(ch_csv), n=300, seed=43, min_per_stratum=5)
    assert sorted(s1["company_number"]) == sorted(s2["company_number"])
    assert sorted(s1["company_number"]) != sorted(s3["company_number"])
    assert s1["company_number"].is_unique
    # weights reproduce the population size per stratum
    pop = s1.groupby("stratum")["weight"].sum().round().astype(int)
    for stratum, total in pop.items():
        assert total == info["population_by_stratum"][stratum]
    assert abs(s1["weight"].sum() - info["population_total"]) < 1
    rep = representativeness(s1, info)
    # a single draw of ~300 has sampling noise of about 0.023 per share (sqrt(p(1-p)/n_eff)): allow 4 sigma
    n_eff = kish_effective_n(s1["weight"])
    tol = 4 * (0.25 / n_eff) ** 0.5
    assert (rep["sample_weighted"] - rep["population"]).abs().max() < tol
    assert n_eff <= len(s1)


def test_sampler_is_unbiased_across_seeds(ch_csv):
    """Weighted SIC shares should centre on the population shares when averaged over many seeds."""
    devs = []
    for seed in range(30):
        s, info = draw_sample(_fn(ch_csv), n=300, seed=seed, min_per_stratum=5)
        rep = representativeness(s, info)
        devs.append(rep["sample_weighted"] - rep["population"])
    mean_dev = pd.DataFrame(devs).mean().abs()
    assert mean_dev.max() < 0.012   # SE of the mean is ~0.004; 0.012 is about 3 SE
