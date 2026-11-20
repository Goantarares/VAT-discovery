"""Name / postcode comparison between HMRC's record and the Companies House record, and the tier decision.

This module is the main defence against the failure the brief warns about: a plausible, HMRC-valid
number attached to the wrong company. A number being valid proves nothing about ownership.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

LEGAL_TOKENS = {
    "ltd", "limited", "plc", "llp", "lp", "llc", "inc", "co", "company", "cic", "cio", "corp",
    "corporation", "uk", "gb",  # 'uk' removed from the stripped set below if it is the whole name
}
STOPWORDS = {"the", "and", "of"}
ABBREV = {
    "svcs": "services", "svc": "services", "serv": "services", "bldg": "building", "bldrs": "builders",
    "mgmt": "management", "mgt": "management", "intl": "international", "int": "international",
    "grp": "group", "hldgs": "holdings", "hldg": "holdings", "eng": "engineering",
    "engrs": "engineers", "constn": "construction", "const": "construction", "dev": "development",
    "devs": "developments", "assoc": "associates", "assocs": "associates", "prop": "properties",
    "props": "properties", "tech": "technology", "techs": "technologies", "mfg": "manufacturing",
    "dist": "distribution", "elec": "electrical", "plmbg": "plumbing", "consulting": "consultancy",
    "solns": "solutions", "sys": "systems", "trdg": "trading", "ent": "enterprises",
}


def normalise_name(name: str | None, drop_legal: bool = True) -> str:
    if not name:
        return ""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [ABBREV.get(t, t) for t in s.split()]
    tokens = [t for t in tokens if t not in STOPWORDS]
    if drop_legal:
        stripped = [t for t in tokens if t not in LEGAL_TOKENS]
        tokens = stripped if stripped else tokens  # never reduce a name to nothing
    return " ".join(tokens)


def name_score(a: str | None, b: str | None) -> float:
    """0-100 similarity on normalised names. Deliberately stricter than token_set_ratio, which
    scores 100 for any subset ('SMITH' vs 'SMITH HOLDINGS OF LONDON')."""
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    if na.replace(" ", "") == nb.replace(" ", ""):
        return 98.0
    sa, sb = set(na.split()), set(nb.split())
    jacc = len(sa & sb) / len(sa | sb)
    srt = fuzz.token_sort_ratio(na, nb)
    return round(0.6 * srt + 0.4 * 100 * jacc, 1)


def best_name_score(hmrc_name: str | None, ch_names: list[str]) -> tuple[float, str | None]:
    best, which = 0.0, None
    for n in ch_names:
        sc = name_score(hmrc_name, n)
        if sc > best:
            best, which = sc, n
    return best, which


def norm_postcode(pc: str | None) -> str:
    return re.sub(r"\s+", "", (pc or "").upper())


def postcode_relation(a: str | None, b: str | None) -> str:
    """'exact' | 'outward' (same outward code, e.g. SW1A) | 'none' | 'missing'."""
    pa, pb = norm_postcode(a), norm_postcode(b)
    if not pa or not pb:
        return "missing"
    if pa == pb:
        return "exact"
    if len(pa) > 3 and len(pb) > 3 and pa[:-3] == pb[:-3]:
        return "outward"
    return "none"


@dataclass(frozen=True)
class Thresholds:
    high_name: float = 95.0
    medium_name: float = 85.0


@dataclass
class Decision:
    tier: str                      # HIGH | MEDIUM | LOW
    reasons: list[str] = field(default_factory=list)


def decide(
    name_sc: float,
    pc_rel: str,
    cn_linked: bool,
    site_linked: bool = False,
    vat_shared: int = 1,
    company_multi_vat: int = 1,
    th: Thresholds = Thresholds(),
) -> Decision:
    """Tier a (company, VAT) pair that HMRC already confirmed exists.

    HIGH requires a strong name match AND independent corroboration (postcode, or the company
    number / a verified company website on the source page). A perfect name with no corroboration
    is only MEDIUM: trading-name collisions are real and the registered office is often an
    accountant's address, so absence of a postcode match alone is not evidence against.
    """
    reasons = [f"name_score={name_sc:.1f}", f"postcode={pc_rel}"]
    corroborated = pc_rel in ("exact", "outward") or cn_linked or site_linked
    if cn_linked:
        reasons.append("company_number_on_source")
    if site_linked:
        reasons.append("site_verified_as_company")

    if name_sc >= th.high_name and corroborated:
        tier = "HIGH"
    elif name_sc >= th.high_name:
        tier, _ = "MEDIUM", reasons.append("no_corroboration")
    elif name_sc >= th.medium_name and corroborated:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    if tier == "HIGH" and vat_shared > 1:
        tier = "MEDIUM"
        reasons.append(f"vat_shared_by_{vat_shared}_companies(possible VAT group)")
    if tier == "HIGH" and company_multi_vat > 1:
        tier = "MEDIUM"
        reasons.append(f"company_has_{company_multi_vat}_distinct_valid_vats")
    return Decision(tier, reasons)
