"""Bounded read-load check on the real-source CI database; not a production SLO certification."""
import asyncio
import json
from pathlib import Path
import time

import httpx


async def main():
    semaphore = asyncio.Semaphore(16)
    timings = []
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=10, trust_env=False) as client:
        async def read():
            async with semaphore:
                started = time.monotonic()
                response = await client.get('/v1/public/observations?country=PRT&indicator=SP.POP.TOTL')
                response.raise_for_status()
                if response.json()['count'] != 3:
                    raise ValueError('Expected the bounded actual-source import of three observations')
                timings.append((time.monotonic() - started) * 1000)
        await asyncio.gather(*(read() for _ in range(96)))
    ordered = sorted(timings)
    p95 = ordered[int(len(ordered) * .95)]
    receipt = {'requests': len(ordered), 'concurrency': 16, 'p95_ms': round(p95, 2),
               'max_ms': round(max(ordered), 2), 'target_p95_ms': 800, 'passed': p95 <= 800,
               'scope': 'Real-source public read API, small disposable CI dataset; not full-scale SLO evidence'}
    Path('work/live-worldbank/performance.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))
    if p95 > 800:
        raise RuntimeError('Bounded read latency exceeded the 800 ms target')


if __name__ == '__main__':
    asyncio.run(main())
