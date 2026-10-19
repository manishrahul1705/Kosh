# Kosh Automated Test Evidence & Verification Guide

Comprehensive breakdown of automated tests, reproduction commands, and mathematical/security proofs implemented across the platform.

---

## Final verification — 2026-10-19

Verified offline with all scheduler, startup collection, recovery and automatic migration flags disabled (`APP_ENV=development`, `KOSH_AS_OF_DATE=2026-10-13`). These are the current results:

| Check | Actual result |
|---|---|
| Kosh suite (`tests/test_kosh_*.py`) | **337 passed, 1 skipped** (optional SciPy unavailable) |
| Frontend tests / build | **54 passed across 8 files**; production build passed |
| Submission evidence checks (included in Kosh count) | **12 passed** on a separate final rerun |
| Canonical demo regeneration | Passed; all **125 rupee values unchanged**, with Indian grouping |
| Sandbox execution evidence | All six generated artifacts committed under [`evidence/`](evidence/) |
| Audit verifier | **VALID, 73 entries**, zero broken links |

The evidence exporter runs `scripts/verify_audit_chain.py` against its throwaway database before deleting it and saves the actual output. Its additional approved reminder and blocked-action checks explain why this 73-entry export has more audit entries than the separate canonical numbers run. The reminder creates no cash receipt. Test/build logs remain local under `private_notes/logs/final_*`; private databases, delivery credentials and storage are excluded from Git. Media delivery status is tracked separately in the submission checklist.

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
.\.venv\Scripts\pytest.exe -q --tb=line -p no:warnings --basetemp private_notes/final_pytest_run (Get-ChildItem tests\test_kosh_*.py)
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

| Test file | Named checks | What they prove |
|---|---|---|
| `tests/test_kosh_demo_walkthrough.py` | `test_full_demo_walkthrough_api` | End-to-end API walkthrough: forecast, eligibility, planning, approval, OTP, settlement, security denials and audit integrity. |
| `tests/test_kosh_stage5_4_security.py` | `test_security_headers_present_on_api_responses`<br>`test_cors_production_guards_against_wildcard`<br>`test_dev_login_rate_limiting`<br>`test_approval_rate_limiting` | Security headers, production CORS guards and bounded login/approval attempts. |
| `tests/test_kosh_stage4_attack_demo.py` | `test_seeded_payment_injection_is_data_and_forced_action_is_blocked` | Instruction-bearing invoices remain review data; document-origin payments receive a T4 denial. |
| `tests/test_kosh_stage4_approvals.py` | `test_t3_creator_needs_other_approver_when_one_exists`<br>`test_single_use_token_and_signature_and_parameter_tampering` | Another approver is required when available; exact-parameter, signed approvals reject tampering and replay. |
| `tests/test_kosh_stage4_step_up.py` | `test_otp_hash_encrypted_delivery_success_single_use_and_no_audit_plaintext`<br>`test_three_attempt_limit_and_delivery_rate_limit` | Hashed OTPs, encrypted delivery, single use and attempt/rate limits. |
| `tests/test_kosh_stage4_audit_export.py` | `test_export_preserves_chain_links_without_foreign_payloads`<br>`test_cli_verifies_scoped_export_against_same_database` | Tenant-private exports preserve chain anchors and the audit verification CLI accepts a valid scoped snapshot. |
| `tests/test_kosh_stage3_2.py` | `test_target_is_inclusive_threshold_is_strict_and_every_week_is_checked`<br>`test_collection_and_discount_caps_cannot_double_finance_same_invoice` | All-weeks safety constraints and prevention of duplicate financing of the same receivable. |
| `tests/test_kosh_stage5_collections.py` | `test_payment_period_and_due_boundary`<br>`test_monthly_rests_and_unknown_evidence`<br>`test_native_reminder_needs_t2_approval_before_outbox` | MSMED term caps and monthly compounding; reminders require approval and produce no invented cash receipt. |
| `tests/test_kosh_stage2.py` | `test_determinism_and_fingerprint_changes`<br>`test_historical_inputs_treat_future_payment_as_unknown` | Seed reproducibility, changed-input fingerprints and historical forecast boundaries. |
| `tests/test_kosh_submission_evidence.py` | `test_committed_evidence_is_complete_and_has_no_secrets`<br>`test_committed_audit_chain_and_walkthrough_results`<br>`test_evidence_scanner_rejects_credentials` | Required committed files, independent chain hashing, lifecycle and 403 evidence, safe forecasts and credential scanning. |

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
   Recomputes payload digests and chained event hashes from genesis. The evidence exporter runs this CLI against its throwaway database before cleanup and commits the actual output in `evidence/audit_verify.txt`.
3. **Instant Demo Reset Script** (`scripts/kosh_demo_reset.py`):
   ```bash
   python scripts/kosh_demo_reset.py
   ```
   Wipes existing demo databases and re-seeds clean canonical state ready for judge click-throughs.
