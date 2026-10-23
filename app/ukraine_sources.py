"""Minimized professional public-office records; exact originals remain separately restricted."""

import csv
from datetime import date, datetime
from decimal import Decimal
import io
import re

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.source_json import load_source_json


def field(value, maximum=1000, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError("UKRAINE_SOURCE_FIELD_CHANGED")
    return value.strip() or None


def source_id(value):
    if isinstance(value, Decimal) and value == value.to_integral_value() and 0 < value < 10**12:
        return str(int(value))
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,11}", value):
        return value
    raise ValueError("UKRAINE_SOURCE_ID_CHANGED")


def source_date(value):
    value = field(value, 10)
    if not value:
        return None
    return date.fromisoformat(value).isoformat()


def parse_roster(raw, term, add):
    data = load_source_json(raw)
    if not isinstance(data, list) or not 1 <= len(data) <= 1000:
        raise ValueError("RADA_ROSTER_SCHEMA_CHANGED")
    excluded, card_ids, repeated = 0, set(), 0
    for index, row in enumerate(data):
        if not isinstance(row, dict) or str(row.get("convocation")) != term:
            raise ValueError("RADA_CONVOCATION_MISMATCH")
        identifier = source_id(row.get("id"))
        repeated += identifier in card_ids
        card_ids.add(identifier)
        start, end = source_date(row.get("date_begin")), source_date(row.get("date_end"))
        if start and end and end < start:
            raise ValueError("RADA_REVERSED_MANDATE")
        if end and end < "2014-01-01":
            excluded += 1
            continue
        registration = field(row.get("nreg"), 80, required=True)
        if not re.fullmatch(r"mp-[a-z0-9_]+_skl" + term, registration):
            raise ValueError("RADA_REGISTRATION_CHANGED")
        name = field(row.get("full_name"), 250, required=True)
        add(
            f"{term}:{identifier}:row:{index}",
            {
                "name": name,
                "search_name": name.casefold(),
                "office": "Народний депутат України",
                "source_card_id": identifier,
                "source_registration": registration,
                "convocation": term,
                "mandate_start": start,
                "mandate_end": end,
                "current_office_status": "NOT_INFERRED_FROM_HISTORICAL_SNAPSHOT",
                "identity_policy": "Rada card identifier; no cross-registry name merge",
                "scope_overlap": "CONFIRMED" if start and end else "OPEN_OR_MISSING_SOURCE_DATES",
            },
            f"$[{index}]",
        )
    return {
        "source_rows": len(data),
        "excluded_ended_before_2014": excluded,
        "repeated_card_id_rows": repeated,
        "duplicate_policy": "Preserved separate source rows; no silent merge",
        "scope": "published_convocation_membership_overlapping_2014_onward",
        "convocation": term,
    }


def parse_cec(raw, add):
    # defusedxml rejects entities/external references; explicit DTD rejection also covers empty DTDs.
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("CEC_XML_DTD_FORBIDDEN")
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=True)
    except (DefusedXmlException, SyntaxError, LookupError):
        raise ValueError("CEC_XML_INVALID") from None
    if root.tag != "result" or not 1 <= len(root) <= 30:
        raise ValueError("CEC_XML_SCHEMA_CHANGED")
    allowed = {
        "result",
        "region",
        "rada",
        "head",
        "deputies",
        "deputy",
        "PIB",
        "DN",
        "N022",
        "F13",
        "F8",
        "F9",
        "F63",
        "F50",
        "F58",
        "DISTRICT",
        "NOMINATED",
        "PROCESS",
        "DATE_OF_APPOINTMENT",
    }
    if any(node.tag not in allowed for node in root.iter()):
        raise ValueError("CEC_XML_SCHEMA_CHANGED")
    regions, councils, counts = set(), set(), {"deputy": 0, "head": 0}
    empty_heads = 0
    for region_index, region in enumerate(root, 1):
        rid = source_id(region.get("id"))
        if region.tag != "region" or rid in regions:
            raise ValueError("CEC_REGION_CHANGED")
        regions.add(rid)
        for council_index, council in enumerate(region, 1):
            cid = source_id(council.get("id"))
            if council.tag != "rada" or (rid, cid) in councils:
                raise ValueError("CEC_COUNCIL_CHANGED")
            councils.add((rid, cid))
            heads = council.findall("head")
            groups = council.findall("deputies")
            if len(heads) > 1 or len(groups) != 1 or len(groups[0]) != len(groups[0].findall("deputy")):
                raise ValueError("CEC_ROLE_SCHEMA_CHANGED")
            for role, people in [("head", heads), ("deputy", groups[0].findall("deputy"))]:
                for index, person in enumerate(people, 1):
                    if role == "head" and not len(person) and not (person.text or "").strip():
                        empty_heads += 1
                        continue
                    if len(person) != len({child.tag for child in person}):
                        raise ValueError("CEC_DUPLICATE_FIELD")
                    decision = field(person.findtext("DATE_OF_APPOINTMENT"), 40)
                    parsed = datetime.strptime(decision, "%d.%m.%Y").date().isoformat() if decision else None
                    locator = f"/result/region[{region_index}]/rada[{council_index}]/" + (
                        f"deputies/deputy[{index}]" if role == "deputy" else "head"
                    )
                    counts[role] += 1
                    name = field(person.findtext("PIB"), 250, required=True)
                    add(
                        f"{rid}:{cid}:{role}:{index}",
                        {
                            "name": name,
                            "search_name": name.casefold(),
                            "office": "Місцевий депутат" if role == "deputy" else "Обраний голова",
                            "source_region_id": rid,
                            "region": field(region.get("name"), 250, required=True),
                            "source_council_id": cid,
                            "council": field(council.get("name"), 500, required=True),
                            "election_process": field(person.findtext("PROCESS"), 250, required=True),
                            "election_decision_date": parsed,
                            "nominating_body": field(person.findtext("NOMINATED"), 500),
                            "person_identifier": None,
                            "mandate_end": None,
                            "current_office_status": "NOT_DETERMINED_FROM_ELECTION_RESULT",
                            "identity_policy": "Structural row key, not a persistent person ID; no name merge",
                        },
                        locator,
                    )
    return {
        "scope": "published_local_election_results_2020_cycle",
        "regions": len(regions),
        "councils": len(councils),
        "role_counts": counts,
        "excluded_empty_head_elements": empty_heads,
        "current_mandate_coverage": "NOT_DETERMINED",
        "normalized_exclusions": [
            "birth_date",
            "residence",
            "education",
            "personal_party_membership",
            "private_employment",
        ],
    }


def parse_posts(raw, term, add):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    # Field contract is checked below; no automatic retention of unknown upstream columns.
    required = {"mp_id", "full_name", "post_name", "unit_name", "post_title"}
    if set(reader.fieldnames or []) != required:
        raise ValueError("RADA_POSTS_SCHEMA_CHANGED")
    count = 0
    for index, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError("RADA_POSTS_SCHEMA_CHANGED")
        identifier = source_id(row["mp_id"])
        name = field(row["full_name"], 250, required=True)
        add(
            f"{term}:{identifier}:row:{index}",
            {
                "name": name,
                "search_name": name.casefold(),
                "source_card_id": identifier,
                "convocation": term,
                "office": field(row["post_name"], 1000, required=True),
                "organization": field(row["unit_name"], 2000),
                "office_title": field(row["post_title"], 3000),
                "mandate_start": None,
                "mandate_end": None,
                "current_office_status": "NO_POST_DATE_RANGES_IN_SOURCE",
            },
            f"csv:row:{index}",
        )
        count += 1
    if not 1 <= count <= 20000:
        raise ValueError("RADA_POSTS_COUNT_CHANGED")
    return {
        "scope": "published_parliamentary_posts_by_convocation",
        "convocation": term,
        "date_coverage": "NO_POST_DATE_RANGES_IN_SOURCE",
        "source_rows": count,
    }
