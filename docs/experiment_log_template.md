# Experiment log (fill one row per thing you actually ran)

| # | Date | Source / idea | What I expected | What I ran (command, N) | What came back (numbers) | Verdict | Exact reason it worked / failed |
|---|------|---------------|-----------------|-------------------------|--------------------------|---------|---------------------------------|
| 1 | | Company websites (domain guess) | | `scan-websites --limit 200` | domains found: ; candidates: ; HMRC-valid: | | |
| 2 | | Common Crawl WET | | `scan-wet --max-files 2` | pages: ; pages with VAT + company number: ; pairs: | | |
| 3 | | EORI pattern on pages | | | | | |
| 4 | | Peppol Directory | | `peppol --limit 100` | | | |
| 5 | | (your own source) | | | | | |

## Dead ends (be specific: source, expectation, exact failure, evidence)

- **Source:**
  **Expected:**
  **What happened (numbers):**
  **Why it failed:**

## Cost notes for Part 3 (per 1,000 companies)

| Stage | Wall time here | Requests / calls | What changes with budget |
|-------|----------------|------------------|--------------------------|
| Domain discovery | | | |
| Crawl / corpus scan | | | |
| HMRC verification | | | |
| Human review (MEDIUM + audit) | | | |

## Audit log

Sample size, seed, date, HIGH audited / wrong / unsure, LOW audited / correct (lost recall), who labelled.
