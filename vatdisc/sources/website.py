"""Source 1: the company's own website (homepage + legal-looking pages).

Flow per company: guess domains -> fetch homepage -> fetch up to N legal-ish same-host pages ->
check the site proves it belongs to this company -> extract VAT candidates from those pages.
Candidates are only emitted when domain evidence is at least `min_evidence`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..domains import EVIDENCE_ORDER, candidate_domains, domain_evidence
from ..extract import find_vat_hits
from ..http import PoliteFetcher

LINK_KEYWORDS = [
    ("terms", 5), ("conditions", 5), ("vat", 5), ("contact", 4), ("legal", 4), ("imprint", 4),
    ("about", 3), ("privacy", 3), ("company", 2), ("delivery", 2), ("returns", 2),
    ("shipping", 2), ("policy", 1),
]


@dataclass
class Page:
    url: str
    html: str
    text: str


@dataclass
class SiteScan:
    domain: str | None
    evidence: str = "none"
    detail: str = ""
    tried: list[str] = field(default_factory=list)
    n_pages: int = 0
    hits: list[dict] = field(default_factory=list)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _same_site(host_a: str, host_b: str) -> bool:
    strip = lambda h: h.lower().removeprefix("www.")
    return strip(host_a) == strip(host_b)


def pick_links(base_url: str, html: str, limit: int) -> list[str]:
    host = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        p = urlparse(href)
        if p.scheme not in ("http", "https") or not _same_site(p.netloc, host):
            continue
        hay = (p.path + " " + a.get_text(" ", strip=True)).lower()
        score = max((w for kw, w in LINK_KEYWORDS if kw in hay), default=0)
        if score and href.rstrip("/") != base_url.rstrip("/"):
            scored[href] = max(score, scored.get(href, 0))
    return [u for u, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]


def crawl_site(fetcher: PoliteFetcher, domain: str, max_pages: int) -> list[Page]:
    home = fetcher.get(f"https://{domain}")
    if not home.ok:
        home = fetcher.get(f"http://{domain}")
    if not home.ok:
        return []
    base = home.final_url or home.url
    pages = [Page(base, home.text, html_to_text(home.text))]
    for url in pick_links(base, home.text, max_pages - 1):
        r = fetcher.get(url)
        if r.ok:
            pages.append(Page(r.final_url or url, r.text, html_to_text(r.text)))
    return pages


def scan_company(company: dict, fetcher: PoliteFetcher, max_pages: int = 8,
                 min_evidence: str = "medium") -> SiteScan:
    """`company` needs: company_number, name, postcode."""
    result = SiteScan(domain=None)
    for dom in candidate_domains(company["name"]):
        result.tried.append(dom)
        pages = crawl_site(fetcher, dom, max_pages)
        if not pages:
            continue
        ev = domain_evidence(company, [p.text for p in pages])
        if EVIDENCE_ORDER[ev.level] < EVIDENCE_ORDER[min_evidence]:
            continue
        result.domain, result.evidence, result.detail, result.n_pages = dom, ev.level, ev.detail, len(pages)
        seen: set[tuple[str, str]] = set()
        for p in pages:
            for h in find_vat_hits(p.text, p.html):
                if (h.vat, p.url) in seen:
                    continue
                seen.add((h.vat, p.url))
                result.hits.append({
                    "vat": h.vat, "kind": h.kind, "url": p.url, "context": h.context,
                    "checksum_ok": int(h.checksum_ok),
                })
        break
    return result
