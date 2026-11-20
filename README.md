# UK VAT identifier discovery: feasibility pipeline

Can a UK company VAT dataset be built from the open web, and how sure are we of each number? This repository is
the code and evidence behind that question. The full write-up (Parts 1 to 3) is a separate document; this file
explains how to run the code, what was actually run, what it found, what was not done, and the facts behind the
debate topics.

## Status

- **Run against live data** on a 500-company sample: company websites, a 10-file slice of Common Crawl, and the
  Peppol Directory. Companies House data comes from the bulk snapshot `BasicCompanyDataAsOneFile-2026-11-01`.
- **HMRC verification was done by hand** on the GOV.UK "Check a UK VAT number" page (49 numbers). The HMRC API
  client (`hmrc.py`) was tested only against the sandbox, which accepts mock numbers only. The production API
  (version 2) requires registration, which HMRC's page says should take around 2 weeks, and acceptance of its
  Terms of Use 2.0. It was not obtained.
- **31 tests pass** (`python -m pytest -q`).
- **No blind audit was run**, so there is no measured false-positive rate. See "What was not done".

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # set VATDISC_CONTACT; HMRC_CLIENT_ID / HMRC_CLIENT_SECRET / HMRC_BASE_URL if you use the API
python -m pytest -q         # 31 passed
```

`.env` holds credentials. Do not commit or share it, and keep `data/` (the database and downloads) out of any
archive you submit. The HMRC sandbox base URL is `https://test-api.service.hmrc.gov.uk`.

## What was run, in order

```bash
python -m vatdisc.cli sample --file data/<file>.zip --n 500 --seed 42   # 500 of 4,295,232 eligible companies
python -m vatdisc.cli scan-websites                                      # route A: company websites
python -m vatdisc.cli scan-wet --crawl CC-MAIN-2026-43 --max-files 10   # route B: Common Crawl text files 0 to 9
python -m vatdisc.cli link-corpus --file data/<file>.zip                 # attach Companies House records
python -m vatdisc.cli peppol                                             # route C: Peppol Directory
# 49 distinct numbers were then checked by hand at GOV.UK and imported (make_manual_sheet.py, import_manual_hmrc.py)
python -m vatdisc.cli decide
python -m vatdisc.cli outcomes
python -m vatdisc.cli report .                                           # writes results.md
```

Every stage reads and writes `data/vatdisc.sqlite`, so results are queryable with SQL. Failed requests are
recorded as unknown, never as "no match".

## What it found (sources and calculations are in the write-up)

| Quantity | Value |
| --- | --- |
| Sample | 500 companies, seed 42, stratified by accounts group x age bucket, weights N_h / n_h |
| Domains accepted | 46 of 500 (9.2%) |
| Accepted sites showing a VAT number | 8 of 46 (1.6% of all 500) |
| HMRC-confirmed and name-matched (HIGH) | 7 of 500 (1.4%, 95% interval 0.7 to 2.9%) |
| Numbers checked by hand at HMRC | 49 (40 from the corpus, 9 from websites); 47 valid, 2 not found |
| Tier decisions | 48: 42 HIGH, 6 LOW, 0 MEDIUM |
| Common Crawl slice | 10 of 100,000 text files: 215,425 pages, 355 company-number and VAT pairs, 202 distinct companies |
| Peppol | 500 queried, 8 errors (unknown), 3 candidates, not checked at HMRC |
| Pages showing a VAT number, shop-like vs other (.uk hosts, 10 files) | 11.39% vs 4.16% |

## What was not done

- **Blind audit** of tiered pairs. The code exists (`audit-export`, `audit-import`, `audit-report`); it was skipped
  because of time, so the false-positive rate of HIGH is not measured.
- **Production HMRC API** (see Status).
- **Full crawl:** only 10 of 100,000 files, and only the text files, so structured data in the HTML (such as
  `vatID`) was not seen.
- **Sell2Wales, the Gazette, spend-over-GBP25k files, the EORI lookup and Endole's terms and API** were not used.
- **Aggregator scraping** (CompanyCheck and similar) was not built, because their terms prohibit scraping.
- **Website route pairing:** it attributes every number on a verified site to that company. The corpus route has a
  nearest-company-number rule; the website route does not.
- **Recall** cannot be measured on a 500-company sample.

## Module map

| File | Role |
|---|---|
| `vat.py` | normalise VRNs, modulus-97 checksum, EORI -> VAT relationship. No enumeration helper, on purpose. |
| `companies_house.py` | stream the bulk file, clean columns, eligibility filter, SIC section / account group / age bucket |
| `sampling.py` | deterministic stratified sample, weights, representativeness table |
| `extract.py` | regex candidates for VAT numbers (keyword, `GB`-prefixed, EORI, JSON-LD `vatID`) and company numbers |
| `domains.py` | domain guesses from the company name; evidence that a site belongs to the company |
| `http.py` | polite fetcher: identifying User-Agent, robots.txt, per-host throttle, size cap |
| `sources/website.py` | homepage and legal-type pages -> candidates, only on a verified domain |
| `sources/commoncrawl_wet.py` | corpus route: a page showing a company number and a VAT number together, paired by proximity |
| `sources/peppol.py` | Peppol Directory (scheme 9932 = GB VAT) |
| `hmrc.py` | HMRC v2 client: OAuth, cache, rate limit, 429 backoff, hard call budget (sandbox-tested only) |
| `matching.py` | name and postcode comparison and the HIGH / MEDIUM / LOW tier rules |
| `pipeline.py` | store, verify, decide, classify outcomes |
| `audit.py` | blind manual audit sheet (not run) |
| `evaluate.py` | weighted outcomes, funnel, per-source yield, report |

## Decisions worth defending

- **HMRC-valid is not "correct company".** HMRC confirms a number exists, not whose it is. `decide()` in `matching.py`
  compares HMRC's registered name and address with Companies House (current and previous names) and requires
  corroboration for HIGH.
- **HIGH needs a name score of 95 or more and independent corroboration** (postcode, company number on the source
  page, or a verified site). 95 or more without corroboration, or 85 to 94 with it, is MEDIUM. Address never lowers a
  tier, because many registered offices are accountants' addresses.
- **Consistency checks demote:** a VAT number shared by two matching companies (possible VAT group), or a company
  with two valid numbers, drops from HIGH to MEDIUM.
- **"Not found" is split into outcome classes** (`pipeline.py`). `no_domain_found` is a method failure and
  `no_vat_on_verified_site` is ambiguous; neither is read as "not registered".
- **The corpus route keys on the company number, not the domain.** A page showing both numbers proves its own
  pairing. Pages with more than 3 company numbers or 3 VAT numbers are skipped.
- **The sample uses Companies House attributes only** (accounts category x age), with weights, and excludes dormant
  companies by default.

## Facts for the debate topics

**The checksum brute-force idea.** 28,869,645 nine-digit strings pass `checksum_ok` (about 1 in 35; local arithmetic,
no HMRC calls). At 2 requests per second, which is a default pace and not an HMRC limit, that is about 167 days.
HMRC's API description says the service is "for the sole purpose of allowing traders to do due diligence on
VAT-registered businesses". A hit also needs matching to a company.

**Keeping the dataset current.** HMRC answers are cached by number and errors are not cached. Companies House
publishes monthly snapshots, so name and status changes can be detected by comparing snapshots. A pass of 1 million
re-checks at 2 per second takes 5.8 days.

**Detecting errors at scale.** Two kinds of error appeared: numbers HMRC does not recognise (2 of 49) and
registered numbers matched to a different name (6 of 48 decisions were LOW). The consistency checks above (one VAT
to many companies, one company to many VATs) are in the code. The blind audit was not run.

**Sources.** CompanyCheck's terms prohibit screen scraping and reserve the data. Endole's terms were not found, so
it was not automated. The Peppol Directory lists individuals. In the pilot, an AI search overview gave 5 numbers:
3 correct, 1 wrong owner, 1 expired.

## Known limitations of the code

- The website scan cannot tell an unreachable domain from a nonexistent one.
- The first 10 Common Crawl files share a timestamp segment and may not be a random mix.
- The checksum accepts remainders 0, 42 and 55 for numbers whose first three digits are 100 or more, matching
  `python-stdnum`.

## Reporting checklist

For each source: companies tried, pages fetched, candidates, checksum-valid, HMRC-valid, tier counts, and the
exact reason it fell short. `docs/experiment_log_template.md` has a table for this.
