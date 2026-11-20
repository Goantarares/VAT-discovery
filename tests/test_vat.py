import random

import pytest

from vatdisc.vat import checksum_ok, eori_to_vrn, normalise_vrn


def test_normalise():
    assert normalise_vrn("GB 123 4567 89") == "123456789"
    assert normalise_vrn("gb123456789000") == "123456789000"
    assert normalise_vrn("123-4567-89") == "123456789"
    assert normalise_vrn("GD123") is None
    assert normalise_vrn("12345") is None
    assert normalise_vrn(None) is None


def test_eori():
    assert eori_to_vrn("GB123456789000") == "123456789"
    assert eori_to_vrn("GB 123456789 000") == "123456789"
    assert eori_to_vrn("GB123456789001") is None   # suffix other than 000
    assert eori_to_vrn("DE123456789000") is None


def test_checksum_matches_stdnum_on_random_input():
    stdnum_vat = pytest.importorskip("stdnum.gb.vat")
    rng = random.Random(0)
    agree = valid = 0
    for _ in range(40_000):
        n = f"{rng.randrange(10**9):09d}"
        mine = checksum_ok(n)
        theirs = stdnum_vat.is_valid(n)
        assert mine == theirs, n
        agree += 1
        valid += mine
    # roughly 3/97 of numbers with prefix >= 100 pass: about 1 in 32
    assert 0.02 < valid / agree < 0.045


def test_known_numbers_from_published_examples():
    # appear in public HMRC / vendor documentation examples
    stdnum_vat = pytest.importorskip("stdnum.gb.vat")
    for n in ("220430231", "553557881", "337440071"):
        assert checksum_ok(n) == stdnum_vat.is_valid(n)
