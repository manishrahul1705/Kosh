# Kosh — SME Finance Copilot: Setup Guide for Another Laptop

This guide provides tested, step-by-step instructions to clone, configure, seed, and run the **Kosh — SME Finance Copilot** application on any secondary development machine or judge laptop.

---

## 1. Prerequisites

Ensure the following runtimes and tools are installed before setting up Kosh:

| Requirement | Minimum Version | Recommended / Tested Version | Verification Command |
|---|---|---|---|
| **Python** | 3.11+ | 3.11.9 (or 3.12) | `python --version` or `py -3.11 --version` |
| **Node.js** | 20+ | 20.x or 22.x (Tested on 24.21.0) | `node --version` |
| **npm** | 9+ | 10.x or 11.x | `npm --version` |
| **Git** | 2.30+ | Latest | `git --version` |
| **Tesseract OCR** *(Optional)* | Any | 5.x | `tesseract --version` *(If omitted, image-only scans are safely marked `REVIEW_REQUIRED` without crashing)* |

---

## 2. Clone and Checkout

Clone the repository and use the default `main` branch:

### Windows (PowerShell) / macOS / Linux
```bash
git clone https://github.com/manishrahul1705/Kosh.git
cd Kosh
```

---

## 3. Environment & Dependency Installation

### Step A: Python Virtual Environment & Backend Dependencies

#### Windows (PowerShell)
```powershell
# Create virtual environment
py -3.11 -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install requirements
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### macOS / Linux (bash/zsh)
```bash
# Create virtual environment
python3.11 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip and install requirements
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step B: Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

### Step C: Environment Configuration

Create a `.env` file in the repository root. Kosh works 100% offline out-of-the-box using local SQLite and mock offline AI:

```bash
# Copy example if present, or create .env directly:
```

Create `.env` with the following content:
```env
APP_ENV=development
DATABASE_URL=sqlite:///./kosh_work.db
DEV_LOGIN_ENABLED=true
DEMO_MODE=true
KOSH_AS_OF_DATE=2026-10-13

# Disable background background collectors & schedulers for deterministic demo:
SCHEDULER_ENABLED=false
AUTO_MIGRATE=false
COLLECT_ON_STARTUP=false
STARTUP_RECOVERY_ENABLED=false

# CORS & Server Settings
CORS_ORIGINS=http://localhost:5180,http://127.0.0.1:5180,http://localhost:5180,http://127.0.0.1:5180
SECRET_KEY=kosh-local-showcase-dev-secret-key-32chars-min
```

---

## 4. Database Initialization & Deterministic Demo Seeding

Kosh uses an integer-paise deterministic demo dataset seeded under **Meenakshi Precision Components** (GSTIN `33AABCM1234F1Z5`, seed `42`, as-of date `2026-10-13`).

Run the following commands from the repository root with your virtual environment active:

#### Windows (PowerShell)
```powershell
$env:DATABASE_URL = "sqlite:///./kosh_work.db"

# 1. Generate canonical demo records
python scripts/kosh_generate_demo.py --seed 42 --out demo_data

# 2. Run database schema migrations
python scripts/migrate.py

# 3. Seed canonical demo scenario into SQLite
python scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage

# 4. Optional: Verify SHA-256 tamper-evident audit hash chain
python scripts/verify_audit_chain.py
```

#### macOS / Linux (bash/zsh)
```bash
export DATABASE_URL="sqlite:///./kosh_work.db"

# 1. Generate canonical demo records
python scripts/kosh_generate_demo.py --seed 42 --out demo_data

# 2. Run database schema migrations
python scripts/migrate.py

# 3. Seed canonical demo scenario into SQLite
python scripts/kosh_seed_demo.py --database-url sqlite:///./kosh_work.db --data demo_data --storage private_storage

# 4. Optional: Verify SHA-256 tamper-evident audit hash chain
python scripts/verify_audit_chain.py
```

---

## 5. Starting the Application

You will need **two terminal tabs/windows**: one for the FastAPI backend and one for the Vite frontend dev server.

### Terminal 1: Backend Server (FastAPI on Port 8010)

#### Windows (PowerShell)
```powershell
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "sqlite:///./kosh_work.db"
$env:DEV_LOGIN_ENABLED = "true"
$env:DEMO_MODE = "true"
$env:SCHEDULER_ENABLED = "false"
$env:AUTO_MIGRATE = "false"
$env:COLLECT_ON_STARTUP = "false"
$env:STARTUP_RECOVERY_ENABLED = "false"
$env:APP_ENV = "development"
$env:KOSH_AS_OF_DATE = "2026-10-13"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

#### macOS / Linux
```bash
source .venv/bin/activate
export DATABASE_URL="sqlite:///./kosh_work.db"
export DEV_LOGIN_ENABLED="true"
export DEMO_MODE="true"
export SCHEDULER_ENABLED="false"
export AUTO_MIGRATE="false"
export COLLECT_ON_STARTUP="false"
export STARTUP_RECOVERY_ENABLED="false"
export APP_ENV="development"
export KOSH_AS_OF_DATE="2026-10-13"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

*Verification*: Open `http://127.0.0.1:8010/health` in your browser. It should return `{"status":"ok"}`.

---

### Terminal 2: Frontend Server (Vite on Port 5180)

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5180
```

*Verification*: Open `http://127.0.0.1:5180/` in your browser.

---

## 6. Accessing the Showcase & Demo Credentials

1. Open your browser to `http://127.0.0.1:5180/`.
2. In development mode with `DEV_LOGIN_ENABLED=true`, a **"Quick Dev Login"** card appears on the login screen.
3. Select **Meenakshi Precision Components** (or click **"Sign in as Meenakshi Precision Components"**).
4. You will land on the **Cash Forecast** dashboard (`/cash`).
5. **Interactive Tour**: Click the **"Product Tour"** button in the top navigation header at any time to launch the step-by-step guided tour explaining the 7-step closed-loop cash-gap workflow.

---

## 7. Canonical Demo Numbers (Quick Sanity Reference)

The seed data establishes deterministic figures as of **13 October 2026**:

| Metric / Screen | Canonical Value | Meaning |
|---|---|---|
| **Bank Balance** | ₹24,96,800.00 | Verified closing balance across HDFC & SBI accounts |
| **Receivables** | ₹48,22,400.00 | 5 verified outstanding invoices (₹28.40L overdue) |
| **Payables & Obligations** | ₹38,04,300.00 | 4 vendor bills + GST + loan EMIs |
| **Minimum Safety Buffer** | ₹10,00,000.00 | Target liquidity floor set by the enterprise |
| **Forecast Deficit (Week 6)** | P50: ₹(11,20,535.12) | Projected balance before financing |
| **Peak Deficit (Week 8)** | P50: ₹(12,85,910.12) | Maximum liquidity dip in the 13-week horizon |
| **Recommended Financing** | ₹18,00,000.00 | Invoice Discounting against BHEL-2026-0881 |
| **Post-Action Risk Target** | ≤ 20% in simulation | All 13 weeks satisfy buffer target after simulated financing |
| **Tender Feasibility (BHEL-2026-TND-0042)** | ₹5,50,000.00 | Maximum interim cash outlay required during execution |

---

## 8. Verification & Sanity Test Commands

Run the test suites on the new laptop to verify full environment compatibility:

### Backend Suite
```powershell
# Run the complete Kosh demo walkthrough test:
python -m pytest tests/test_kosh_demo_walkthrough.py -v

# Run the full Kosh test suite:
python -m pytest tests/test_kosh_*.py -q
```

### Frontend Suite & Production Build
```powershell
cd frontend
npm run test -- --run
npm run build
cd ..
```

---

## 9. Troubleshooting & FAQ

### A. Port 8010 or 5180 is already in use

- **Find and stop the conflicting process on Windows**:
  ```powershell
  Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue | Select-Object OwningProcess
  Stop-Process -Id <PID> -Force
  ```
- **Find and stop on macOS / Linux**:
  ```bash
  lsof -i :8010
  kill -9 <PID>
  ```
- **Alternative ports**: If you change the backend port, set `VITE_API_PROXY_TARGET` to its URL before starting Vite. The default proxy already targets `http://127.0.0.1:8010`.

### B. SQLite file locked error (`kosh_work.db`)

If you encounter `sqlite3.OperationalError: database is locked`:
- Ensure only one instance of the FastAPI server or migration script is writing to the database.
- Stop background worker scripts (`SCHEDULER_ENABLED=false`).

### C. Node engine / npm package errors

- Use Node.js version 20 LTS or higher (`node -v`).
- If dependencies encounter version lock issues, delete `node_modules` and run `npm install`.

### D. Missing Tesseract OCR

Tesseract is strictly optional. If not installed, PDF text extraction and CSV bank statements will continue to parse natively; image-based invoices will safely display `REVIEW_REQUIRED` without blocking any financial workflows or the demonstration.
