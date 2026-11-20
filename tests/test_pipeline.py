"""End-to-end test of store -> decide -> outcomes with fake HMRC responses (no network)."""
import pandas as pd

from vatdisc import pipeline as pl
from vatdisc.audit import export_audit, import_audit, precision_report
from vatdisc.db import connect
from vatdisc.evaluate import build_report, chapman, rule_of_three, weighted_outcome_table, wilson
from vatdisc.vat import checksum_ok


def _valid(start):
    n = start
    while not checksum_ok(f"{n:09d}"):
        n += 1
    return f"{n:09d}"


def _setup(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    cos = pd.DataFrame([
        dict(company_number="00000001", name="ALPHA BUILDERS LIMITED", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="SMALL", sic_section="F", incorporation_date="2010-01-01", postcode="E1 1AA", address="x"),
        dict(company_number="00000002", name="BETA SOFTWARE LTD", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="MICRO", sic_section="J", incorporation_date="2015-01-01", postcode="M1 1AA", address="x"),
        dict(company_number="00000003", name="GAMMA FOODS LTD", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="MICRO", sic_section="C", incorporation_date="2015-01-01", postcode="B1 1AA", address="x"),
        dict(company_number="00000004", name="DELTA CONSULTING LTD", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="MICRO", sic_section="M", incorporation_date="2015-01-01", postcode="L1 1AA", address="x"),
        dict(company_number="00000005", name="EPSILON TRADING LTD", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="MICRO", sic_section="G", incorporation_date="2015-01-01", postcode="G1 1AA", address="x"),
        dict(company_number="00000006", name="ZETA LTD", prev_names="", status="Active", category="Private Limited Company",
             accounts_category="MICRO", sic_section="G", incorporation_date="2015-01-01", postcode="G1 1AA", address="x"),
    ])
    pl.store_companies(conn, cos)
    s = cos[["company_number"]].assign(stratum="micro|5-15y", stratum_pop=60, stratum_n=6, weight=10.0, seed=1)
    pl.store_sample(conn, s)
    return conn


def _hmrc(conn, vrn, status, name="", postcode=""):
    with conn:
        conn.execute("INSERT OR REPLACE INTO hmrc VALUES(?,?,?,?,?,?,?)", (vrn, status, name, "", postcode, 200, "now"))


def _cand(conn, cn, vat, source="website", linked=0, url="http://x"):
    pl._insert_candidates(conn, [(cn, vat, "keyword", source, url, "ctx", int(checksum_ok(vat)), linked, "now")])


def test_pipeline_outcomes(tmp_path):
    conn = _setup(tmp_path)
    v1, v2, v3, v4 = _valid(100_000_000), _valid(200_000_000), _valid(300_000_000), _valid(400_000_000)

    _cand(conn, "00000001", v1); _hmrc(conn, v1, "valid", "ALPHA BUILDERS LTD", "E1 1AA")           # HIGH
    _cand(conn, "00000002", v2); _hmrc(conn, v2, "valid", "SOMEONE ELSE ENTIRELY PLC", "M9 9ZZ")    # LOW
    _cand(conn, "00000003", v3); _hmrc(conn, v3, "not_found")                                        # hmrc_not_found
    _cand(conn, "00000004", "123456789")                                                             # bad checksum
    with conn:
        conn.execute("INSERT INTO domains VALUES('00000005','eps.co.uk','strong','company_number_on_site','[]',3,'found','now')")
        conn.execute("INSERT INTO domains VALUES('00000006',NULL,'none','','[]',0,'none_found','now')")

    assert v4 not in pl.pending_vrns(conn)
    assert set(pl.pending_vrns(conn)) == set()   # all candidate vrns already cached in hmrc, or invalid
    counts = pl.run_decide(conn)
    assert counts == {"HIGH": 1, "LOW": 1}
    out = pl.compute_outcomes(conn)
    assert out["verified_high"] == 1 and out["rejected_mismatch"] == 1 and out["hmrc_not_found"] == 1
    assert out["checksum_failed_only"] == 1
    assert out["no_vat_on_verified_site"] == 1 and out["no_domain_found"] == 1

    t = weighted_outcome_table(conn)
    assert abs(t["weighted_share"].sum() - 1.0) < 1e-9


def test_vat_group_demotes_to_medium(tmp_path):
    conn = _setup(tmp_path)
    v = _valid(100_000_000)
    for cn in ("00000001", "00000002"):
        _cand(conn, cn, v)
    _hmrc(conn, v, "valid", "ALPHA BUILDERS LTD", "E1 1AA")
    # second company has a name that also matches HMRC's -> same VAT claimed by two matching companies
    with conn:
        conn.execute("UPDATE companies SET name='ALPHA BUILDERS LTD', postcode='E1 1AA' WHERE company_number='00000002'")
    counts = pl.run_decide(conn)
    assert counts.get("HIGH", 0) == 0 and counts["MEDIUM"] == 2


def test_audit_roundtrip_and_precision(tmp_path):
    conn = _setup(tmp_path)
    vs = [_valid(100_000_000 + i * 50_000_000) for i in range(3)]
    for cn, v in zip(("00000001", "00000002", "00000003"), vs):
        _cand(conn, cn, v)
    _hmrc(conn, vs[0], "valid", "ALPHA BUILDERS LTD", "E1 1AA")
    _hmrc(conn, vs[1], "valid", "BETA SOFTWARE LTD", "M1 1AA")
    _hmrc(conn, vs[2], "valid", "TOTALLY DIFFERENT", "ZZ1 1ZZ")
    pl.run_decide(conn)
    sheet, key = export_audit(conn, tmp_path, n_high=5, n_medium=5, n_low=5)
    df = pd.read_csv(sheet, dtype=str).fillna("")
    assert "tier" not in df.columns and "name_score" not in df.columns        # blind to the algorithm
    df["label"] = "correct"
    df.loc[df["company_number"] == "00000003", "label"] = "wrong"
    df.to_csv(sheet, index=False)
    assert import_audit(conn, sheet, key) == 3
    table, md = precision_report(conn)
    high = table[table["tier"] == "HIGH"].iloc[0]
    assert high["audited"] == 2 and high["wrong"] == 0 and high["rule_of_three_upper(if wrong=0)"] == 1.5
    text = build_report(conn, tmp_path / "results.md", md)
    assert "Funnel" in text and "do not capture" in text


def test_stats_helpers():
    lo, hi = wilson(0, 100)
    assert lo == 0.0 and 0.02 < hi < 0.05
    assert rule_of_three(100) == 0.03
    r = chapman(50, 40, 20)
    assert 90 < r["n_hat"] < 110 and r["lo"] <= r["n_hat"] <= r["hi"]
