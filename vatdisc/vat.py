"""UK VAT number helpers: normalisation, modulus-97 checksum, EORI relationship.

This module only *validates* numbers that some source handed us. It deliberately has no
function that enumerates the valid number space: see README (debate topic 1) for why.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 1)


def normalise_vrn(raw: str | None) -> str | None:
    """Return a 9- or 12-digit string, or None.

    Accepts 'GB 123 4567 89', 'gb123456789', '123-4567-89', 'GB123456789000'.
    Government (GD) and health-authority (HA) numbers are rejected: they are not companies.
    """
    if not raw:
        return None
    s = _NON_ALNUM.sub("", str(raw)).upper()
    if s.startswith("GB"):
        s = s[2:]
    if not s.isdigit():
        return None
    if len(s) in (9, 12):
        return s
    return None


def base9(vrn: str) -> str:
    return vrn[:9]


def checksum_ok(vrn: str) -> bool:
    """Modulus-97 check on the first nine digits.

    Pre-2010 style numbers: weighted sum % 97 == 0.
    Newer numbers (first three digits >= 100) are valid when the remainder is 0, 42 or 55
    (the 42/55 residues are the "+55" variants).  This mirrors python-stdnum, and the test
    suite cross-checks the two on random input.
    """
    v = normalise_vrn(vrn)
    if v is None:
        return False
    d = v[:9]
    s = sum(w * int(c) for w, c in zip(_WEIGHTS, d)) % 97
    if int(d[:3]) >= 100:
        return s in (0, 42, 55)
    return s == 0


def eori_to_vrn(eori: str | None) -> str | None:
    """GB EORI numbers for VAT-registered traders are 'GB' + 9-digit VAT number + '000'.

    Returns the 9-digit VAT number, or None if the string is not of that shape.
    NOTE: verify this relationship yourself against HMRC-confirmed pairs before relying on it.
    """
    if not eori:
        return None
    s = _NON_ALNUM.sub("", str(eori)).upper()
    if not (s.startswith("GB") and s[2:].isdigit() and len(s) == 14):
        return None
    digits = s[2:]
    return digits[:9] if digits[9:] == "000" else None


def display(vrn: str) -> str:
    v = base9(vrn)
    return f"GB {v[:3]} {v[3:7]} {v[7:]}"
