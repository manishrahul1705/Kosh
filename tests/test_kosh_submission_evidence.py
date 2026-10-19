"""Submission artifacts must be present and contain no delivery credentials."""
import importlib.util
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("submission_export", ROOT / "scripts/kosh_export_evidence.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def test_committed_evidence_is_complete_and_has_no_secrets():
    folder = ROOT / "docs/kosh/evidence"
    required = {"sandbox_outbox.jsonl", "sandbox_ledger.jsonl", "action_intents.jsonl",
                "audit_chain.jsonl", "audit_verify.txt", "forecast_before_after.json", "README.md"}
    assert required <= {path.name for path in folder.iterdir()}, "Generate and commit the execution evidence"
    for path in folder.iterdir():
        if path.is_file():
            exporter.assert_safe(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("payload", [
    '{"code":"123456"}', '{"token":"abc"}', '{"code_hash":"abc"}',
    '{"encrypted_payload":"abc"}', 'OTP code: 123456', 'Bearer abc',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature',
    '{"otp":"123456"}', '{"approval_token":"abc"}',
    'eyJhcHByb3Zlcl9pZCI6MX0.' + 'a' * 64,
])
def test_evidence_scanner_rejects_credentials(payload):
    with pytest.raises(ValueError):
        exporter.assert_safe(payload)


def test_committed_audit_chain_and_walkthrough_results():
    from app.audit.ledger import canonical_json, event_hash, GENESIS_HASH

    folder = ROOT / "docs/kosh/evidence"
    def records(name):
        return [json.loads(line) for line in (folder / name).read_text(encoding="utf-8").splitlines()]

    audit = records("audit_chain.jsonl")
    assert audit, "An empty audit chain is not execution evidence"
    previous = GENESIS_HASH
    for sequence, row in enumerate(audit, 1):
        assert row["sequence"] == sequence and row["prev_hash"] == previous
        assert row["params_hash"] == hashlib.sha256(canonical_json(row["payload"]).encode()).hexdigest()
        entry = SimpleNamespace(**{**row, "recorded_at": datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))})
        assert row["entry_hash"] == event_hash(entry)
        previous = row["entry_hash"]
    assert (folder / "audit_verify.txt").read_text().strip() == f"VALID, {len(audit)} entries"

    events = records("action_intents.jsonl")
    assert {"PROPOSED", "APPROVED", "SUCCEEDED"} <= {row.get("state") for row in events}
    rules = set()
    for row in events:
        if row.get("status_code") == 403:
            rules.update(row.get("payload", {}).get("rule_ids", []))
            rules.update(row.get("detail", {}).get("rule_ids", []))
    assert {"OTP_REQUIRED", "TOKEN_REPLAY", "PARAMS_TAMPERED", "DOCUMENT_PARAMETERS", "KILL_SWITCH"} <= rules
    assert any(row.get("attempt") == "approved reminder under kill switch" and
               row.get("status_code") == 403 for row in events)
    forecast = json.loads((folder / "forecast_before_after.json").read_text())
    assert len(forecast["before"]) == len(forecast["after"]) == 13
    assert all(week["prob_below_buffer"] <= .20 for week in forecast["after"])
    ledger = records("sandbox_ledger.jsonl")
    assert len(ledger) == 1 and ledger[0]["kind"] == "TREDS_SETTLEMENT"
    assert ledger[0]["amount_paise"] > 0 and ledger[0]["receivable_reduction_paise"] > 0
    assert any(row.get("message") == "OTP delivery [MASKED]" for row in records("sandbox_outbox.jsonl"))
    assert any(row.get("body") and row.get("status") == "SUBMITTED"
               for row in records("sandbox_outbox.jsonl"))
