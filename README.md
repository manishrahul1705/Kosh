# Kosh

Kosh is an agentic cash-gap treasurer for Indian MSMEs (Topic E: SME Finance Copilot).
All seven steps work end to end in a sandbox: Connect → Understand → Forecast → Alert → Match → Plan & approve → Act & prove.
The seed-42 demo reduces week-6 risk from 79.95% to 6.25%, keeps every week ≤ 20%, and costs ₹15,407.10 versus NBFC ₹84,128.14 (81.7% cheaper).
Every external action needs human approval; money and data-sharing actions need OTP, and all transitions are audited.
Tender-to-Cash and the rebuilt operations modules are add-ons.

## Submission checklist

01. [Technical documentation](docs/kosh/ARCHITECTURE.md)
02. [Deck delivery status](docs/kosh/submission/README.md#02-deck)
03. [Demo video delivery status](docs/kosh/submission/README.md#03-demo-video)
04. [Public source](https://github.com/manishrahul1705/Kosh), [setup and deployment](docs/SETUP.md), [test cases](tests/)
05. [Security self-assessment](docs/kosh/SECURITY_SELF_ASSESSMENT.md)
06. [Execution evidence](docs/kosh/evidence/) and [demo walkthrough](docs/kosh/demo_walkthrough.md)

Full installation instructions: [Setup guide](docs/SETUP.md).

## Features

### Kosh roadmap

1. **Connect** - private business documents and authorized data connections.
2. **Understand** - source-backed business facts and a cash ledger.
3. **Forecast** - thirteen-week cash forecasts.
4. **Alert** - cash-gap and obligation alerts.
5. **Match** - financing products evaluated against business criteria.
6. **Plan & Approve** - gap-closing plans with explicit approvals.
7. **Act & Prove** - authorized sandbox actions and auditable evidence.

Kosh keeps public tender documents separate from private borrower files. Connect manages consent and validated uploads; Ledger shows source-backed receivables, payables, obligations and bank balances; Audit verifies the persisted hash chain.

Starting the app prepares the complete fictional Meenakshi Precision Components business automatically. All 18 modules, business operations, cash plans, approvals, reports, chat history and ten GeM-style tender packages are available without a private backup or a separate seed command. Cash-changing additions await owner confirmation; the canonical seed-42 financial results remain unchanged. Execution stays in a sandbox with no real money movement.

### Documentation for Judges

- **[System Architecture](docs/kosh/ARCHITECTURE.md)**: System design diagram, 7-step closed loop, 18 modules, Monte Carlo forecasting with Common Random Numbers, least-cost optimization, policy tiers, and audit hash chaining.
- **[5-Minute Demo Walkthrough](docs/kosh/demo_walkthrough.md)**: Exact click-path and expected on-screen values from reset to execution.
- **[Canonical Demo Numbers](docs/kosh/demo_numbers.md)**: Deterministic figures for Meenakshi Precision Components (seed 42, as-of `2026-10-13`).
- **[Security Self-Assessment](docs/kosh/SECURITY_SELF_ASSESSMENT.md)**: Threat model, OWASP Top 10 for LLMs, DPDP Act 2023, RBI Digital Lending Directions 2025, FREE-AI controls, penetration attack test results, and known risks.
- **[Statutory Compliance Map](docs/kosh/COMPLIANCE_MAP.md)**: Direct mapping from regulations (MSMED Act Sections 15/16, PMMY caps, TReDS mandate) to Kosh implementations and automated tests.
- **[Automated Test Evidence](docs/kosh/TEST_EVIDENCE.md)**: Current verification status, reproduction instructions, and proof mapping.
- **[Financing Product Catalogue](docs/kosh/financing_catalogue.md)**: Comprehensive specification of all 8 evaluated credit products.

## Final verification — 2026-10-19

Verified offline with seed 42 and as-of `2026-10-13`. These results cover automatic startup and the populated business workspace:

| Check | Actual result |
|---|---|
| Kosh suite (`tests/test_kosh_*.py`) | **342 passed, 1 skipped** (optional SciPy unavailable) |
| Frontend tests / production build | **55 passed across 9 files**; build passed |
| Automatic startup | Missing database populated before requests; restart preserves data; concurrent starts seed once; production never bootstraps |
| Fresh local clone | Dependencies installed from local caches; `start.ps1` started both servers with **no `.env` and no setup/seed command**; **49 page/API reads populated**; temporary checkout removed |
| Canonical financial figures | All **125 rupee values unchanged**; auto-start plan principal/cost, NBFC baseline and week-6 **6.25%** independently checked |
| Execution evidence / audit verifier | Regenerated [`docs/kosh/evidence/`](docs/kosh/evidence/); **VALID, 73 entries**, zero broken links |

The page/read contract is maintained in [`scripts/kosh_data_coverage.py`](scripts/kosh_data_coverage.py). The full local inventory is `private_notes/DATA_COVERAGE.md` (all yes). Logs remain under `private_notes/logs/data_*` and are excluded from Git. Source/commit-message hygiene and private-file checks are clean. PowerShell/shell launchers and Compose configuration passed syntax checks; a Docker runtime was unavailable for a container execution check. Media delivery status remains separate in the submission checklist.

### Judge quick start

Install Python 3.11+ and Node.js with npm, then:

```powershell
# Windows PowerShell
git clone https://github.com/manishrahul1705/Kosh.git
Set-Location Kosh
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Push-Location frontend
npm.cmd ci
Pop-Location
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

```bash
# macOS / Linux
git clone https://github.com/manishrahul1705/Kosh.git
cd Kosh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd frontend && npm ci)
bash start.sh
```

Open **http://127.0.0.1:5180/login** after the launcher reports the workspace is ready and click **Sign in**. The suggested email is prefilled; any email works for local development sign-in. You land on the cash dashboard with **Meenakshi Precision Components** selected. The first start builds the workspace and may take a few minutes; subsequent starts preserve it. No `.env` copy, migration command or seed command is required. Ports are 8010 (API) and 5180 (frontend). Stop the launcher with Ctrl+C.

Alternatively, `docker compose up --build` starts the same two services with a persistent local SQLite volume. Docker requires its images and dependency packages to be available locally or downloadable. Production never bootstraps or permits development sign-in.

Optional tools: `python scripts/kosh_setup.py` explicitly initializes a selected local database; `python scripts/kosh_demo_reset.py` restores the complete clean state after stopping the backend. These tools are not part of normal startup. [Detailed configuration](docs/SETUP.md).

### Tender-to-Cash

Separate GeM module: [Demo guide](docs/gem/PROJECT_DEMO_GUIDE.md) and [architecture](docs/gem/PROJECT_ARCHITECTURE.md).

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

See [PROJECT_ARCHITECTURE.md](docs/gem/PROJECT_ARCHITECTURE.md) for the tender pipeline and [PROJECT_DEMO_GUIDE.md](docs/gem/PROJECT_DEMO_GUIDE.md) for the optional snapshot-based demo.

## Advanced: explicit database and external sign-in

This optional path is for an explicitly managed database and external identity. Normal local use needs only the launcher above. Use Python 3.11 and a Node/npm version supported by the frontend lockfile. Run these commands from the repository root. Do not overwrite an existing `.env` or start the application against a real database unintentionally.

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
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Migrations write only the explicitly selected development database. Normal startup can migrate, recover or schedule when enabled. Configure `SUPABASE_URL` for backend JWT verification and frontend `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` for account login. Identity provisioning does not grant seller membership or operator permissions automatically. Environment secrets are local and ignored.

In a second terminal:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Vite serves port 5180 and proxies `/api` and `/health` to port 8010. Native OCR is optional (`OCR_ENABLED=false` by default). When disabled, intake processes text-layer PDFs directly, and image-only pages remain `REVIEW_REQUIRED`. When enabled (`OCR_ENABLED=true`), local Tesseract CLI is used if present on PATH or `OCR_EXECUTABLE`; if Tesseract is missing or unavailable, the system records `OCR_DEPENDENCY_UNAVAILABLE` and image pages stay `REVIEW_REQUIRED` without halting ingestion. Optional live WhatsApp QR device pairing remains blocked offline (`BLOCKED_OFFLINE`) as live delivery requires authorized external sessions. Low confidence, unsupported scripts and complex scanned tables remain review. Do not enable collection, paid providers or broad workers merely to start an empty workspace.

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
