"""Find VAT-number-looking strings (and company numbers) in page text.

Extraction only produces *candidates*. Whether a candidate belongs to a given company is decided
later, by HMRC verification plus name/address matching. Context windows are kept for human audit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .vat import checksum_ok, normalise_vrn

# "GB 123 4567 89", optionally followed by a 3-digit suffix (branch trader or EORI '000').
GB_PREFIXED = re.compile(
    r"(?<![A-Za-z0-9])GB[\s\-]?(\d{3})[\s\-]?(\d{4})[\s\-]?(\d{2})(?:[\s\-]?(\d{3}))?(?!\d)",
    re.I,
)
# "VAT Reg No: 123 4567 89", "VAT number 123456789", "V.A.T. registration: GB123456789"
VAT_KEYWORD = re.compile(
    r"(?:VAT|V\.A\.T\.?|Value\s+Added\s+Tax)"
    r"(?:\s*(?:Registration|Registered|Reg\.?|No\.?|Number|Num\.?|ID|Identification))*"
    r"\s*[:#\-–—]?\s*(?:\(?GB\)?\s*)?"
    r"(\d{3}[\s\-]?\d{4}[\s\-]?\d{2})(?!\d)",
    re.I,
)
JSONLD_VAT = re.compile(r'"(?:vatID|taxID)"\s*:\s*"([^"]{6,30})"', re.I)
VAT_WORD = re.compile(r"\bVAT\b|\bEORI\b|Value\s+Added\s+Tax", re.I)

CONTEXT_CHARS = 100


@dataclass(frozen=True)
class VatHit:
    vat: str            # 9 digits
    kind: str           # 'prefixed' | 'keyword' | 'eori' | 'branch' | 'jsonld'
    raw: str
    context: str
    checksum_ok: bool
    keyword_near: bool
    positions: tuple = ()   # character offsets of every occurrence in `text` (empty for JSON-LD)


def _ctx(text: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - CONTEXT_CHARS): end + CONTEXT_CHARS]).strip()


def find_vat_hits(text: str, html: str | None = None) -> list[VatHit]:
    """All distinct 9-digit VAT candidates in `text` (plus JSON-LD in `html` if given)."""
    hits: dict[str, VatHit] = {}
    where: dict[str, list[int]] = {}

    def add(vat9: str, kind: str, raw: str, start: int, end: int) -> None:
        where.setdefault(vat9, []).append(start)
        if vat9 in hits:
            return
        ctx = _ctx(text, start, end)
        near = bool(VAT_WORD.search(text[max(0, start - 40): end + 10]))
        hits[vat9] = VatHit(vat9, kind, raw, ctx, checksum_ok(vat9), near)

    for m in VAT_KEYWORD.finditer(text):
        vrn = normalise_vrn(m.group(1))
        if vrn:
            add(vrn[:9], "keyword", m.group(0), m.start(), m.end())

    for m in GB_PREFIXED.finditer(text):
        digits = m.group(1) + m.group(2) + m.group(3)
        suffix = m.group(4)
        before = text[max(0, m.start() - 30): m.start()]
        if suffix == "000" and re.search(r"EORI", before, re.I):
            kind = "eori"
        elif suffix:
            kind = "branch"
        else:
            kind = "prefixed"
        add(digits, kind, m.group(0), m.start(), m.end())

    if html:
        for m in JSONLD_VAT.finditer(html):
            vrn = normalise_vrn(m.group(1))
            if vrn:
                hits.setdefault(
                    vrn[:9],
                    VatHit(vrn[:9], "jsonld", m.group(0), m.group(0), checksum_ok(vrn), True),
                )
    return [replace(h, positions=tuple(where.get(h.vat, ()))) for h in hits.values()]


# ---------------------------------------------------------------- company numbers

_CN_TOKEN = r"((?:[A-Z]{2})?\d{5,8})"
CN_KEYWORD = re.compile(
    r"(?:company|registration|registered|reg\.?|co\.?)\s*(?:number|no\.?|num\.?|#)\s*[:\-–]?\s*" + _CN_TOKEN
    + r"(?![\dA-Za-z])",
    re.I,
)
CN_REGISTERED_IN = re.compile(
    r"registered\s+in\s+(?:england(?:\s+and|\s*&)\s+wales|england|scotland|northern\s+ireland|wales)"
    r"[^0-9A-Za-z]{0,20}(?:company\s+)?(?:number|no\.?|num\.?)?\s*[:\-–]?\s*"
    r"(?:with\s+(?:company\s+)?(?:number|no\.?)\s*)?" + _CN_TOKEN + r"(?![\dA-Za-z])",
    re.I,
)
_CN_NEARBY_WORDS = re.compile(r"regist|company|co\.? ?no|number|england|wales|scotland|northern ireland", re.I)


def normalise_company_number(raw: str) -> str | None:
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if re.fullmatch(r"\d{5,8}", s):
        return s.zfill(8)
    if re.fullmatch(r"[A-Z]{2}\d{6}", s):
        return s
    if re.fullmatch(r"[A-Z]{2}\d{5,6}[A-Z]?", s):
        return s
    return None


def find_company_numbers(text: str) -> list[str]:
    """Company-number candidates introduced by a keyword ('Company No', 'registered in England...')."""
    out: dict[str, None] = {}
    for rx in (CN_KEYWORD, CN_REGISTERED_IN):
        for m in rx.finditer(text):
            cn = normalise_company_number(m.group(1))
            if cn:
                out[cn] = None
    return list(out)


def find_company_number_spans(text: str) -> list[tuple[str, int]]:
    """Every occurrence of a keyword-introduced company number, as (normalised number, offset)."""
    out: list[tuple[str, int]] = []
    for rx in (CN_KEYWORD, CN_REGISTERED_IN):
        for m in rx.finditer(text):
            cn = normalise_company_number(m.group(1))
            if cn:
                out.append((cn, m.start(1)))
    return out


def page_mentions_company_number(text: str, company_number: str) -> bool:
    """True if `text` shows this company's number near a registration-ish word.

    Pages often drop leading zeros, so '00012345' also matches '12345', but only when at least
    five significant digits remain (shorter fragments collide with arbitrary numbers).
    """
    cn = company_number.strip().upper()
    m = re.fullmatch(r"([A-Z]{0,2})(\d+)", cn)
    if not m:
        return False
    prefix, digits = m.groups()
    sig = digits.lstrip("0")
    candidates = {cn}
    if not prefix and len(sig) >= 5:
        candidates.add(sig)
    if prefix and len(digits) == 6:
        candidates.add(cn)
    for cand in candidates:
        rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(cand) + r"(?![A-Za-z0-9])", re.I)
        for mm in rx.finditer(text):
            window = text[max(0, mm.start() - 80): mm.end() + 20]
            if cand == cn and not prefix or cand == cn and prefix:
                # full-form match is distinctive enough on its own for 8-char forms
                if len(cn) == 8 and not prefix:
                    return True
            if _CN_NEARBY_WORDS.search(window):
                return True
    return False
