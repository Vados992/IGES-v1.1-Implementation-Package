# Analyst and reviewer workspace

The controlled workspace is `/workspace`; public versions use `/publication#ID`.
RU/EN is selected in the header. Lists and forms are backed by the actual API,
not bundled research cases. Start with an empty, isolated evaluation database.

## Identity and case access

Use **Sign in with SSO** with a real approved OIDC provider. Missing issuer,
audience, JWKS or signed MFA fails closed. Configure a public `iges-web` client
(or `IGES_OIDC_WEB_CLIENT_ID`), Authorization Code enabled, S256 PKCE required,
password grants/service accounts disabled. Approve the exact HTTPS origin and
`<origin>/workspace` redirect, without wildcards. Browser token exchange requires
that exact web origin at the IdP. Discovery/authorization/token endpoints must
use the trusted HTTPS issuer origin.

Fresh Windows setup defines localhost web origins/redirects on port 8444 alongside
the preserved desktop client. An existing IdP realm is **not** silently changed;
its administrator must configure the web client, role mappings and actual users.
Personal password replacement/OTP enrollment must be performed by each person.
No test receipt proves that the owner has enrolled.

The optional access-token field accepts a valid recent MFA token obtained through
an approved client; the bundled desktop login helper does not print tokens. Tokens
are held in page memory and discarded on disconnect/reload; transient PKCE state
is removed on callback. Use a controlled HTTPS workspace origin.

Current signed global role **and** current case membership must both allow an
action. Creating a case needs analyst/editor. The creator is its owner and can
grant/revoke case memberships; membership alone cannot grant IdP roles. Administrator
is not an evidence/publication role. Use separate real people for independent work.

| Role | Permitted work, subject to membership and content gates |
| --- | --- |
| analyst/editor | Create scoped cases/claims/hypotheses, register sources, upload originals, quote evidence, catalogue entities/relationships; editor controls publication/reply disposition |
| reviewer | Assess assigned claims only, with independence/conflict and quote/provenance checks |
| counsel | Record legal/privacy approval or veto for the exact current content revision |
| panel | Resolve disputed statuses explicitly; must be independent of authors and reviewers |
| respondent | Submit a response with already admitted evidence references; analyst-assisted original intake is currently required |
| reader | Read authorized private case records; cannot alter evidence |

## Research and intake

1. Create a case with jurisdiction, period and scope. Create the exact claim,
   initially UNASSESSED, then a hypothesis with expected observations and falsifiers.
2. Register the actual source: publisher, original HTTPS URL, language, primacy,
   independence group and provenance basis. Leave unknown author/publication day
   null. Derivative documents do not become independent primary sources.
3. Upload unchanged original bytes (8 MiB limit) with source/version. SHA-256,
   size and receipt time are stored. Processing stays PENDING until the separate
   worker passes actual scanning and extraction. FAILED/QUARANTINED is visible;
   never use those files as evidence. Retry is explicit and audited after operator
   diagnosis. Archive/path/encryption/expansion restrictions intentionally reject
   unsafe inputs.
4. Refresh to see READY, then inspect page text and download the original for
   visual comparison. PDF/images use physical page numbers; DOCX/text inputs use
   labelled logical pages. OCR below 0.85 is flagged. Confidence is an OCR engine
   signal, not factual probability. The UI provides text/original controls, not an
   embedded Office page-layout viewer.
5. Copy an exact quotation from a stored page. Record direction and limitations;
   translation is separate. API rejects absent quotes, pages and cross-case IDs.
   Add entity identity basis and evidence-backed, period-scoped relationships.
6. Use search for page fragments, claims and entities. Record revisions and IDs
   are visible. A stale form receives HTTP 412; refresh before making a new intent.
   Retrying the same API intent requires the same Idempotency-Key and payload.

Sources/claims/evidence are append-only. Case changes create a new revision;
claim replacement follows withdrawal and a new superseding claim. Identity alias
resolution can be reversed with an UNDO_MERGE event; underlying records survive.

## Independent review and publication

An owner grants the real reviewer a case membership and assigns the claim. The
reviewer must have the current reviewer role at the IdP, have authored none of its
claim/hypothesis/evidence/originals, declare NO_CONFLICT and explain independence.
They check provenance, quotations, countermaterial and limitations. Low-confidence
OCR requires recorded human comparison to the original. A changed conclusion by
the same reviewer needs new evidence; withdrawal is terminal. Competing conclusions
need an independent panel's explicit per-claim resolution before publication.

Counsel reviews the entire exact public snapshot, including personal information,
copyright, legal basis, retention and source safety. A veto blocks publication.
The editor records either no affected party with reasons, or actual outreach
evidence and a future window of at least 14 days. A response needs evidence and
is carried alongside the conclusion. The software sends no external communications.
New content, including a response, invalidates prior substantive approvals.

The operator must deliberately set `IGES_ENABLE_PUBLICATION=true` in an approved
controlled environment. The editor can then submit a methodology version/text and
reason. Missing/stale reviews, legal/privacy veto or open reply window fail closed.
The published manifest has a SHA-256 and reproducible claims CSV digest. Public
reader verifies the manifest hash; originals and full extracted pages stay private.
Never treat automated test approvals as actual authority to publish a real case.

A correction or retraction must reference the latest publication and give a reason.
It creates a new immutable version; history marks prior versions as superseded.
Do not edit old manifests or delete evidence. Public notification/cache handling,
legal takedown and retention decisions need a separately approved process.

The optional public-data gateway blocks workspace/publication routes. Real public
deployment, sensitive material and multi-tenant operation remain [NO-GO](PRODUCTION_GATES.md).
See [FR status](FR_STATUS.md) for partial P1 features and acceptance limits.
