# Kosh Automated Test Evidence & Verification Guide

Comprehensive breakdown of automated tests, reproduction commands, and mathematical/security proofs implemented across the platform.

---

## Final verification — 2026-10-19

This checkout is **not ready for submission**. Verification used offline-safe settings and no network. Current results supersede earlier counts:

| Check | Actual result |
|---|---|
| Kosh suite (`tests/test_kosh_*.py`) | 34 collection errors; no suite pass count established |
| Isolated submission evidence tests (`--noconftest`) | 7 passed, 1 failed (required exports absent) |
| Frontend tests / build | Blocked: dependencies unavailable; `vitest` / `tsc` missing |
| Canonical demo regeneration / evidence export | Blocked: `cryptography` unavailable |
| Rupee presentation check | All 125 rupee amounts retain identical numeric values |
| Audit verifier | Blocked: no migrated demo database; no verified audit entry count |

Offline dependency installation was attempted. The cache does not contain the pinned `reportlab==5.0.1`; other missing runtime imports include `PyJWT`, `pdfminer` and `pdfplumber`. Logs are local under `private_notes/logs/final_*` and are excluded from Git. Generated evidence, a verified audit count, passing complete checks, deck and recorded video remain required.

---

## 2. How to Reproduce All Tests

### Prerequisites
- Python 3.11 with virtual environment activated (`.venv`).
- Node.js 20+ and npm 10+ (for frontend tests).
- Offline-safe environment variables:
  ```bash
  export SCHEDULER_ENABLED="false"
  export AUTO_MIGRATE="false"
  export COLLECT_ON_STARTUP="false"
  export STARTUP_RECOVERY_ENABLED="false"
  export APP_ENV="development"
  export KOSH_AS_OF_DATE="2026-10-13"
  ```

### Run Focused Kosh Suite
```powershell
# Windows PowerShell
.\.venv\Scripts\pytest.exe -q --tb=line -p no:warnings (Get-ChildItem tests\test_kosh_*.py)
```
```bash
# macOS / Linux Bash
pytest -q --tb=line -p no:warnings tests/test_kosh_*.py
```

### Run Frontend UI Test Suite
```bash
cd frontend
npm test -- --run
npm run build
```

### Run Complete Monolithic Backend Suite
```powershell
# Windows PowerShell
.\.venv\Scripts\pytest.exe -q --tb=line -p no:warnings
```
```bash
# macOS / Linux Bash
pytest -q --tb=line -p no:warnings
```

---

## 3. What Key Test Suites Prove

| Test File | Key Test Names | What the Test Proves |
| :--- | :--- | :--- |
| **`tests/test_kosh_demo_walkthrough.py`** | `test_full_demo_walkthrough_api` | Proves the entire 5-minute judge walkthrough via API: dev login, document quarantine, verified ledger, 13-week forecast, catalogue evaluation, least-cost plan creation, four-eyes segregation of duties, OTP step-up, sandbox settlement, re-forecast, attack injection rejection, kill switch, and audit chain verification. |
| **`tests/test_kosh_stage5_4_security.py`** | `test_security_headers_present_on_api_responses`<br>`test_cors_production_guards_against_wildcard`<br>`test_dev_login_rate_limiting`<br>`test_approval_rate_limiting` | Proves presence of `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Content-Security-Policy`; verifies production startup rejects wildcard CORS `*`; proves in-memory rate limiting stops brute-force attempts on dev login and approval endpoints. |
| **`tests/test_kosh_stage5_4_demo_snapshot.py`** | `test_dev_login_refused_in_production`<br>`test_dev_login_grants_access_to_meenakshi_demo_seller`<br>`test_ledger_excludes_review_payables_and_matches_forecast` | Proves `DEV_LOGIN_ENABLED` is refused when `APP_ENV=production`; verifies dev sign-in with any email receives `OWNER` access to Meenakshi Precision Components; proves open payables exclude poisoned invoices in review. |
| **`tests/test_kosh_stage4_attack_demo.py`** | `test_poisoned_document_flagged_for_review`<br>`test_blocked_document_payment_fails_execution` | Proves adversarial instruction text in PDFs (`INSTRUCTION_TEXT_DETECTED`) quarantines invoices into `REVIEW` and blocks automated payment execution (T4 policy violation). |
| **`tests/test_kosh_stage4_approvals.py`** | `test_t3_creator_needs_other_approver_when_one_exists`<br>`test_single_use_token_and_signature_and_parameter_tampering`<br>`test_token_expiry_and_rejection_revoke_token` | Proves four-eyes control (intent creator cannot self-approve T3 disbursements); proves approval tokens are single-use, 5-minute expiring, and bound cryptographically to `params_hash`. |
| **`tests/test_kosh_stage4_step_up.py`** | `test_otp_hash_encrypted_delivery_success_single_use_and_no_audit_plaintext`<br>`test_three_attempt_limit_and_delivery_rate_limit` | Proves simulated OTP challenges are hashed (HMAC-SHA256), delivered encrypted in the sandbox outbox, lock after 3 invalid attempts, and never expose raw codes in audit logs. |
| **`tests/test_kosh_stage4_hash_chain.py`** | `test_audit_chain_contiguous_and_valid`<br>`test_tampered_audit_chain_fails_verification` | Proves cryptographic SHA-256 hash chaining of all corporate events; verifies that modifying an event payload breaks the audit chain (`PAYLOAD_HASH_MISMATCH`). |
| **`tests/test_kosh_stage5_plan.py`** | `test_plan_orders_by_cost_per_net_rupee`<br>`test_same_seed_proof_verifies_horizon_safety`<br>`test_guaranteed_vs_expected_collections_separation` | Proves greedy least-cost optimization based on cost per net rupee; proves that with `ALL_WEEKS` every horizon week's probability is $\le 0.20$; proves separation between guaranteed and expected plans. |
| **`tests/test_kosh_stage5_2_collections.py`** | `test_msmed_interest_matches_statutory_formula`<br>`test_collections_status_consistency` | Proves MSMED Act Section 15 (45-day cap) and Section 16 penal compound interest calculation (3x RBI bank rate); proves collections push lever consistency between product and invoice levels. |
| **`tests/test_kosh_stage3_reproducibility.py`** | `test_monte_carlo_crn_seed_reproducibility` | Proves that 2,000 Monte Carlo paths generated with Common Random Numbers (`seed=42`) produce 100% bit-exact probabilities and shortfall amounts across runs. |

---

## 4. Standalone Deterministic Verification Scripts

1. **Demonstration Rebuild & Number Generator** (`scripts/kosh_demo_numbers.py`):
   ```bash
   python scripts/kosh_demo_numbers.py
   ```
   Rebuilds the demo database from seed 42, runs forecast $\to$ financing $\to$ plan $\to$ execution $\to$ re-forecast, and outputs `docs/kosh/demo_numbers.md`.
2. **Audit Hash Chain Verifier** (`scripts/verify_audit_chain.py`):
   ```bash
   python scripts/verify_audit_chain.py
   ```
   Re-computes the SHA-256 digest across all sequential audit entries from genesis, verifying 0 broken links and checking security counters.
3. **Instant Demo Reset Script** (`scripts/kosh_demo_reset.py`):
   ```bash
   python scripts/kosh_demo_reset.py
   ```
   Wipes existing demo databases and re-seeds clean canonical state ready for judge click-throughs.
