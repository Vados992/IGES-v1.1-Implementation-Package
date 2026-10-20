# IGES security model — implementation boundaries

## Verified prerequisites / trust boundaries

The pilot handles **only public World Bank economic indicators** in a single configured project. It does not solicit or retain confidential whistleblower identities. Do not upload confidential identities or classified material into this pilot.

Internet clients never send arbitrary fetch URLs. The World Bank adapter constructs an HTTPS URL from a three-letter country, a strict allowlist of indicator IDs and bounded years. Redirects are disabled, response sizes and row counts are bounded, and both metadata and country/indicator/year identity are checked.

All privileged API methods require a validated issuer, audience, expiry, `sub`, project claim and role from OIDC JWKS. With no issuer configuration, writes return HTTP 503; no hardcoded administrative token or bypass exists. Privileged users should use phishing-resistant MFA at the identity provider, which must be independently verified.

The runtime principal is not a superuser and has no BYPASSRLS. Tables use forced
RLS and append-only grants. Policies require both the transaction-local project
context and an administrator-owned mapping of `session_user` to the pilot project;
changing the session context cannot grant access to another project. Read endpoints
use read-only transactions. The runtime cannot read or change its project mapping.
This is still a single-project pilot: hostile multi-tenant deployment requires an
independent RLS/BOLA assessment and a complete identity/provisioning design.

Evidence stores source raw bytes and SHA-256. A checksum does not establish truthful content; attestation of official origin is different from claim verification. Reviews cannot be submitted by a claim's author, and there is no public allegation-publishing endpoint.

## Threat scenarios and expected behavior

| Threat | Pilot control | Residual limitation |
| --- | --- | --- |
| Forged upstream JSON | Shape / identity validation and source URL allowlist | Source itself could be wrong or compromised |
| Prompt injection | No LLM execution or agent tools in deployed pilot | Red-team any later AI addition |
| IDOR/BOLA | Fixed project and forced RLS | Multi-project verification not completed |
| Credential theft | Strict OIDC validation; MFA must be configured externally | IdP configuration unverified |
| Insider tampering | Append-only runtime grants; per-project hash-chained events | Superuser control, no independent anchor |
| Source deanonymization | No confidential-source ingestion | Dedicated vault and DPIA required |
| Amount inflation | Financial lifecycle segmentation, idempotency keys | No external banking reconciliation |
| Network/service outage | Docker restart and DB persistence | No production HA or measured recovery |
| Source-citation falsification | Raw snapshot, retrieval URL and row locator | No signed publisher attestation by default |

## Known high-priority gaps

- External audit anchoring, signed attestations and separated key custody.
- Dedicated object storage with immutable retention, backup encryption, KMS and PITR.
- Independent penetration testing and sustained performance characterization.
- API rate limiting and reverse proxy WAF / TLS / IP filtering.
- Source attribution licensing, data retention policy, DPIA and correction process.
- External reconciliation of source-backed financial events; concurrency invariants
  are now enforced with transactional locks and database checks, and exercised in CI.
- Continuous vulnerability scanning, SBOM provenance and image signing.
- Scrutinized OIDC provider claims mappings, MFA enforcement and incident response.

**NO-GO for public multi-tenant or confidential-source use until controls are implemented and tested.**

Request bodies are bounded to 64 KiB even without Content-Length; responses receive
no-store and basic browser safety headers. These controls do not replace proxy TLS,
connection/rate limits, phishing-resistant MFA or an independent security review.
Database statements and lock waits have deadlines. JWKS fetches have a timeout;
key rotation and outage behavior must also be checked against the actual IdP.

The sequence-based audit chain retains its canonical hash input and is checked by
both a database trigger and `python -m app.verify_integrity`. Evidence digests are
also checked in SQL and by the verifier. A database administrator can rewrite an
entire chain or remove its tail; independent externally held anchors remain absent.
Attestation methods describe reviewer assertions; naming `DIGITAL_SIGNATURE` does
not execute a signature validator or establish that a signature was checked.
