# Execution evidence

Run `python scripts/kosh_export_evidence.py` from the repository root after installing the backend requirements. The exporter resets a throwaway database, seeds the fictional business and executes the complete canonical Stage 4 walkthrough. Its temporary database, borrower documents and private inbox are removed afterward.

The following generated artifacts are required before this folder is submission-ready:

| File | Meaning |
|---|---|
| `sandbox_outbox.jsonl` | Collections reminders and masked OTP delivery metadata; no decrypted codes |
| `sandbox_ledger.jsonl` | Simulated TReDS settlement and receivable reduction, in integer paise |
| `action_intents.jsonl` | Proposal, approval, execution and security denials; pure policy checks are explicitly labelled |
| `audit_chain.jsonl` | Original ordered chain rows, including canonical payload digests and parent hashes |
| `audit_verify.txt` | Verification result and actual chain entry count |
| `forecast_before_after.json` | Same-seed 13-week baseline and post-execution probabilities and balances |

Export is currently blocked on missing offline runtime dependencies. No generated execution artifacts are claimed or substituted. `tests/test_kosh_submission_evidence.py` scans every generated file for credential fields, unmasked OTPs and JWTs, and fails if required artifacts are absent.

Amounts and business identities are fictional sandbox fixtures. Approval identifiers and digests are audit references, not executable approval tokens. OTP ciphertext, OTP hashes and private delivery payloads are never exported. Audit verification applies to the original records; payloads must not be edited after export.
