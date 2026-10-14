# 5-Minute Kosh Demonstration Walkthrough Guide

A step-by-step narrative and click path for hackathon judges and evaluators to experience the complete Kosh Cash-Flow Intelligence & Safeguarded Intervention loop on the canonical demonstration company, **Meenakshi Precision Components** (seed 42, as-of `2026-10-13`).

---

## 0. Initial Reset & Launch

Run this single reset command to ensure the database and demo documents are in the canonical starting state:

```powershell
# PowerShell
.\.venv\Scripts\python.exe scripts/kosh_demo_reset.py
```
```bash
# Bash
python scripts/kosh_demo_reset.py
```

### Launch Servers
1. **Backend**:
   ```bash
   export DATABASE_URL="sqlite:///./kosh_work.db"
   export SCHEDULER_ENABLED="false"
   export AUTO_MIGRATE="false"
   export COLLECT_ON_STARTUP="false"
   export STARTUP_RECOVERY_ENABLED="false"
   export APP_ENV="development"
   export DEV_LOGIN_ENABLED="true"
   export KOSH_AS_OF_DATE="2026-10-13"
   uvicorn app.main:app --host 127.0.0.1 --port 8010
   ```
2. **Frontend**:
   ```bash
   cd frontend && npm run dev -- --host 127.0.0.1 --port 5180
   ```
3. **Sign-In**:
   - Navigate to `http://127.0.0.1:5180/login`.
   - In the **Local Dev Sign-In** box, enter any email (e.g. `judge@kosh.local`).
   - Click **Sign in**. The user is instantly provisioned and linked as `OWNER` of **Meenakshi Precision Components**.

---

## 1. Connect (`/connect`) — Ingestion, Consent & Security Quarantine

- **Click path**: Click **Connect** in the left navigation sidebar (`http://127.0.0.1:5180/connect`).
- **What to observe**:
  - **Active Consents**: `BOOKS_EXPORT`, `BANK_STATEMENT`, `SALES_INVOICES`, `PURCHASE_BILLS` active through 2027.
  - **18 Ingested Documents**: 13 customer invoice PDFs, sales register CSV, purchase register CSV, bank statement JSON, and 2 attack documents.
  - **Quarantine Security Flag**:
    - `poisoned_supplier_invoice.pdf` (Invoice `POISON-001`, ₹4,80,000.00)
    - `poisoned_payment_instruction.pdf` (Invoice `POISON-002`, ₹4,80,000.00)
    - Both display a red alert box: **`Instruction-like payment text detected. Review required.`**
    - Status is quarantined as `Needs review` (`REVIEW`), preventing automatic inclusion in open payables or payment execution.

---

## 2. Cash (`/cash`) — 13-Week Monte Carlo Forecast & Cash-Gap Alert

- **Click path**: Click **Cash** in the sidebar (`http://127.0.0.1:5180/cash`).
- **What to observe**:
  - **Interactive Area Chart**: 13-week stochastic distribution showing P10, P50, P90 confidence intervals and the ₹10,00,000 (100,000,000 paise) minimum cash buffer target.
  - **Critical Alert Card**:
    - **Alert Week**: **Week 6** (late November 2026).
    - **Shortfall Probability**: **79.95%** chance of falling below buffer.
    - **Expected Shortfall**: **₹5,11,372.96** (51,137,296 paise).
    - **Peak Expected Shortfall**: **₹5,87,748.92** (58,774,892 paise).
  - **Attribution / Causes**:
    - Deccan Heavy Machines Ltd (CPSE): ₹20,00,000 due date shift (terms 60 days).
    - ABC Industries: ₹7,00,000 delay (+12 days seasonal shift).
  - **Quarantine Safeguard Banner**:
    - Note banner: **`Under review: ₹9,60,000.00 excluded`** (the two quarantined poisoned payables are excluded from forecast commitments).

---

## 3. Plan (`/plan`) — Catalogue Evaluation & Safety-vs-Cost Optimization

- **Click path**: Click **Plan** in the sidebar (`http://127.0.0.1:5180/plan`).
- **What to observe**:
  - **Financing Product Catalogue (8 Products)**:
    1. `TReDS_DISCOUNTING`: **Eligible** (`MATCHED`), 2 invoices eligible (Deccan Heavy Machines CPSE, ₹39,48,316.45). Cost ₹15,407.10 (8.5% annual rate, 15 days).
    2. `BANK_OD_DRAWDOWN`: **Eligible** (`MATCHED`), capacity ₹18,00,000 (180,000,000 paise). Cost ₹15,682.19 (10.5% annual rate).
    3. `COLLECTIONS_PUSH`: **Eligible** (`MATCHED`), 14 invoices eligible. 0 monetary cost (statutory reminder).
    4. `SUPPLIER_TERM_EXTENSION`: **Eligible** (`MATCHED`), 1 invoice eligible. Cost ₹0.
    5. `MUDRA_TARUN`: **Not eligible** (`NOT_MATCHED` — borrowing need exceeds ₹10,00,000 ceiling).
    6. `CGTMSE_TERM_LOAN`: **Needs review** (`REVIEW_REQUIRED` — MSE certificate missing).
    7. `VENDOR_FINANCING`: **Not eligible** (`NOT_MATCHED` — lack of 24-month supplier history).
    8. `INVOICE_FACTORING`: **Not eligible** (`NOT_MATCHED` — non-recourse factoring criteria unmet).
  - **Guaranteed Plan vs. Expected with Collections**:
    - **Guaranteed Plan Card**:
      - Total cost: **₹15,407.10** (TReDS on Invoice 395).
      - Alert week probability: **6.25%** (verified $\le$ 20.00% target across all weeks).
      - Verification status: **`Valid`**.
    - **Expected with Collections Card**:
      - Reminders cost ₹0 monetary fees but receipt timing is uncertain.
    - **Savings Comparison**:
      - NBFC Baseline Unsecured Cost: **₹84,128.14**
      - Guaranteed Plan Cost: **₹15,407.10**
      - Cost Savings: **81.7% saving** (₹68,721.04 saved).
  - **Safety vs Cost Curve**:
    - Interactive selector for 40%, 30%, 20%, 10% safety targets with same-seed verification.
  - **Per-Week Comparison Chart**:
    - Shows before vs after shortfall probabilities dropping below 20% across all 13 horizon weeks.

---

## 4. Approvals (`/approvals`) — Policy Engine, Tier Badges & Step-Up OTP

- **Click path**: Click **Approvals** in the sidebar (`http://127.0.0.1:5180/approvals`).
- **What to observe**:
  - **SANDBOX Banner**: Prominently visible warning: *SANDBOX: no real money moves*.
  - **Proposing Plan Lines**:
    - Click **Propose TReDS_DISCOUNTING (Line 1)**.
    - An action intent is generated in the **Intent inbox**.
  - **Intent Cards**:
    - **T2 Action** (e.g. Collections reminder): Auto-approval / single click.
    - **T3 Action** (Financial disbursement):
      - Tier badge: `T3` (blue badge).
      - Status: `Pending approval` (`PENDING_APPROVAL`).
      - Exact parameters: `{"amount_paise": 194831645, "invoice_id": 395, "product_id": "TReDS_DISCOUNTING"}`.
  - **OTP Step-Up**:
    - Click **Request OTP**.
    - Inspect **Sandbox inbox · private OTP deliveries** at the bottom of the page to copy the 6-digit simulated OTP (e.g. `123456`).
    - Enter the 6-digit OTP into the input field and click **Approve [ID]**.
    - Note the **300-second token expiry countdown**.

---

## 5. Execution, Cool-Off & Re-Forecast

- **Click path**: In `/approvals`, locate the approved TReDS intent.
- **What to observe**:
  - Click **Execute in sandbox [ID]**.
  - **Virtual Sandbox Clock & Payee Cool-Off**:
    - The transaction is processed through the sandbox outbox with simulated clearing and cooling-off checks.
  - **Return to Cash (`/cash`)**:
    - Re-forecast reflects the simulated inflow:
    - **Week 6 probability drops from 79.95% to 6.25%**.
    - All 13 weeks are verified $\le$ 20.00%.

---

## 6. Security Defense Flow — Untrusted Injection Block & Kill Switch

- **Click path**: In `/approvals`.
- **Attack Demonstration**:
  - Click **Test blocked document payment**.
  - The system simulates an attacker attempting to force an automated payment towards `POISON-001`.
  - Result: **BLOCKED**. The policy engine refuses execution because the source document version contains `INSTRUCTION_TEXT_DETECTED` and is untrusted (T4 violation).
  - The incident is logged to security counters.
- **Owner Kill Switch**:
  - Click **Enable seller kill switch**.
  - Confirm the browser confirmation modal: *Enable the seller kill switch?*.
  - Observe that all proposal and execution buttons are immediately disabled.
  - Click **Disable seller kill switch** and confirm to restore normal operations.

---

## 7. Audit Trail (`/audit`) — Cryptographic Hash Chain & Export

- **Click path**: Click **Audit** in the sidebar (`http://127.0.0.1:5180/audit`).
- **What to observe**:
  - **Click "Verify chain"**:
    - Displays: **`VALID, 167 entries`** (or current sequence count, 0 broken links).
    - Every action (forecast run, intent proposal, OTP issuance, approval, execution) is chained via SHA-256 (`entry_hash = H(prev_hash || sequence || action || params)`).
  - **Security Events Counter**:
    - Displays exact counters for `injection detections`, `blocked executions`, and `tamper checks`.
  - **Click "Export JSONL"**:
    - Downloads `kosh-audit-1.jsonl` containing the immutable verifiable ledger.

---

## 8. Modules (`/modules`) & Tender-to-Cash (`/tender-cash`)

- **Modules (`/modules`)**:
  - View all 18 modular feature toggles. Toggle `customer_intelligence` or `revenue`. Notice state persists and adapts the cash loop.
- **Tender-to-Cash (`/tender-cash`)**:
  - Match a live GeM tender to the company's financial capacity.
  - Demonstrates affordability testing without committing real funds.

---

## Summary of Canonical Numbers Verified in Walkthrough

| Item | On-Screen Value | Reference |
| :--- | :--- | :--- |
| **Bank Balance** | ₹24,97,318.42 | Section 1 |
| **Open Receivables** | ₹1,09,48,317.40 | Section 1 |
| **Open Payables (Verified)** | ₹38,03,973.22 | Section 1 |
| **Held for Review (Poisoned)** | ₹9,60,000.00 | Section 1 |
| **Week 6 Gap Prob (Pre-Plan)** | 79.95% | Section 2 |
| **Week 6 Gap Prob (Post-Plan)** | 6.25% | Section 5 |
| **All Horizon Weeks** | $\le$ 20.00% | Section 5 |
| **Guaranteed Plan Cost** | ₹15,407.10 | Section 3 |
| **NBFC Unsecured Baseline** | ₹84,128.14 | Section 3 |
| **Cost Savings vs Baseline** | 81.7% | Section 3 |
| **Audit Chain Verification** | `VALID` (0 broken links) | Section 7 |
