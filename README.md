# Kosh

Kosh is an SME cash-flow and financing workspace built around source-backed business information and deterministic decisions. Its Tender-to-Cash module discovers public GeM tenders, extracts requirements, checks document coverage and explains seller matches. Stage 1 adds consent-controlled private intake, deterministic invoice and bank extraction, an integer-paise ledger and an append-only audit chain. Forecasts, financing recommendations and external actions remain later stages.

## Features

### Kosh roadmap

1. **Connect** - private business documents and authorized data connections.
2. **Understand** - source-backed business facts and a cash ledger.
3. **Forecast** - thirteen-week cash forecasts.
4. **Alert** - cash-gap and obligation alerts.
5. **Match** - financing products evaluated against business criteria.
6. **Plan & Approve** - gap-closing plans with explicit approvals.
7. **Act & Prove** - authorized sandbox actions and auditable evidence.

Stage 1 keeps public tender documents separate from private borrower files. Connect manages consent and validated uploads; Ledger shows source-backed receivables, payables, obligations and bank balances; Audit verifies the persisted hash chain.

Generate and seed the deterministic fictional demo only against an explicitly selected development database:

```powershell
& .\.venv\Scripts\python.exe scripts/kosh_generate_demo.py --seed 42 --out demo_data
& .\.venv\Scripts\python.exe scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage
$env:DATABASE_URL = 'sqlite:///./kosh_work.db'
& .\.venv\Scripts\python.exe scripts/verify_audit_chain.py --export-jsonl private_notes/kosh-audit.jsonl
```

The generated data and private storage are ignored. Keep all worker and collection flags disabled while using this local demo.

### Tender-to-Cash

- Public GeM listing discovery, bid identity, changes and deadline/status history.
- Regular bids, reverse auctions, linked main bids and supporting documents.
- Immutable versions, hashes, reference provenance and complete/incomplete packages.
- Native/mixed PDF extraction, optional local Tesseract OCR, validated Office/text/image formats and supported static catalogue tables.
- Structured turnover, experience, exemption and documentary requirements with page/cell/quote evidence.
- Revisioned seller profiles, relevance checks and deterministic Matched / Not matched / Needs review results.
- Membership-authorized seller portal, scoped document downloads and profile refresh flows.
- Optional evidence-grounded Gemini or OpenAI-compatible interpretation; no provider call is required for deterministic matching.

Missing, contradictory, unsupported or uncertain information remains review. Complete material input coverage does not mean every free-form technical or legal clause has been interpreted. Existing central public-tender APIs are not private borrower-document storage.

## Architecture

```text
Public GeM -> discovery -> immutable documents -> text/tables/OCR
           -> structured fields + provenance -> corpus completeness
           -> deterministic eligibility + seller revision -> matching -> portal
```

FastAPI serves authenticated APIs, SQLAlchemy manages persistence and Alembic manages migrations. Database-backed jobs and APScheduler drive optional bounded workers. React, TypeScript, TanStack Query and Tailwind provide the portal. SQLite WAL is supported for local development and allows one writer at a time. Use one scheduler owner and shared absolute lock paths for a deployment.

See [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) for the tender pipeline and [PROJECT_DEMO_GUIDE.md](PROJECT_DEMO_GUIDE.md) for the optional snapshot-based demo.

## Local setup

Use Python 3.11 and a Node/npm version supported by the frontend lockfile. Run these commands from the repository root. Do not overwrite an existing `.env` or start the application against a real database unintentionally.

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$env:DATABASE_URL = 'sqlite:///./kosh_dev.db'
$env:SCHEDULER_ENABLED = 'false'
$env:AUTO_MIGRATE = 'false'
$env:COLLECT_ON_STARTUP = 'false'
$env:STARTUP_RECOVERY_ENABLED = 'false'
$env:APP_ENV = 'development'
$env:DEV_LOGIN_ENABLED = 'false'
$env:DOCUMENT_WORKER_ENABLED = 'false'
$env:EXTRACTION_WORKER_ENABLED = 'false'
$env:FIELD_EXTRACTION_WORKER_ENABLED = 'false'
$env:AI_ANALYSIS_WORKER_ENABLED = 'false'
$env:AI_ANALYSIS_AUTO_QUEUE = 'false'

& .\.venv\Scripts\python.exe scripts/migrate.py
& .\.venv\Scripts\python.exe scripts/migrate.py --check
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Migrations write only the explicitly selected development database. Normal startup can migrate, recover or schedule when enabled. Configure `SUPABASE_URL` for backend JWT verification and frontend `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` for account login. Identity provisioning does not grant seller membership or operator permissions automatically. Environment secrets are local and ignored.

In a second terminal:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Vite serves port 5173 and proxies `/api` and `/health` to port 8000. Native OCR is optional: install Tesseract and suitable language packs separately, then configure `OCR_ENABLED`, `OCR_EXECUTABLE` and `OCR_LANGUAGES`. Low confidence, unsupported scripts and complex scanned tables remain review. Do not enable collection, paid providers or broad workers merely to start an empty workspace.

## Tests

Apply the safe process settings above before backend tests. Tests create migrated temporary databases and retain an offline network guard; production databases and live providers are not test fixtures.

```powershell
& .\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Frontend checks:

```powershell
Set-Location frontend
npx.cmd tsc -b
npm.cmd run test -- --run
npm.cmd run lint
npm.cmd run build
```

Optional rendered React/local-API integration source is retained under `frontend/validation/`. It requires a separately prepared disposable fixture API and is distinct from unit tests or live browser authentication. Scripts under `scripts/` provide targeted migration, inspection, ingestion, recovery and verification operations. Review each selector before running a write-capable or network-capable tool.

## Project structure

```text
app/                 API, persistence, ingestion, evidence and decision services
app/finance/         Reserved ledger, forecast, cost and planning interfaces (kosh)
app/lending/         Reserved financing-criteria adapters (kosh)
app/policy/          Permission tiers and reserved approval interfaces (kosh)
app/audit/           Reserved audit-chain interfaces (kosh)
app/consent/         Reserved consent interfaces (kosh)
app/sandbox/         Reserved external-service adapters (kosh)
frontend/src/        Protected portal, profile and Kosh workspace pages
frontend/validation/ Optional integration-test source
migrations/          Additive schema history
scripts/             Product operation and verification tools
tests/               Offline fixtures and regression tests
```

Local databases, documents, snapshot prerequisites, backups and validation outputs are excluded from Git. Snapshot-based tools require their local input assets and are not portable empty-install seeds. Historical migrations remain for compatibility; a legacy table is not evidence of an active financing feature.

## Licence

The `kosh` branch includes the MIT licence in `LICENSE`. The copyright-holder placeholder must be completed before distribution. Third-party dependencies retain their own licences.
## Cash forecast

Stage 2 adds a deterministic, seeded 13-week cash forecast for each authorized seller. It keeps committed receivables, payables, obligations, and bootstrapped future trading flows separate; reports P10, P50, and P90 closing balances; and raises a cash-buffer alert from the first week whose shortfall probability reaches the configured threshold. Review-state invoices remain visible in the ledger but are excluded from cash flows.

The Cash workspace includes the forecast band, buffer, alert causes, under-review total, rolling backtest coverage, cash-cycle analysis, and a non-persisted what-if view. Forecast runs, acknowledgements, and backtests use the existing seller authorization and append-only audit chain.

Kosh reuses modules from the team's own prior projects, FinCent and GeM Tender Intelligence
