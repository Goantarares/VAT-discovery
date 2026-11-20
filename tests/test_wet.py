"""Common Crawl WET scanning, tested on a locally built .wet.gz (no network)."""
import io

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from vatdisc.sources.commoncrawl_wet import scan_wet
from vatdisc.vat import checksum_ok


def _valid():
    n = 100_000_000
    while not checksum_ok(f"{n:09d}"):
        n += 1
    return f"{n:09d}"


V = _valid()
SP = f"{V[:3]} {V[3:7]} {V[7:]}"


def _write_wet(path, pages):
    with open(path, "wb") as fh:
        w = WARCWriter(fh, gzip=True)
        for uri, text in pages:
            rec = w.create_warc_record(
                uri, "conversion", payload=io.BytesIO(text.encode()),
                warc_headers_dict={"Content-Type": "text/plain"},
            )
            w.write_record(rec)


def test_scan_wet_pairs_and_guards(tmp_path):
    pages = [
        ("http://good.example/terms",
         f"Acme Ltd. Registered in England and Wales, company number 01234567. VAT Reg No: GB {SP}. Contact us."),
        ("http://nokw.example", "Just a shop. Nothing to see. Company number 07654321."),
        ("http://novat.example", "VAT is a tax. Company number 07654321."),
        ("http://directory.example",
         "Company number 00000011 Company number 00000022 Company number 00000033 Company number 00000044 "
         f"VAT {SP}"),
        ("http://badsum.example", "Company number 01111111 VAT Reg No 123456789"),
    ]
    p = tmp_path / "x.wet.gz"
    _write_wet(p, pages)
    res = scan_wet(str(p))
    assert res.stats.pages == 5
    assert res.stats.pages_with_vat_kw == 4
    assert res.stats.skipped_multi == 1             # directory-style page is dropped, not guessed at
    assert [(x["company_number"], x["vat"]) for x in res.pairs] == [("01234567", V)]
    assert res.pairs[0]["url"] == "http://good.example/terms"

    only = scan_wet(str(p), target_numbers={"99999999"})
    assert only.pairs == []


def _valid_after(start):
    n = start
    while not checksum_ok(f"{n:09d}"):
        n += 1
    return f"{n:09d}"


def test_multi_entity_footer_pairs_each_vat_with_its_own_company(tmp_path):
    """Regression: a footer listing several companies used to pair every company with every VAT."""
    v1, v2 = _valid_after(200_000_000), _valid_after(300_000_000)
    text = (f"Alpha Ltd | Registered Address: 3 High Street | Company Number: 5394595 | VAT Number: {v1} "
            f"Company Name: Beta Ltd | Company Number: 12870723 | VAT Number: {v2} Privacy Policy")
    p = tmp_path / "m.wet.gz"
    _write_wet(p, [("http://group.example/", text)])
    res = scan_wet(str(p))
    assert sorted((x["company_number"], x["vat"]) for x in res.pairs) == sorted(
        [("05394595", v1), ("12870723", v2)])


def test_vat_far_from_any_company_number_is_not_paired(tmp_path):
    text = f"Company number 01234567. " + ("lorem ipsum " * 60) + f"our accountant's VAT Reg No: {V}"
    p = tmp_path / "f.wet.gz"
    _write_wet(p, [("http://far.example/", text)])
    res = scan_wet(str(p))
    assert res.pairs == [] and res.stats.skipped_far == 1
