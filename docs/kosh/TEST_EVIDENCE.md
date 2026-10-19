# Kosh Automated Test Evidence & Verification Guide

Comprehensive breakdown of automated tests, reproduction commands, and mathematical/security proofs implemented across the platform.

---

## Final verification — 2026-10-19

Verified offline with seed 42 and as-of `2026-10-13`. These results cover automatic startup and the populated business workspace:

| Check | Actual result |
|---|---|
| Kosh suite (`tests/test_kosh_*.py`) | **342 passed, 1 skipped** (optional SciPy unavailable) |
| Frontend tests / production build | **55 passed across 9 files**; build passed |
| Automatic startup | Missing database populated before requests; restart preserves data; concurrent starts seed once; production never bootstraps |
| Fresh local clone | Dependencies installed from local caches; `start.ps1` started both servers with **no `.env` and no setup/seed command**; **49 page/API reads populated**; temporary checkout removed |
| Canonical financial figures | All **125 rupee values unchanged**; auto-start plan principal/cost, NBFC baseline and week-6 **6.25%** independently checked |
| Execution evidence / audit verifier | Regenerated [`evidence/`](evidence/); **VALID, 73 entries**, zero broken links |

The page/read contract is maintained in [`scripts/kosh_data_coverage.py`](../../scripts/kosh_data_coverage.py). The full local inventory is `private_notes/DATA_COVERAGE.md` (all yes). Logs remain under `private_notes/logs/data_*` and are excluded from Git. Source/commit-message hygiene and private-file checks are clean. PowerShell/shell launchers and Compose configuration passed syntax checks; a Docker runtime was unavailable for a container execution check. Media delivery status remains separate in the submission checklist.

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
.\.venv\Scripts\pytest.exe -q --tb=line -p no:warnings --basetemp private_notes/data_pytest_final (Get-ChildItem tests\test_kosh_*.py)
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
| `tests/test_kosh_auto_bootstrap.py` | `test_empty_start_signin_all_pages_and_restart_preserves_data`<br>`test_production_never_bootstraps_even_when_explicitly_enabled`<br>`test_development_defaults_need_no_dotenv`<br>`test_two_empty_database_starts_only_seed_once` | Missing/empty SQLite startup, complete business reads, restart preservation, serialized creation, defaults without configuration and unconditional production exclusion. |
| `tests/test_kosh_data_coverage.py` | `test_every_business_page_is_populated_without_changed_cash` | All page reads, complete records, modules on, pending/executed/blocked intents, statutory interest, quote comparisons, four chat answers, ten tenders and identical financial results. |

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
