"""Submission artifacts must be present and contain no delivery credentials."""
import importlib.util
from pathlib import Path
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
])
def test_evidence_scanner_rejects_credentials(payload):
    with pytest.raises(ValueError):
        exporter.assert_safe(payload)
