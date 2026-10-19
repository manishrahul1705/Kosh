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

Generate and seed the deterministic fictional demo only against an explicitly selected development database:

```powershell
& .\.venv\Scripts\python.exe scripts/kosh_generate_demo.py --seed 42 --out demo_data
$env:DATABASE_URL = 'sqlite:///./kosh_work.db'
& .\.venv\Scripts\python.exe scripts/migrate.py
& .\.venv\Scripts\python.exe scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage
& .\.venv\Scripts\python.exe scripts/verify_audit_chain.py --export-jsonl private_notes/kosh-audit.jsonl
```

The generated data and private storage are ignored. Keep all worker and collection flags disabled while using this local demo.

### Documentation for Judges

- **[System Architecture](docs/kosh/ARCHITECTURE.md)**: System design diagram, 7-step closed loop, 18 modules, Monte Carlo forecasting with Common Random Numbers, least-cost optimization, policy tiers, and audit hash chaining.
- **[5-Minute Demo Walkthrough](docs/kosh/demo_walkthrough.md)**: Exact click-path and expected on-screen values from reset to execution.
- **[Canonical Demo Numbers](docs/kosh/demo_numbers.md)**: Deterministic figures for Meenakshi Precision Components (seed 42, as-of `2026-10-13`).
- **[Security Self-Assessment](docs/kosh/SECURITY_SELF_ASSESSMENT.md)**: Threat model, OWASP Top 10 for LLMs, DPDP Act 2023, RBI Digital Lending Directions 2025, FREE-AI controls, penetration attack test results, and known risks.
- **[Statutory Compliance Map](docs/kosh/COMPLIANCE_MAP.md)**: Direct mapping from regulations (MSMED Act Sections 15/16, PMMY caps, TReDS mandate) to Kosh implementations and automated tests.
- **[Automated Test Evidence](docs/kosh/TEST_EVIDENCE.md)**: Current verification status, reproduction instructions, and proof mapping.
- **[Financing Product Catalogue](docs/kosh/financing_catalogue.md)**: Comprehensive specification of all 8 evaluated credit products.

## Final verification — 2026-10-19

Verified offline with all scheduler, startup collection, recovery and automatic migration flags disabled (`APP_ENV=development`, `KOSH_AS_OF_DATE=2026-10-13`). These are the current results:

| Check | Actual result |
|---|---|
| Kosh suite (`tests/test_kosh_*.py`) | **337 passed, 1 skipped** (optional SciPy unavailable) |
| Frontend tests / build | **54 passed across 8 files**; production build passed |
| Submission evidence checks (included in Kosh count) | **12 passed** on a separate final rerun |
| Canonical demo regeneration | Passed; all **125 rupee values unchanged**, with Indian grouping |
| Sandbox execution evidence | All six generated artifacts committed under [`docs/kosh/evidence/`](docs/kosh/evidence/) |
| Audit verifier | **VALID, 73 entries**, zero broken links |

The evidence exporter runs `scripts/verify_audit_chain.py` against its throwaway database before deleting it and saves the actual output. Its additional approved reminder and blocked-action checks explain why this 73-entry export has more audit entries than the separate canonical numbers run. The reminder creates no cash receipt. Test/build logs remain local under `private_notes/logs/final_*`; private databases, delivery credentials and storage are excluded from Git. Media delivery status is tracked separately in the submission checklist.

### Judge quick start

To run the complete Kosh demo end-to-end (seed 42, as-of `2026-10-13`, forecast, financing evaluation, gap-closing plan at target 0.20, and Stage 4 sandbox execution):

#### Prerequisites
- **Python**: Python 3.11 (tested on `3.11.9`).
- **Node & npm**: Node 24 and npm 11 (tested on Node `v24.21.0`, npm `11.11.1`).
- **OCR (Optional)**: Tesseract CLI on PATH or `OCR_EXECUTABLE`. If missing, image-only documents remain honestly marked as `REVIEW_REQUIRED` without raising errors.

#### Option A: Windows PowerShell

```powershell
# 1. Clone repository
git clone https://github.com/manishrahul1705/Kosh.git
Set-Location Kosh

# 2. Create and activate Python 3.11 virtual environment
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Install frontend dependencies
Push-Location frontend
npm.cmd ci
Pop-Location

# 4. Copy configuration
Copy-Item .env.example .env
# Offline defaults work out of the box (SQLite, mock/offline AI, local auth).
# For dev-mode sign in without Supabase, DEV_LOGIN_ENABLED=true is used below.

# 5. Run database migrations
$env:DATABASE_URL = 'sqlite:///./kosh_work.db'
& .\.venv\Scripts\python.exe scripts/migrate.py

# 6. Generate and seed demo data (Meenakshi Precision Components, seed 42)
& .\.venv\Scripts\python.exe scripts/kosh_generate_demo.py --seed 42 --out demo_data
& .\.venv\Scripts\python.exe scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage

# 7. Start backend API server on port 8010 (Terminal 1)
$env:DATABASE_URL = 'sqlite:///./kosh_work.db'
$env:SCHEDULER_ENABLED = 'false'
$env:AUTO_MIGRATE = 'false'
$env:COLLECT_ON_STARTUP = 'false'
$env:STARTUP_RECOVERY_ENABLED = 'false'
$env:APP_ENV = 'development'
$env:DEV_LOGIN_ENABLED = 'true'
$env:KOSH_AS_OF_DATE = '2026-10-13'
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# 8. Start frontend dev server on port 5180 (Terminal 2)
Push-Location frontend
npm.cmd run dev -- --host 127.0.0.1 --port 5180
Pop-Location

# 9. Verify and run test suites (Terminal 3)
& .\.venv\Scripts\python.exe -m pytest -q --tb=line -p no:warnings (Get-ChildItem tests\test_kosh_*.py)
Push-Location frontend
npm.cmd run test -- --run
npm.cmd run build
Pop-Location

# 10. Run canonical demonstration numbers script & audit verification
& .\.venv\Scripts\python.exe scripts/kosh_demo_numbers.py
# (Note: runs 2,000 Monte Carlo paths; takes 3-7 minutes)
& .\.venv\Scripts\python.exe scripts/verify_audit_chain.py
```

#### Option B: macOS / Linux bash

```bash
# 1. Clone repository
git clone https://github.com/manishrahul1705/Kosh.git
cd Kosh

# 2. Create and activate Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Install frontend dependencies
(cd frontend && npm ci)

# 4. Copy configuration
cp .env.example .env
# Offline defaults work out of the box (SQLite, mock/offline AI, local auth).
# For dev-mode sign in without Supabase, DEV_LOGIN_ENABLED=true is used below.

# 5. Run database migrations
export DATABASE_URL="sqlite:///./kosh_work.db"
python scripts/migrate.py

# 6. Generate and seed demo data (Meenakshi Precision Components, seed 42)
python scripts/kosh_generate_demo.py --seed 42 --out demo_data
python scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage

# 7. Start backend API server on port 8010 (Terminal 1)
export DATABASE_URL="sqlite:///./kosh_work.db"
export SCHEDULER_ENABLED="false"
export AUTO_MIGRATE="false"
export COLLECT_ON_STARTUP="false"
export STARTUP_RECOVERY_ENABLED="false"
export APP_ENV="development"
export DEV_LOGIN_ENABLED="true"
export KOSH_AS_OF_DATE="2026-10-13"
uvicorn app.main:app --host 127.0.0.1 --port 8010

# 8. Start frontend dev server on port 5180 (Terminal 2)
(cd frontend && npm run dev -- --host 127.0.0.1 --port 5180)

# 9. Verify and run test suites (Terminal 3)
source .venv/bin/activate
pytest -q --tb=line -p no:warnings tests/test_kosh_*.py
(cd frontend && npm run test -- --run && npm run build)

# 10. Run canonical demonstration numbers script & audit verification
python scripts/kosh_demo_numbers.py
# (Note: runs 2,000 Monte Carlo paths; takes 3-7 minutes)
python scripts/verify_audit_chain.py
```

#### Logging in and What to Click First

1. Open `http://127.0.0.1:5180/login` in your web browser.
2. In the **Local Dev Sign-In** box, enter any email address (e.g. `judge@example.com` or `demo@meenakshi.example`). Click **Sign in**.
   - *Automatic Demo Seller Association*: Any dev sign-in email automatically receives `OWNER` access to the seeded demo seller **Meenakshi Precision Components** (accessible via `/api/sellers` and `/api/kosh/sellers/{id}/ledger`).
   - *Production Guard*: `DEV_LOGIN_ENABLED` is strictly refused and blocked when `APP_ENV=production` (enforced by both `Settings.assert_startup_safe` and `dev_login.install`).
3. **What to click first**:
   - **Connect**: View the 18 ingested documents, including commercial invoices, bank statements, and the quarantined poisoned invoice marked with `INSTRUCTION_TEXT_DETECTED`.
   - **Cash**: View the 13-week cash forecast with the Week 6 critical cash-gap alert (79.95% shortfall probability below ₹10,00,000 buffer).
   - **Plan**: Inspect all 8 financing products evaluated against catalogue rules, the cost-minimized Guaranteed Plan (TReDS on Invoice 395 saving 81.7% vs NBFC baseline), and the Safety vs Cost curve.
   - **Approvals**: Review proposed action intents, submit OTP step-up for T3 actions, and execute sandbox settlement.
   - **Audit**: Verify the cryptographic SHA-256 tamper-evident hash chain and inspect security incident counters.

#### Expected Canonical Demo Numbers
- **Business Snapshot**:
  - Bank Balance: ₹24,97,318.42 (249,731,842 paise)
  - Open Receivables: ₹1,09,48,317.40 (1,094,831,740 paise)
  - Open Payables (Verified): ₹38,03,973.22 (380,397,322 paise)
  - Held for Review (Payables): ₹9,60,000.00 (96,000,000 paise) *(quarantined poisoned invoices POISON-001 & POISON-002)*
  - Cash Buffer Target: ₹10,00,000.00 (100,000,000 paise)
- **Baseline Week 6 Shortfall Probability**: 79.95% before $\rightarrow$ 6.25% after execution
- **Horizon-Wide Safety Target**: All 13 horizon weeks achieve $\le$ 20.00% probability below buffer
- **Guaranteed Plan Cost**: ₹15,407.10 (TReDS Invoice 395) vs ₹84,128.14 (NBFC Unsecured baseline) $\rightarrow$ **81.7% cost savings**
- **Audit Chain**: 167 entries, status **`VALID`** (0 broken links)

#### Troubleshooting
- **Port already in use**: If port 8010 or 5180 is taken by another service, change `--port <port>` (if changing backend port, update Vite's proxy in `frontend/vite.config.ts`).
- **Wrong Python version**: Ensure Python 3.11 is used (`python --version` or `py -3.11`). Python 3.12+ may encounter package compatibility issues.
- **Tesseract missing**: Tesseract is entirely optional. If missing from `PATH`, OCR fields remain honestly marked as `REVIEW_REQUIRED` without halting ingestion.
- **PowerShell Execution Policy**: If `.venv\Scripts\Activate.ps1` gives an execution policy error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or execute Python directly via `& .\.venv\Scripts\python.exe`.


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
