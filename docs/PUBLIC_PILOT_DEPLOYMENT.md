# Publish the IGES public-data-only pilot — operator checklist

**Not a production certification.** This controlled mode exposes public economic
observations and publicly attributed procurement award records only, while refusing
administrative requests from the Internet. Do not enable public political accusation
publishing, confidential source intake or multi-tenant research.

## Requirements before making the system reachable

1. Own a domain with DNS A/AAAA records pointing to a dedicated Linux server.
2. Independently review source licenses, controller responsibilities, privacy
   statements, threat model, and data-processing basis.
3. Configure host firewall and operating-system security; keep database private.
4. Establish encrypted offsite backups and rehearse restore with actual measurements.
5. Assign named operators and incident response escalation.
6. Decide whether the public pilot can be approved with outstanding production gates.
7. Do not use a developer laptop as a public server.

## Deployment

On a dedicated host with Docker Compose v2:

```sh
git clone https://github.com/Vados992/IGES-v1.1-Implementation-Package.git
cd IGES-v1.1-Implementation-Package
# Checkout reviewed, merged commit or approved release tag.
cp .env.example .env
# Configure strong distinct POSTGRES_ADMIN_PASSWORD and IGES_DB_PASSWORD
# Add IGES_DOMAIN=your-owned-domain.example to .env
# Add IGES_ACME_EMAIL=operator@your-owned-domain.example to .env
docker compose -f compose.yaml -f deploy/compose.public.yaml config
docker compose -f compose.yaml -f deploy/compose.public.yaml up --build -d
curl --fail https://your-owned-domain.example/readyz
```

Caddy attempts automatic TLS certificate acquisition; it requires correct DNS
and inbound TCP ports 80 and 443. It blocks `/v1/admin/*`, `/docs`,
`/redoc` and `/openapi.json` at the edge. The database is not port-mapped;
API's original port binding remains localhost-only.

The public site is empty until official data are ingested on the trusted host:

```sh
docker compose run --rm api python -m app.seed_worldbank \
  --country PRT --indicator SP.POP.TOTL --start 2022 --end 2024
docker compose run --rm api python -m app.seed_usaspending \
  --fiscal-year 2024 --limit 10
```

To implement periodic ingestion, schedule the exact allowlisted commands
using the host's trusted scheduler with concurrency prevention, retry limits,
monitoring and provider terms-of-service review. **Never provide open proxy-like
source URLs to external clients.**

## Operational cautions

- Never commit `.env`, OIDC secrets or database backups.
- A fresh DB volume is initialized once. Applying schema changes to existing
  persistent DB requires a reviewed migration. Deleting the volume is not an upgrade.
- Managed host backup, WAL/PITR, point-in-time restoration, tests and independent
  audit anchoring must be deployed separately.
- Caddy TLS alone does not satisfy all security gates.
- Keep this reverse proxy restricted to *public* sourced data until independent
  pen testing and formal authorization permit greater functionality.
