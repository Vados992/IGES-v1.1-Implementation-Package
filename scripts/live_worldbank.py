"""Bounded official-source probe. Fails visibly; never fabricates a substitute."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.worldbank import fetch_snapshot


def main():
    output = Path("work/live-worldbank")
    output.mkdir(parents=True, exist_ok=True)
    try:
        snap = asyncio.run(fetch_snapshot("PRT", "SP.POP.TOTL", 2022, 2024))
    except (httpx.HTTPError, ValueError, TimeoutError, RecursionError) as exc:
        result = {"checked_at": datetime.now(timezone.utc).isoformat(), "status": "UPSTREAM_CHECK_FAILED",
                  "error_type": type(exc).__name__, "persisted_to_database": False, "fallback_used": False}
        (output / "last-run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        raise SystemExit(1) from None
    (output / "response.json").write_bytes(snap.raw)
    receipt = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "url": snap.url,
               "sha256": snap.sha256, "observations": len(snap.observations),
               "persisted_to_database": False, "provenance_state": "UNASSESSED"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    (output / "last-run.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
