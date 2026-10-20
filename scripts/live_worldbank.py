"""Bounded official-source probe. Fails visibly; never fabricates a substitute."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.worldbank import fetch_snapshot


def main():
    snap = asyncio.run(fetch_snapshot("PRT", "SP.POP.TOTL", 2022, 2024))
    output = Path("work/live-worldbank")
    output.mkdir(parents=True, exist_ok=True)
    (output / "response.json").write_bytes(snap.raw)
    receipt = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "url": snap.url,
               "sha256": snap.sha256, "observations": len(snap.observations),
               "persisted_to_database": False, "provenance_state": "UNASSESSED"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
