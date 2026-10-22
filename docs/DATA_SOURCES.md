# Data acquisition and evidentiary limitations

## Live source: World Bank Indicators API v2

Documentation: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation

Official endpoint pattern:
`https://api.worldbank.org/v2/country/PRT/indicator/SP.POP.TOTL?format=json&date=2022:2024&per_page=100`

No API key is required for this read-only source. At each invocation, the adapter
downloads the JSON response, records exact raw bytes and SHA-256, source URL,
UTC retrieval timestamp, indicator/country/year locator, and the source observation
status. Versions remain separate when the provider revises a response.
Missing values are represented as NULL — never interpolated.

These are **official source-attributed observations**, not conclusive independent
geopolitical evidence. Economic statistics cannot, by themselves, establish state
control, corruption, political intervention or individual responsibility.

## Live source: USAspending.gov federal procurement award search

Official API contract: https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md

This adapter sends a fixed-shape bounded POST request for a specified federal fiscal
year and at most 25 contract award results. The complete request and raw response
are both hashed and stored. `Award Amount` is retained **as an attributed award
figure only**, never automatically converted to an actual payment, grant
disbursement or end-recipient benefit. The response is paginated; first-page
samples are partial, not representative of all awards.

USAspending data may be revised and must be corroborated with transaction-level
records for any claim about money changing hands.

## Candidate adapters, not yet implemented

- European Commission Financial Transparency System: EU budget recipients.
- OECD and IMF: macroeconomic and governance series subject to licensing.
- Official legislative/regulatory journals: decisions and formal acts.
- Company and beneficial ownership registries: jurisdiction-dependent
  identity, timing, public-access and legal restrictions.

Every future connector must specify terms of use, allowed fields, authenticated
provenance, page cursors, revision semantics, local retention and redaction.

## No automatic political conclusions

An independently validated financial transaction does not by itself prove
undue influence. A meeting does not by itself prove instruction. A contract does
not by itself prove beneficial ownership. Human reviewers must assess
counterevidence, competing explanations and legal standards.
