"""Download portable Windows runtimes from their publisher's HTTPS endpoints."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1] / "work/windows-pilot"


def download(client, url, target, expected=None):
    if not target.exists():
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with target.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
    digest = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    if expected and digest != expected:
        raise RuntimeError(f"Publisher checksum mismatch for {target.name}")
    print(json.dumps({"file": target.name, "sha256": digest, "publisher_checksum_verified": bool(expected)}), flush=True)
    return digest


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        release = client.get("https://api.adoptium.net/v3/assets/latest/21/hotspot", params={
            "architecture": "x64", "image_type": "jdk", "os": "windows", "vendor": "eclipse"})
        release.raise_for_status()
        package = release.json()[0]["binary"]["package"]
        artifacts = [
            (package["link"], "jdk.zip", package["checksum"], "java"),
            ("https://github.com/keycloak/keycloak/releases/download/26.8.1/keycloak-26.8.1.zip", "keycloak.zip", None, "identity"),
            ("https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip", "postgres.zip", None, "database"),
        ]
        receipts = []
        for url, filename, expected, directory in artifacts:
            archive = ROOT / filename
            digest = download(client, url, archive, expected)
            destination = ROOT / directory
            if not destination.exists():
                destination.mkdir()
                with zipfile.ZipFile(archive) as bundle:
                    for entry in bundle.infolist():
                        resolved = (destination / entry.filename).resolve()
                        if not resolved.is_relative_to(destination.resolve()):
                            raise RuntimeError("Archive contains an unsafe path")
                    bundle.extractall(destination)
            receipts.append({"url": url, "sha256": digest, "publisher_checksum_verified": bool(expected)})
        (ROOT / "runtime-downloads.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
