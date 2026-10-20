import asyncio
import json

import httpx
import pytest

from app import worldbank
from test_worldbank import fixture_raw


class Stream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


@pytest.mark.parametrize("status,headers,body,valid", [
    (200, {"content-type": "application/json"}, fixture_raw(), True),
    (302, {"location": "https://evil.example"}, b"", False),
    (500, {}, b"error", False),
    (200, {"content-type": "text/html"}, fixture_raw(), False),
    (200, {"content-type": "application/json", "content-encoding": "gzip"}, b"tiny", False),
    (200, {"content-type": "application/json"}, b"x" * (worldbank.MAX_BYTES + 1), False),
], ids=["json", "redirect", "server-error", "html", "compressed", "oversized"])
def test_bounded_transport(monkeypatch, status, headers, body, valid):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, stream=Stream(body))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(worldbank.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    if valid:
        snap = asyncio.run(worldbank.fetch_snapshot("PRT", "SP.POP.TOTL", 2024, 2024))
        assert snap.raw == body
    else:
        with pytest.raises((ValueError, httpx.HTTPError)):
            asyncio.run(worldbank.fetch_snapshot("PRT", "SP.POP.TOTL", 2024, 2024))
    assert len(calls) == 1
    assert calls[0].url.host == "api.worldbank.org"


@pytest.mark.parametrize("meta", [None, {}, {"page": 1, "pages": 2, "total": 200},
                                      {"page": 1, "pages": 1, "total": 2}])
def test_partial_pagination_is_rejected(meta):
    doc = json.loads(fixture_raw())
    doc[0] = meta
    with pytest.raises(ValueError, match="metadata"):
        worldbank.parse_snapshot(json.dumps(doc).encode(), "x", "PRT", "SP.POP.TOTL", 2024, 2024)


def test_duplicate_json_keys_rejected():
    raw = fixture_raw().replace(b'"value": 12345', b'"value": 12345, "value": 98765')
    with pytest.raises(ValueError, match="duplicate JSON"):
        worldbank.parse_snapshot(raw, "x", "PRT", "SP.POP.TOTL", 2024, 2024)
