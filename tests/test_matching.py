from vatdisc.matching import (
    Thresholds, best_name_score, decide, name_score, normalise_name, postcode_relation)


def test_issue_example_from_brief_is_one_company():
    assert name_score("J Smith Building Services Ltd", "J. Smith Building Svcs Limited") == 100.0


def test_normalise_never_empties_a_name():
    assert normalise_name("The UK Limited") != ""
    assert normalise_name("Smith & Sons Ltd") == "smith sons"


def test_similar_but_different_companies_score_low():
    assert name_score("ACME TRADING LIMITED", "ACME HOLDINGS LIMITED") < 75
    assert name_score("SMITH LTD", "SMITH HOLDINGS OF LONDON LTD") < 85


def test_joined_words_variant():
    assert name_score("Bluebird Logistics Ltd", "Blue Bird Logistics Limited") >= 95


def test_best_over_previous_names():
    sc, which = best_name_score("OLD NAME LTD", ["NEW NAME LIMITED", "OLD NAME LIMITED"])
    assert sc == 100.0 and which == "OLD NAME LIMITED"


def test_postcode_relation():
    assert postcode_relation("SW1A 1AA", "sw1a1aa") == "exact"
    assert postcode_relation("SW1A 1AA", "SW1A 2BB") == "outward"
    assert postcode_relation("SW1A 1AA", "M1 1AE") == "none"
    assert postcode_relation("", "M1 1AE") == "missing"


def test_decide_tiers():
    assert decide(100, "exact", False).tier == "HIGH"
    assert decide(100, "none", True).tier == "HIGH"            # company number on source corroborates
    assert decide(100, "none", False).tier == "MEDIUM"         # perfect name alone is not enough
    assert decide(88, "exact", False).tier == "MEDIUM"
    assert decide(70, "exact", True).tier == "LOW"
    assert decide(100, "exact", False, vat_shared=2).tier == "MEDIUM"   # possible VAT group
    assert decide(100, "exact", False, company_multi_vat=2).tier == "MEDIUM"
    assert decide(94.9, "exact", False, th=Thresholds()).tier == "MEDIUM"
