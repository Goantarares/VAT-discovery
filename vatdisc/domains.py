"""Company -> website mapping.

Companies House has no website field, so this is its own problem. Strategy here is deliberately
modest and, crucially, *self-verifying*:

  1. Generate a handful of domain guesses from the company name.
  2. Fetch the homepage and legal-ish pages.
  3. Accept a domain only if the pages prove they belong to this company. UK websites of limited
     companies must display company name, registration number and registered office
     (Companies (Trading Disclosures) Regulations 2008), so the company number or the registered
     postcode appearing on the site is genuine evidence.

Evidence levels:  strong = company number on the site;  medium = registered postcode + name on the
site;  weak = name only (never accepted);  none.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import page_mentions_company_number
from .matching import norm_postcode, normalise_name

DEFAULT_TLDS = (".co.uk", ".com", ".uk", ".org.uk", ".net")
EVIDENCE_ORDER = {"none": 0, "weak": 1, "medium": 2, "strong": 3}


def candidate_domains(name: str, tlds: tuple[str, ...] = DEFAULT_TLDS, limit: int = 12) -> list[str]:
    tokens = normalise_name(name, drop_legal=True).split()
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    slugs: list[str] = []
    joined = "".join(tokens)
    hyph = "-".join(tokens)
    slugs += [joined, hyph]
    if len(tokens) > 2:
        slugs.append("".join(tokens[:2]))
    if len(tokens) == 1:
        slugs.append(tokens[0] + "uk")
    out: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        if not slug or len(slug) > 60:
            continue
        for tld in tlds:
            d = slug + tld
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out[:limit]


@dataclass
class DomainEvidence:
    level: str
    detail: str


def domain_evidence(company: dict, page_texts: list[str]) -> DomainEvidence:
    """How strongly do these page texts show that the site belongs to `company`?"""
    cn = company["company_number"]
    for t in page_texts:
        if page_mentions_company_number(t, cn):
            return DomainEvidence("strong", "company_number_on_site")

    pc = norm_postcode(company.get("postcode"))
    nm = normalise_name(company.get("name"), drop_legal=True)
    joined = "\n".join(page_texts)
    norm_joined = normalise_name(joined, drop_legal=False)
    name_present = bool(nm) and f" {nm} " in f" {norm_joined} "
    pc_present = bool(pc) and pc in re.sub(r"\s+", "", joined.upper())
    if name_present and pc_present:
        return DomainEvidence("medium", "registered_postcode_and_name_on_site")
    if name_present:
        return DomainEvidence("weak", "name_only")
    return DomainEvidence("none", "")
