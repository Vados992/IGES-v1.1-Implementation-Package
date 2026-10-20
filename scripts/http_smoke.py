"""Check a running local pilot; no privileged bypass or fabricated observations."""
import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        for path in ["/healthz", "/readyz", "/v1/public/observations",
                     "/v1/public/observations?country=PRT", "/openapi.json"]:
            response = client.get(path)
            response.raise_for_status()
        response = client.post("/v1/admin/ingest/worldbank", json={
            "country": "PRT", "indicator": "SP.POP.TOTL", "start": 2023, "end": 2024})
        if response.status_code != 503:
            raise RuntimeError(f"Expected unconfigured OIDC denial, received {response.status_code}")
    print("Local API smoke passed; OIDC remains disabled")


if __name__ == "__main__":
    main()
