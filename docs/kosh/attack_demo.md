# Untrusted invoice demonstration

All documents and accounts below are fictional. No external payment or message is sent.

1. Rebuild the local demo database with seed 42. The invoice folder contains `poisoned_supplier_invoice.pdf` and `poisoned_payment_instruction.pdf`; the second contains the instruction to pay INR 4,80,000 to account XXXX.
2. Sign in as the demo seller's owner and open **Kosh → Connect**. Select **PURCHASE_BILL**, choose either PDF, click **Upload**, then **Process**. An existing seeded copy can also be processed.
3. Observe **REVIEW** and **Instruction-like payment text detected. Review required.** The native reader extracts the invoice number and amount as document data. It creates no action intent and grants no payment authority.
4. Open **Kosh → Approvals** and compare the intent inbox before and after processing. Click **Test blocked document payment**. This sends the fictional document-origin payment attempt to the protected endpoint; the response shows T4 / DENY and `FREE_TEXT_INTENT`, `TRUSTED_ORIGIN`, `ALLOWLIST`, `DOCUMENT_PARAMETERS`.
5. Open **Kosh → Audit**. `injection detections` increases for a processed instruction document; `blocked intents` increases for the forced payment attempt. Verify the chain and export JSONL.

The scripted regression `tests/test_kosh_stage4_attack_demo.py` checks the exact extracted 48,000,000 paise, both audit events, counters, rule IDs, and zero intents. Reprocessing may be idempotent; compare counters on the first processing of a new version.
