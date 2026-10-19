# Kosh local startup

The business is fictional and deterministic (seed 42, as-of 2026-10-13). All execution is sandboxed. Python 3.11+ and Node.js/npm are required; Tesseract is optional for image-only uploads.

## Clone, install, start

```powershell
git clone https://github.com/manishrahul1705/Kosh.git
Set-Location Kosh
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Push-Location frontend
npm.cmd ci
Pop-Location
.\start.ps1
```

On macOS/Linux use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, `(cd frontend && npm ci)`, then `bash start.sh`.

Wait for the ready URL, open **http://127.0.0.1:5180/login** and click **Sign in** with the suggested email. Any local email receives membership in Meenakshi Precision Components and opens the cash dashboard. The launcher runs both servers (API 8010, frontend 5180). Ctrl+C stops them.

No configuration-file copy, migration or seeding step is required. The backend automatically migrates and populates a missing, empty or non-Kosh development database before accepting requests. A file lock spans the seed transactions, and the existing SQLite writer reservation protects the readiness check. Existing Kosh data is preserved. The first run can take a few minutes. The ready line is `Kosh workspace ready: Meenakshi Precision Components`.

## Optional configuration and deployment

Development defaults are `sqlite:///./kosh_work.db`, local sign-in enabled, automatic workspace bootstrap enabled, and external collection/scheduling disabled. You may set `DATABASE_URL` to select another SQLite file. `KOSH_AUTO_BOOTSTRAP=false` opts out; read-only verification mode also skips bootstrap. `.env.example` is optional. Environment values override it.

`docker compose up --build` runs both services with the same ports and persists SQLite under `data/`. The frontend waits for the API health check. Container builds need installed or cached images/packages; this does not enable external business operations.

For production use `APP_ENV=production`, `DEV_LOGIN_ENABLED=false`, `AUTO_MIGRATE=false`, a stable approval secret of at least 32 bytes, explicit CORS origins and configured authentication. Apply migrations with `python scripts/migrate.py` before deployment. Bootstrap never runs in production, even if `KOSH_AUTO_BOOTSTRAP=true`. The frontend production build disables local sign-in. Run `npm run build` in `frontend` for the production assets.

## Optional reset and explicit setup

Stop the backend before a reset:

```powershell
.\.venv\Scripts\python.exe scripts/kosh_demo_reset.py
```

This restores the full clean business state in the selected repository-local SQLite file. `scripts/kosh_setup.py` is an optional explicit initializer, not a prerequisite to starting the app. Generated borrower files, databases and configuration remain local and ignored by Git.

The seeded operations include customers/suppliers and cities, stock and shortages, RFQs/quotes, proposed orders, shipments, material-price history, goals, onboarding, workflows, knowledge, collections with statutory terms, revenue history, reports, chat and approvals. Cash proposals remain excluded from the confirmed forecast until an owner confirms them. Public tender pages use ten locally generated GeM-style packages; no backup database is required.

If a port is occupied, stop its owner or use a custom server invocation and set `VITE_API_PROXY_TARGET` to the chosen API URL. Missing Tesseract marks image-only files for review; text-layer PDFs still work. [Verification results](kosh/TEST_EVIDENCE.md).
