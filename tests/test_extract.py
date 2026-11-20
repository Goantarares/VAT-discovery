from vatdisc.extract import (
    find_company_numbers, find_vat_hits, normalise_company_number, page_mentions_company_number)
from vatdisc.vat import checksum_ok


def _valid_vat() -> str:
    for n in range(100_000_000, 100_001_000):
        if checksum_ok(f"{n:09d}"):
            return f"{n:09d}"
    raise AssertionError


V = _valid_vat()
SPACED = f"{V[:3]} {V[3:7]} {V[7:]}"


def test_keyword_and_prefixed_forms():
    for text in (f"VAT Reg No: {SPACED}", f"VAT number GB{V}", f"V.A.T. registration: GB {SPACED}",
                 f"Registered for VAT GB {SPACED}"):
        hits = find_vat_hits(text)
        assert [h.vat for h in hits] == [V], text
        assert hits[0].checksum_ok


def test_dedupes_and_flags_bad_checksum():
    bad = "123456789"
    assert not checksum_ok(bad)
    hits = find_vat_hits(f"VAT {SPACED} ... VAT no GB{V} ... VAT: {bad}")
    byvat = {h.vat: h for h in hits}
    assert set(byvat) == {V, bad}
    assert byvat[V].checksum_ok and not byvat[bad].checksum_ok


def test_eori_and_branch_kinds():
    h = find_vat_hits(f"EORI: GB{V}000")[0]
    assert h.vat == V and h.kind == "eori"
    h = find_vat_hits(f"VAT GB{V}001")[0]
    assert h.vat == V and h.kind == "branch"


def test_no_match_inside_longer_digit_strings():
    assert find_vat_hits(f"order ref 9GB{V}77") == []
    assert find_vat_hits("phone 020 7946 0958, GB 1234567890123") == []


def test_jsonld():
    html = f'<script type="application/ld+json">{{"vatID": "GB{V}"}}</script>'
    hits = find_vat_hits("", html)
    assert hits and hits[0].kind == "jsonld" and hits[0].vat == V


def test_company_numbers():
    assert find_company_numbers("Registered in England and Wales, company number 01234567.") == ["01234567"]
    assert find_company_numbers("Company No. SC123456 | VAT") == ["SC123456"]
    assert find_company_numbers("Registered in England No 123456") == ["00123456"]
    assert normalise_company_number("12345") == "00012345"


def test_page_mentions_company_number():
    assert page_mentions_company_number("Registered in England. Company number: 01234567", "01234567")
    assert page_mentions_company_number("Company No 1234567 registered office", "01234567")
    # design choice: the full zero-padded 8-char form is distinctive enough to count without a keyword
    assert page_mentions_company_number("ref 01234567 ok", "01234567")
    assert not page_mentions_company_number("our order was 9999999", "01234567")
    assert page_mentions_company_number("Company number SC123456", "SC123456")
