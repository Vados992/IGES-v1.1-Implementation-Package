"""Reviewed, fixed endpoints and dataset semantics. No client-supplied URL or query language."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    provider: str
    title: str
    sector: str
    jurisdiction: str
    documentation: str
    limitations: str
    parameters: dict
    variant: str = ""
    transport: str = "HTTPS"


DATE = {"type": "date", "default": "2024-01-01"}
END = {"type": "date", "default": "2024-12-31"}
DATES = {"start": DATE, "end": END}
FDIC = "https://api.fdic.gov/banks/docs"
ECB = "https://data.ecb.europa.eu/help/api/data-examples"
CFTC = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
HMLR = "https://landregistry.data.gov.uk/app/root/doc/ppd"
DATASETS = {
    "fdic_institutions": Dataset(
        "FDIC",
        "FDIC insured institutions",
        "banking",
        "US",
        FDIC,
        "Institution directory, not customer accounts. Assets/deposits are reported USD thousands; update dates are not a common financial reporting period.",
        {"state": {"pattern": "[A-Z]{2}", "default": ""}},
        "institutions",
    ),
    "fdic_financials": Dataset(
        "FDIC",
        "FDIC quarterly bank financials",
        "banking",
        "US",
        FDIC,
        "Reported bank financials, USD thousands, not transfers or customer balances.",
        {"report_date": {"type": "date", "default": "2024-12-31"}},
        "financials",
    ),
    "fdic_failures": Dataset(
        "FDIC",
        "FDIC failures and assistance history",
        "banking",
        "US",
        FDIC,
        "Resolution/assistance records; RESTYPE must be inspected. COST is an estimated resolution cost in USD thousands, not a customer loss or bank transfer.",
        {},
        "failures",
    ),
    "ecb_fx": Dataset(
        "ECB",
        "ECB monthly euro reference exchange rates",
        "banking",
        "EU",
        ECB,
        "Monthly reference rates, foreign-currency units per EUR; not executable quotes.",
        DATES
        | {
            "currency": {
                "enum": [
                    "USD",
                    "GBP",
                    "CHF",
                    "JPY",
                    "CAD",
                    "AUD",
                    "SEK",
                    "NOK",
                    "DKK",
                    "PLN",
                    "CZK",
                    "HUF",
                    "RON",
                ],
                "default": "USD",
            }
        },
        "EXR",
    ),
    "ecb_deposit_rate": Dataset(
        "ECB",
        "ECB deposit facility rate changes",
        "banking",
        "EU",
        ECB,
        "Change-date observations; absent days are not zero and are not forward-filled.",
        DATES,
        "FM",
    ),
    "ecb_mortgage_volume": Dataset(
        "ECB",
        "ECB new housing loan business volumes",
        "property",
        "EU",
        ECB,
        "MFI new-business lending volume, not property sale prices or actual account transfers. Unit and multiplier remain attached.",
        DATES,
        "MIR_VOLUME",
    ),
    "ecb_mortgage_rate": Dataset(
        "ECB",
        "ECB new housing loan interest rates",
        "property",
        "EU",
        ECB,
        "Aggregated household housing-loan rate, not an individual mortgage offer.",
        DATES,
        "MIR_RATE",
    ),
    "boe_bank_rate": Dataset(
        "BOE",
        "Bank of England official Bank Rate",
        "banking",
        "UK",
        "https://www.bankofengland.co.uk/boeapps/database/help.asp",
        "Daily published Bank Rate in percent; no assumed observations on missing dates.",
        DATES,
        "IUDBEDR",
    ),
    "treasury_debt": Dataset(
        "US_TREASURY",
        "US Treasury Debt to the Penny",
        "banking",
        "US",
        "https://fiscaldata.treasury.gov/api-documentation/",
        "Outstanding public debt stocks in USD, not individual bank transactions.",
        DATES,
    ),
    "eurostat_hpi": Dataset(
        "EUROSTAT",
        "Eurostat quarterly house price index",
        "property",
        "EU",
        "https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction",
        "Quarterly total-purchase index, 2015=100, not transaction prices or an ownership register; latest provider vintage is retained separately on revision.",
        DATES
        | {
            "country": {
                "enum": [
                    "ALL",
                    "EU27_2020",
                    "EA20",
                    "AT",
                    "BE",
                    "BG",
                    "HR",
                    "CY",
                    "CZ",
                    "DK",
                    "EE",
                    "FI",
                    "FR",
                    "DE",
                    "EL",
                    "HU",
                    "IE",
                    "IT",
                    "LV",
                    "LT",
                    "LU",
                    "MT",
                    "NL",
                    "PL",
                    "PT",
                    "RO",
                    "SK",
                    "SI",
                    "ES",
                    "SE",
                ],
                "default": "ALL",
            }
        },
    ),
    "nyc_acris": Dataset(
        "NYC_DOF",
        "NYC ACRIS real property document master",
        "property",
        "US",
        "https://data.cityofnewyork.us/City-Government/ACRIS-Real-Property-Master/bnx9-e6tj",
        "Recorded property documents, not a current ownership determination. Document amount may be zero and may not be a sale consideration. No party names/addresses are requested.",
        DATES,
    ),
    "hmlr_ppd": Dataset(
        "HM_LAND_REGISTRY",
        "HM Land Registry Price Paid transactions",
        "property",
        "UK",
        HMLR,
        "England/Wales postcode query, not all UK property or current title ownership. No party names or full address requested. Contains HM Land Registry data © Crown copyright and database right; OGL attribution required.",
        {"postcode": {"pattern": "[A-Z0-9 ]{5,9}", "default": "EC1V 3AP"}},
    ),
    "gleif_lei": Dataset(
        "GLEIF",
        "GLEIF legal entity identifiers",
        "identity",
        "US/EU/UK",
        "https://www.gleif.org/en/lei-data/gleif-api/",
        "LEI reference identity, not a banking/broker licence, account or proof of beneficial ownership. Name matching does not merge identities.",
        {
            "name": {"pattern": "[A-Za-z0-9 .&()-]{2,80}", "default": "Bank"},
            "country": {
                "enum": [
                    "ALL",
                    "US",
                    "GB",
                    "AT",
                    "BE",
                    "BG",
                    "HR",
                    "CY",
                    "CZ",
                    "DK",
                    "EE",
                    "FI",
                    "FR",
                    "DE",
                    "GR",
                    "HU",
                    "IE",
                    "IT",
                    "LV",
                    "LT",
                    "LU",
                    "MT",
                    "NL",
                    "PL",
                    "PT",
                    "RO",
                    "SK",
                    "SI",
                    "ES",
                    "SE",
                ],
                "default": "ALL",
            },
        },
    ),
    "alpaca_stock_bars": Dataset(
        "ALPACA",
        "Alpaca daily IEX stock bars",
        "market",
        "US",
        "https://docs.alpaca.markets/docs/market-data",
        "IEX venue feed only, not consolidated US volume or customer positions. MCP envelopes are connector-normalized, not original HTTP bytes; redistribution needs provider terms review.",
        DATES | {"symbols": {"pattern": "[A-Z.,-]{1,100}", "default": "JPM,BAC,GS,MS,SCHW,BLK"}},
        transport="MCP_OR_CREDENTIALED_HTTPS",
    ),
}

for key, title, view in [
    ("cftc_tff_futures", "Financial futures, futures only", "gpe5-46if"),
    ("cftc_tff_combined", "Financial futures/options combined", "yw9f-hn96"),
    ("cftc_legacy_futures", "Legacy COT, futures only", "6dca-aqww"),
    ("cftc_legacy_combined", "Legacy COT futures/options combined", "jun7-fc8e"),
    ("cftc_disaggregated_futures", "Disaggregated COT, futures only", "72hh-3qpy"),
    ("cftc_disaggregated_combined", "Disaggregated COT futures/options combined", "kh3c-gbw2"),
]:
    DATASETS[key] = Dataset(
        "CFTC",
        title,
        "market",
        "US",
        CFTC,
        "Weekly aggregate trader-category positions in contracts, not named broker/client positions or payments. Combined options are futures-equivalent; reports share lineage and are not independent corroboration.",
        DATES,
        view,
    )

DATASETS.update(
    {
        "ua_rada_roster": Dataset(
            "UA_RADA",
            "Verkhovna Rada membership, VII–IX convocations",
            "public_office",
            "UA",
            "https://data.rada.gov.ua/open/data/mps",
            "Official published membership history, filtered to mandates overlapping 2014 onward. Convocation is not an annual snapshot. Source dates are preserved; null end dates are not proof of current office. No automatic cross-registry identity merge. Attribution: Апарат Верховної Ради України.",
            {"term": {"enum": ["7", "8", "9"], "default": "9"}},
        ),
        "ua_rada_posts": Dataset(
            "UA_RADA",
            "Verkhovna Rada published posts and organizations",
            "public_office",
            "UA",
            "https://data.rada.gov.ua/open/data/mps-skl9",
            "Published posts and organizations by convocation with member identifiers, without post date ranges. VII includes 2012–2014 and cannot be restricted to 2014 posts from this file alone. No inferred annual office status or party affiliation. Attribution: Апарат Верховної Ради України.",
            {"term": {"enum": ["7", "8", "9"], "default": "9"}},
        ),
        "ua_cec_elected_2020": Dataset(
            "UA_CEC",
            "CEC elected local deputies and heads, 2020 election cycle",
            "public_office",
            "UA",
            "https://www.cvk.gov.ua/pls/vm2020/pvm013pt001f01=695.html",
            "Election-result records including published repeat/by-elections, not current office holders. Structural source keys identify rows, not people. Birth dates, residential places, education and personal party membership are excluded from normalized records. Original archive is restricted to counsel; attribution: Центральна виборча комісія України.",
            {},
        ),
    }
)

PROVIDERS = frozenset(d.provider for d in DATASETS.values())
