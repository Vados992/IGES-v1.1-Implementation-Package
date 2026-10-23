"""Bounded official/public-market source adapters with exact receipts and replayable parsing."""

from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
import re

import httpx

from app.external_catalog import DATASETS
from app.source_json import load_source_json

MAX_BYTES = 2_000_000
MAX_RECORDS = 20_000
ADAPTER_VERSION = "iges-public-sources/1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("INVALID_SOURCE_NUMBER")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("INVALID_SOURCE_NUMBER") from None
    if not parsed.is_finite() or len(parsed.as_tuple().digits) > 80 or abs(parsed.adjusted()) > 40:
        raise ValueError("INVALID_SOURCE_NUMBER")
    return str(parsed)


def integer(value):
    result = number(value)
    if (
        result is None
        or Decimal(result) != Decimal(result).to_integral_value()
        or not 0 <= Decimal(result) <= 10**12
    ):
        raise ValueError("INVALID_SOURCE_COUNT")
    return int(Decimal(result))


def text(value, max_length=1000):
    if value is not None and (not isinstance(value, str) or len(value) > max_length):
        raise ValueError("INVALID_SOURCE_TEXT")
    return value


def validate_query(dataset, params, page=1, limit=100, adapter_version=None):
    if dataset not in DATASETS or not isinstance(params, dict):
        raise ValueError("UNKNOWN_DATASET")
    spec = DATASETS[dataset]
    version = adapter_version or ("iges-public-sources/2" if dataset == "nyc_acris" else ADAPTER_VERSION)
    if version != ADAPTER_VERSION and not (dataset == "nyc_acris" and version == "iges-public-sources/2"):
        raise ValueError("SOURCE_ADAPTER_VERSION_MISMATCH")
    if set(params) - spec.parameters.keys():
        raise ValueError("UNSUPPORTED_SOURCE_PARAMETER")
    if type(page) is not int or not 1 <= page <= 100 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("PAGE_OR_LIMIT_OUT_OF_RANGE")
    if spec.provider in {"CFTC", "GLEIF"} and limit > 200:
        raise ValueError("SOURCE_PAGE_LIMIT_200")
    query = {}
    for name, rules in spec.parameters.items():
        value = params.get(name, rules["default"])
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError("INVALID_SOURCE_PARAMETER")
        if rules.get("type") == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("INVALID_SOURCE_DATE")
            parsed = date.fromisoformat(value)
            if not date(1990, 1, 1) <= parsed <= datetime.now(timezone.utc).date():
                raise ValueError("SOURCE_DATE_OUT_OF_RANGE")
        if "enum" in rules and value not in rules["enum"]:
            raise ValueError("INVALID_SOURCE_CODE")
        if "pattern" in rules and value != "" and not re.fullmatch(rules["pattern"], value):
            raise ValueError("INVALID_SOURCE_PARAMETER")
        if value == "" and rules["default"] != "":
            raise ValueError("SOURCE_PARAMETER_REQUIRED")
        query[name] = value
    if "start" in query and not query["start"] <= query["end"]:
        raise ValueError("REVERSED_SOURCE_PERIOD")
    if (
        "start" in query
        and (date.fromisoformat(query["end"]) - date.fromisoformat(query["start"])).days > 366 * 10
    ):
        raise ValueError("SOURCE_PERIOD_TOO_WIDE")
    if dataset == "fdic_financials":
        d = date.fromisoformat(query["report_date"])
        if (d.month, d.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
            raise ValueError("QUARTER_END_REQUIRED")
    if dataset == "alpaca_stock_bars":
        symbols = query["symbols"].split(",")
        if (
            not 1 <= len(symbols) <= 20
            or len(set(symbols)) != len(symbols)
            or any(not re.fullmatch("[A-Z][A-Z.-]{0,9}", s) for s in symbols)
        ):
            raise ValueError("INVALID_MARKET_SYMBOLS")
    if dataset.startswith(("ecb_", "boe_", "eurostat_")) and page != 1:
        raise ValueError("DATASET_NOT_PAGED")
    return {
        "dataset": dataset,
        "params": query,
        "page": page,
        "limit": limit,
        "adapter_version": version,
    }


def request_for(query):
    dataset, q, page, limit = (query[k] for k in ["dataset", "params", "page", "limit"])
    spec = DATASETS[dataset]
    if spec.provider == "FDIC":
        fields = {
            "institutions": "CERT,NAME,STALP,ACTIVE,ASSET,DEP,DATEUPDT",
            "financials": "CERT,NAME,REPDTE,ASSET,DEP,NETINC",
            "failures": "CERT,NAME,FAILDATE,FIN,COST,RESTYPE",
        }[spec.variant]
        filters = (
            "ACTIVE:1" + (f" AND STALP:{q['state']}" if q.get("state") else "")
            if spec.variant == "institutions"
            else "REPDTE:" + q["report_date"].replace("-", "")
            if spec.variant == "financials"
            else ""
        )
        return f"https://api.fdic.gov/banks/{spec.variant}", {
            "filters": filters,
            "fields": fields,
            "limit": str(limit),
            "offset": str((page - 1) * limit),
            "sort_by": "CERT",
            "sort_order": "ASC",
            "format": "json",
        }
    if spec.provider == "ECB":
        flow, series = {
            "EXR": ("EXR", f"M.{q.get('currency')}.EUR.SP00.A"),
            "FM": ("FM", "B.U2.EUR.4F.KR.DFR.LEV"),
            "MIR_VOLUME": ("MIR", "M.U2.B.A2C.A.B.A.2250.EUR.N"),
            "MIR_RATE": ("MIR", "M.U2.B.A2C.A.R.A.2250.EUR.N"),
        }[spec.variant]
        return f"https://data-api.ecb.europa.eu/service/data/{flow}/{series}", {
            "startPeriod": q["start"] if flow == "FM" else q["start"][:7],
            "endPeriod": q["end"] if flow == "FM" else q["end"][:7],
            "format": "csvdata",
        }
    if spec.provider == "BOE":
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        def fmt(v):
            d = date.fromisoformat(v)
            return f"{d.day:02d}/{months[d.month - 1]}/{d.year}"

        return "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp", {
            "csv.x": "yes",
            "Datefrom": fmt(q["start"]),
            "Dateto": fmt(q["end"]),
            "SeriesCodes": "IUDBEDR",
            "UsingCodes": "Y",
            "VPD": "Y",
            "VFD": "N",
        }
    if spec.provider == "US_TREASURY":
        return (
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
            {
                "filter": f"record_date:gte:{q['start']},record_date:lte:{q['end']}",
                "page[size]": str(limit),
                "page[number]": str(page),
                "sort": "record_date",
            },
        )
    if spec.provider in {"CFTC", "NYC_DOF"}:
        time = "report_date_as_yyyy_mm_dd" if spec.provider == "CFTC" else "recorded_datetime"
        params = {
            "$limit": str(limit),
            "$offset": str((page - 1) * limit),
            "$where": f"{time} >= '{q['start']}T00:00:00' AND {time} <= '{q['end']}T23:59:59.999'",
            "$order": time + (",cftc_contract_market_code,id" if spec.provider == "CFTC" else ",document_id"),
        }
        if spec.provider == "NYC_DOF":
            params["$select"] = (
                "document_id,record_type,crfn,recorded_borough,doc_type,document_date,document_amt,recorded_datetime,modified_date,percent_trans,good_through_date"
            )
            if query["adapter_version"] == "iges-public-sources/2":
                params["$select"] = ":id as source_row_id," + params["$select"]
                params["$order"] += ",:id"
        return (
            f"https://publicreporting.cftc.gov/resource/{spec.variant}.json"
            if spec.provider == "CFTC"
            else "https://data.cityofnewyork.us/resource/bnx9-e6tj.json"
        ), params
    if spec.provider == "HM_LAND_REGISTRY":
        sparql = """PREFIX ppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX common: <http://landregistry.data.gov.uk/def/common/>
SELECT ?transaction ?price ?date ?type WHERE {
?address common:postcode "POSTCODE".
?transaction ppi:propertyAddress ?address; ppi:pricePaid ?price; ppi:transactionDate ?date; ppi:propertyType ?type.
} ORDER BY ?transaction LIMIT LIMITVAL OFFSET OFFSETVAL"""
        return "https://landregistry.data.gov.uk/landregistry/query", {
            "query": sparql.replace("POSTCODE", q["postcode"])
            .replace("LIMITVAL", str(limit))
            .replace("OFFSETVAL", str((page - 1) * limit)),
            "output": "json",
        }
    if spec.provider == "EUROSTAT":

        def quarter(v):
            d = date.fromisoformat(v)
            return f"{d.year}-Q{(d.month - 1) // 3 + 1}"

        p = {
            "lang": "EN",
            "purchase": "TOTAL",
            "unit": "I15_Q",
            "sinceTimePeriod": quarter(q["start"]),
            "untilTimePeriod": quarter(q["end"]),
        }
        if q["country"] != "ALL":
            p["geo"] = q["country"]
        return "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hpi_q", p
    if spec.provider == "GLEIF":
        p = {
            "filter[entity.legalName]": q["name"],
            "page[size]": str(limit),
            "page[number]": str(page),
            "sort": "lei",
        }
        if q["country"] != "ALL":
            p["filter[entity.legalAddress.country]"] = q["country"]
        return "https://api.gleif.org/api/v1/lei-records", p
    if spec.provider == "ALPACA":
        if page != 1:
            raise ValueError("MARKET_PAGINATION_REQUIRES_EXPLICIT_TOKEN_SUPPORT")
        return "https://data.alpaca.markets/v2/stocks/bars", {
            "symbols": q["symbols"],
            "start": q["start"] + "T00:00:00Z",
            "end": q["end"] + "T23:59:59Z",
            "timeframe": "1Day",
            "feed": "iex",
            "adjustment": "raw",
            "sort": "asc",
            "limit": str(limit),
        }
    raise ValueError("UNKNOWN_DATASET")


@dataclass(frozen=True)
class ExternalSnapshot:
    query: dict
    url: str
    raw: bytes
    records: tuple[dict, ...]
    has_more: bool
    coverage: dict
    transport: str = "HTTPS"

    @property
    def media_type(self):
        provider = DATASETS[self.query["dataset"]].provider
        return (
            "text/csv"
            if provider in {"ECB", "BOE"}
            else "application/sparql-results+json"
            if provider == "HM_LAND_REGISTRY"
            else "application/json"
        )

    @property
    def sha256(self):
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def request_sha256(self):
        return hashlib.sha256(
            canonical({"query": self.query, "transport": self.transport, "url": self.url}).encode()
        ).hexdigest()


def parse_external(raw, query, url, transport="HTTPS"):
    checked = validate_query(
        query["dataset"], query["params"], query["page"], query["limit"], query.get("adapter_version")
    )
    if checked != query:
        raise ValueError("SOURCE_ADAPTER_VERSION_MISMATCH")
    endpoint, params = request_for(query)
    expected_url = str(httpx.URL(endpoint, params=params))
    if url != expected_url or len(raw) > MAX_BYTES:
        raise ValueError("SOURCE_URL_OR_SIZE_MISMATCH")
    spec = DATASETS[query["dataset"]]
    records = []
    seen = set()
    has_more = False
    coverage = {
        "scope": "bounded_query",
        "reported_total": None,
        "unit_policy": "No implicit currency/unit conversion; missing is null",
        "limitations": spec.limitations,
    }

    def add(key, body, locator):
        key = str(key)
        if not key or len(key) > 500 or key in seen:
            raise ValueError("DUPLICATE_OR_INVALID_SOURCE_KEY")
        seen.add(key)
        records.append({"key": key, "body": plain(body), "locator": locator})
        if len(records) > MAX_RECORDS:
            raise ValueError("SOURCE_RECORD_LIMIT")

    if spec.provider in {"ECB", "BOE"}:
        csv.field_size_limit(MAX_BYTES)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        required = (
            {"KEY", "TIME_PERIOD", "OBS_VALUE", "UNIT", "UNIT_MULT"}
            if spec.provider == "ECB"
            else {"DATE", "IUDBEDR"}
        )
        if not required <= set(reader.fieldnames or []):
            raise ValueError("SOURCE_CSV_SCHEMA_CHANGED")
        for i, row in enumerate(reader):
            if None in row or any(v is None for v in row.values()):
                raise ValueError("INVALID_CSV_ROW")
            if spec.provider == "ECB":
                series = endpoint.rsplit("/", 1)[1]
                flow = endpoint.rsplit("/", 2)[1]
                if row["KEY"] != flow + "." + series:
                    raise ValueError("MISMATCHED_SDMX_SERIES")
                period = row["TIME_PERIOD"]
                if (
                    not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", period)
                    or not query["params"]["start"][: len(period)]
                    <= period
                    <= query["params"]["end"][: len(period)]
                ):
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                add(
                    row["KEY"] + ":" + period,
                    {
                        "series": row["KEY"],
                        "period": period,
                        "value": number(row["OBS_VALUE"]),
                        "unit": row["UNIT"],
                        "unit_multiplier": row["UNIT_MULT"],
                        "attributes": {k: v or None for k, v in row.items() if k != "OBS_VALUE"},
                    },
                    f"csv:data-row:{i + 1}",
                )
            else:
                # English month names are parsed without changing the host's locale.
                day, mon, year = row["DATE"].split(" ")
                months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                period = date(int(year), months.index(mon) + 1, int(day)).isoformat()
                if not query["params"]["start"] <= period <= query["params"]["end"]:
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                add(
                    "IUDBEDR:" + period,
                    {
                        "series": "IUDBEDR",
                        "period": period,
                        "value": number(row["IUDBEDR"]),
                        "unit": "percent",
                        "source_date": row["DATE"],
                    },
                    f"csv:data-row:{i + 1}",
                )
    else:
        # Existing strict parser bounds bytes to 2 MiB; retain the stricter JSON limit.
        data = load_source_json(raw)
        if spec.provider == "FDIC":
            source_rows = data["data"]
            meta = data["meta"]
            total = integer(meta["total"])
            requested = meta["parameters"]
            if (
                str(requested["limit"]) != params["limit"]
                or str(requested["offset"]) != params["offset"]
                or requested["filters"] != params["filters"]
            ):
                raise ValueError("SOURCE_QUERY_ECHO_MISMATCH")
            if not isinstance(source_rows, list) or len(source_rows) > query["limit"]:
                raise ValueError("INVALID_SOURCE_PAGE")
            if len(source_rows) != min(query["limit"], max(0, total - (query["page"] - 1) * query["limit"])):
                raise ValueError("INCOMPLETE_SOURCE_PAGE")
            coverage.update(reported_total=total, provider_index=plain(meta.get("index")))
            has_more = query["page"] * query["limit"] < total
            for i, item in enumerate(source_rows):
                row = item["data"]
                key = text(row["ID"])
                cert = number(row.get("CERT"))
                body = {
                    "certificate": cert,
                    "name": text(row.get("NAME")),
                    "source_fields": plain(row),
                    "numeric_units": {},
                }
                for field in {"ASSET", "DEP", "NETINC", "COST"} & row.keys():
                    body["source_fields"][field] = number(row[field])
                    body["numeric_units"][field] = "USD_thousands"
                if spec.variant == "financials" and row["REPDTE"] != query["params"]["report_date"].replace(
                    "-", ""
                ):
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                if spec.variant == "institutions" and integer(row["ACTIVE"]) != 1:
                    raise ValueError("MISMATCHED_INSTITUTION_FILTER")
                if (
                    spec.variant == "institutions"
                    and query["params"]["state"]
                    and row.get("STALP") != query["params"]["state"]
                ):
                    raise ValueError("MISMATCHED_INSTITUTION_STATE")
                add(key, body, f"$.data[{i}].data")
        elif spec.provider == "US_TREASURY":
            source_rows = data["data"]
            total = integer(data["meta"]["total-count"])
            coverage.update(
                reported_total=total,
                source_labels=data["meta"].get("labels"),
                source_types=data["meta"].get("dataTypes"),
            )
            has_more = query["page"] * query["limit"] < total
            for i, row in enumerate(source_rows):
                period = date.fromisoformat(row["record_date"]).isoformat()
                if not query["params"]["start"] <= period <= query["params"]["end"]:
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                add(
                    period,
                    {
                        "period": period,
                        "unit": "USD",
                        "debt_held_public": number(row.get("debt_held_public_amt")),
                        "intragovernmental_holdings": number(row.get("intragov_hold_amt")),
                        "total_public_debt": number(row.get("tot_pub_debt_out_amt")),
                    },
                    f"$.data[{i}]",
                )
        elif spec.provider in {"CFTC", "NYC_DOF"}:
            if not isinstance(data, list) or len(data) > query["limit"]:
                raise ValueError("INVALID_SOURCE_PAGE")
            has_more = len(data) == query["limit"]
            time = "report_date_as_yyyy_mm_dd" if spec.provider == "CFTC" else "recorded_datetime"
            for i, row in enumerate(data):
                if not isinstance(row, dict):
                    raise ValueError("INVALID_SOURCE_ROW")
                period = date.fromisoformat(row[time][:10]).isoformat()
                if not query["params"]["start"] <= period <= query["params"]["end"]:
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                if spec.provider == "CFTC":
                    body = {"period": period, "unit": "contracts", "source_fields": plain(row)}
                    for field in row:
                        if any(
                            part in field for part in ["positions_", "open_interest", "traders_"]
                        ) and not field.startswith(("pct_", "change_")):
                            body["source_fields"][field] = number(row[field])
                    key = text(row["id"])
                else:
                    body = {
                        "period": period,
                        "document_type": text(row.get("doc_type")),
                        "document_amount": number(row.get("document_amt")),
                        "unit": "USD",
                        "source_fields": plain(row),
                    }
                    key = text(
                        row["source_row_id"]
                        if query["adapter_version"] == "iges-public-sources/2"
                        else row["document_id"]
                    )
                add(key, body, f"$[{i}]")
        elif spec.provider == "HM_LAND_REGISTRY":
            source_rows = data["results"]["bindings"]
            if data["head"]["vars"] != ["transaction", "price", "date", "type"]:
                raise ValueError("SOURCE_SPARQL_SCHEMA_CHANGED")
            has_more = len(source_rows) == query["limit"]
            for i, row in enumerate(source_rows):
                uri = text(row["transaction"]["value"])
                if not re.fullmatch(
                    r"http://landregistry.data.gov.uk/data/ppi/transaction/[A-Fa-f0-9-]{36}/current", uri
                ):
                    raise ValueError("UNEXPECTED_PROPERTY_IDENTIFIER")
                add(
                    uri,
                    {
                        "transaction_uri": uri,
                        "price_paid": number(row["price"]["value"]),
                        "unit": "GBP",
                        "period": date.fromisoformat(row["date"]["value"]).isoformat(),
                        "property_type": text(row["type"]["value"]),
                        "query_postcode": query["params"]["postcode"],
                    },
                    f"$.results.bindings[{i}]",
                )
        elif spec.provider == "GLEIF":
            source_rows = data["data"]
            total = integer(data["meta"]["pagination"]["total"])
            paging = data["meta"]["pagination"]
            if (
                integer(paging["currentPage"]) != query["page"]
                or integer(paging["perPage"]) != query["limit"]
            ):
                raise ValueError("SOURCE_PAGINATION_MISMATCH")
            coverage.update(reported_total=total, golden_copy=plain(data["meta"].get("goldenCopy")))
            has_more = query["page"] * query["limit"] < total
            for i, row in enumerate(source_rows):
                lei = text(row["id"])
                a = row["attributes"]
                entity = a["entity"]
                if not re.fullmatch("[A-Z0-9]{20}", lei) or a["lei"] != lei:
                    raise ValueError("INVALID_LEI")
                country = entity["legalAddress"]["country"]
                if query["params"]["country"] != "ALL" and country != query["params"]["country"]:
                    raise ValueError("MISMATCHED_ENTITY_COUNTRY")
                add(
                    lei,
                    {
                        "lei": lei,
                        "legal_name": entity["legalName"]["name"],
                        "jurisdiction": entity.get("jurisdiction"),
                        "country": country,
                        "status": entity.get("status"),
                        "registration": plain(a.get("registration")),
                    },
                    f"$.data[{i}].attributes",
                )
        elif spec.provider == "EUROSTAT":
            if (
                data.get("class") != "dataset"
                or data.get("version") != "2.0"
                or data.get("source") != "ESTAT"
            ):
                raise ValueError("INVALID_JSON_STAT")
            dims = data["id"]
            sizes = [integer(s) for s in data["size"]]
            if len(dims) != len(sizes) or set(dims) != {"freq", "purchase", "unit", "geo", "time"}:
                raise ValueError("JSON_STAT_DIMENSIONS_CHANGED")
            product = 1
            categories = []
            for dim, size in zip(dims, sizes, strict=True):
                cat = data["dimension"][dim]["category"]["index"]
                order = (
                    cat
                    if isinstance(cat, list)
                    else [code for code, pos in sorted(cat.items(), key=lambda kv: integer(kv[1]))]
                )
                if len(order) != size or len(set(order)) != size:
                    raise ValueError("INVALID_JSON_STAT_CATEGORY")
                categories.append(order)
                product *= size
            if product > MAX_RECORDS:
                raise ValueError("SOURCE_RECORD_LIMIT")
            values = data.get("value", {})
            statuses = data.get("status", {})
            if not isinstance(values, (dict, list)):
                raise ValueError("INVALID_JSON_STAT_VALUES")
            if isinstance(values, dict) and any(
                not re.fullmatch(r"0|[1-9][0-9]*", k) or not 0 <= int(k) < product for k in values
            ):
                raise ValueError("INVALID_JSON_STAT_VALUES")
            if isinstance(values, list) and len(values) > product:
                raise ValueError("INVALID_JSON_STAT_VALUES")
            for idx in range(product):
                cursor = idx
                coords = {}
                for dim, size, order in reversed(list(zip(dims, sizes, categories, strict=True))):
                    coords[dim] = order[cursor % size]
                    cursor //= size
                if not re.fullmatch(r"\d{4}-Q[1-4]", coords["time"]):
                    raise ValueError("INVALID_SOURCE_PERIOD")

                def quarter(value):
                    d = date.fromisoformat(value)
                    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"

                if not quarter(query["params"]["start"]) <= coords["time"] <= quarter(query["params"]["end"]):
                    raise ValueError("MISMATCHED_SOURCE_PERIOD")
                if (
                    coords["unit"] != "I15_Q"
                    or coords["purchase"] != "TOTAL"
                    or coords["freq"] != "Q"
                    or query["params"]["country"] != "ALL"
                    and coords["geo"] != query["params"]["country"]
                ):
                    raise ValueError("MISMATCHED_JSON_STAT_SCOPE")
                value = (
                    values.get(str(idx))
                    if isinstance(values, dict)
                    else values[idx]
                    if idx < len(values)
                    else None
                )
                status = (
                    statuses.get(str(idx))
                    if isinstance(statuses, dict)
                    else statuses[idx]
                    if idx < len(statuses)
                    else None
                )
                add(
                    coords["geo"] + ":" + coords["time"],
                    {
                        "dimensions": coords,
                        "period": coords["time"],
                        "value": number(value),
                        "status": status,
                        "unit": "index_2015_100",
                        "updated": data.get("updated"),
                    },
                    f"$.value[{idx}]",
                )
        elif spec.provider == "ALPACA":
            if transport == "MCP_TOOL":
                if (
                    data.get("tool") != "get_stock_bars"
                    or data["request"]["feed"] != "iex"
                    or data["request"]["timeframe"] != "1Day"
                    or data["request"]["start"] != query["params"]["start"]
                    or data["request"]["end"] != query["params"]["end"]
                    or set(data["request"]["symbols"]) != set(query["params"]["symbols"].split(","))
                    or integer(data["request"]["limit"]) != query["limit"]
                ):
                    raise ValueError("CONNECTOR_REQUEST_MISMATCH")
                bars = data["bars"]
                has_more = False
                coverage["capture"] = (
                    "Exact MCP text envelope; connector normalization; HTTP payload/adjustment metadata unavailable"
                )
            elif transport == "HTTPS":
                bars = data["bars"]
                has_more = bool(data.get("next_page_token"))
                coverage["capture"] = "Exact HTTP response; adjustment=raw; IEX"
            else:
                raise ValueError("UNSUPPORTED_SOURCE_TRANSPORT")
            if not isinstance(bars, dict) or not set(bars) <= set(query["params"]["symbols"].split(",")):
                raise ValueError("MISMATCHED_MARKET_SYMBOLS")
            count = 0
            for symbol, items in bars.items():
                for i, row in enumerate(items):
                    when = row.get("timestamp") if transport == "MCP_TOOL" else row["t"]
                    at = datetime.fromisoformat(when.replace("Z", "+00:00"))
                    if (
                        not at.tzinfo
                        or not query["params"]["start"] <= at.date().isoformat() <= query["params"]["end"]
                    ):
                        raise ValueError("INVALID_MARKET_TIMESTAMP")
                    names = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
                    fields = names if transport == "MCP_TOOL" else ["o", "h", "l", "c", "v", "n", "vw"]
                    body = {name: number(row.get(field)) for name, field in zip(names, fields, strict=True)}
                    if (
                        any(body[n] is None for n in ["open", "high", "low", "close"])
                        or Decimal(body["low"]) > min(Decimal(body[n]) for n in ["open", "close", "high"])
                        or Decimal(body["high"]) < max(Decimal(body[n]) for n in ["open", "close", "low"])
                    ):
                        raise ValueError("INCONSISTENT_OHLC")
                    body.update(
                        symbol=symbol,
                        period=when,
                        feed="iex",
                        timeframe="1Day",
                        currency="USD",
                        adjustment="unspecified_by_connector" if transport == "MCP_TOOL" else "raw",
                    )
                    add(symbol + ":" + when, body, f"$.bars.{symbol}[{i}]")
                    count += 1
            if transport == "MCP_TOOL" and integer(data["counts"]["records"]) != count:
                raise ValueError("CONNECTOR_COUNT_MISMATCH")
        else:
            raise ValueError("UNKNOWN_DATASET")
    if spec.provider not in {"EUROSTAT", "ECB", "BOE", "ALPACA"} and len(records) > query["limit"]:
        raise ValueError("SOURCE_EXCEEDED_PAGE_LIMIT")
    coverage["returned_count"] = len(records)
    coverage["missing_observations"] = sum(
        1 for record in records if "value" in record["body"] and record["body"]["value"] is None
    )
    coverage["has_more"] = has_more
    if transport not in {"HTTPS", "MCP_TOOL"} or transport == "MCP_TOOL" and spec.provider != "ALPACA":
        raise ValueError("UNSUPPORTED_SOURCE_TRANSPORT")
    return ExternalSnapshot(query, url, raw, tuple(records), has_more, coverage, transport)


async def fetch_external(dataset, params, page=1, limit=100):
    query = validate_query(dataset, params, page, limit)
    url, arguments = request_for(query)
    expected = str(httpx.URL(url, params=arguments))
    headers = {
        "Accept-Encoding": "identity",
        "User-Agent": "IGES/1.1 (+https://github.com/Vados992/IGES-v1.1-Implementation-Package)",
    }
    if DATASETS[dataset].provider == "ALPACA":
        key, secret = os.getenv("IGES_ALPACA_DATA_KEY"), os.getenv("IGES_ALPACA_DATA_SECRET")
        if not key or not secret:
            raise ValueError("ALPACA_MARKET_DATA_CREDENTIALS_REQUIRED")
        headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    async with asyncio.timeout(60):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", url, params=arguments, headers=headers) as response:
                response.raise_for_status()
                if (
                    response.status_code != 200
                    or response.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise ValueError("UNEXPECTED_SOURCE_RESPONSE")
                mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                allowed = (
                    {"text/csv", "application/csv"}
                    if DATASETS[dataset].provider in {"BOE", "ECB"}
                    else {"application/json", "application/vnd.api+json", "application/sparql-results+json"}
                )
                if mime not in allowed:
                    raise ValueError("UNEXPECTED_SOURCE_MEDIA_TYPE")
                content = bytearray()
                async for chunk in response.aiter_raw():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
                    content.extend(chunk)
    return parse_external(bytes(content), query, expected)
