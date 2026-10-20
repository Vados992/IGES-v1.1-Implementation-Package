"""Verify a fresh live-source pilot returns exactly the stored imported observations."""
import json
from pathlib import Path

import httpx


def main():
    imported = json.loads(Path("work/live-worldbank/database-import.json").read_text())
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        response = client.get("/v1/public/observations?country=PRT&indicator=SP.POP.TOTL")
        response.raise_for_status()
        result = response.json()
        records = result["records"]
        if result["count"] != 3 or {r["period"] for r in records} != {2022, 2023, 2024}:
            raise RuntimeError("Live import did not return all three requested periods")
        for record in records:
            if record["content_sha256"] != imported["sha256"] or record["provenance_state"] != "UNASSESSED":
                raise RuntimeError("Live observation provenance mismatch")
            proof = client.get(f"/v1/public/observations/{record['id']}/provenance")
            proof.raise_for_status()
            if proof.json()["evidence_id"] != imported["evidence_id"]:
                raise RuntimeError("Evidence reference mismatch")
    Path("work/live-worldbank/public-api.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Verified 3 source-attributed observations through the running public API")


if __name__ == "__main__":
    main()
