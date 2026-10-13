"""Audit export integrity, tenant privacy and security counter contracts."""
import json
from sqlalchemy import select
from app.audit.ledger import append_event
from app.audit.export import export_jsonl,verify_jsonl,security_counts
from tests.matching_factories import make_seller
from tests.conftest import sign_in

SUBJECT="eeeeeeee-0000-0000-0000-000000000051"


def test_export_preserves_chain_links_without_foreign_payloads(db):
    owner=make_seller(db,name="Audit export owner",owner_subject=SUBJECT)
    other=make_seller(db,name="Audit export other",owner_subject="eeeeeeee-0000-0000-0000-000000000052")
    append_event(db,seller_id=owner.id,actor_type="HUMAN",actor_id="1",action="own",tier="T0",payload={"number":123},policy_decision="ALLOW")
    append_event(db,seller_id=other.id,actor_type="HUMAN",actor_id="2",action="foreign",tier="T0",payload={"private":"foreign confidential payload"},policy_decision="ALLOW");db.commit()
    exported=export_jsonl(db,owner.id)
    assert "foreign confidential payload" not in exported and '"action":"foreign"' not in exported
    records=[json.loads(line) for line in exported.splitlines()]
    assert records[-1]["type"]=="ANCHOR" and set(records[-1])=={"type","sequence","prev_hash","entry_hash"}
    assert verify_jsonl(db,owner.id,exported)["valid"]
    assert not verify_jsonl(db,other.id,exported)["valid"]
    assert not verify_jsonl(db,owner.id,exported.replace('"number":123','"number":124'))["valid"]
    assert not verify_jsonl(db,owner.id,"not json")["valid"]


def test_security_counts_come_from_audit_records(db):
    seller=make_seller(db,name="Counters",owner_subject=SUBJECT)
    for action in ("security.intent_blocked","security.otp_failed","security.token_replay","security.injection_detected"):
        append_event(db,seller_id=seller.id,actor_type="SYSTEM",actor_id=None,action=action,tier="T4",payload={},policy_decision="DENY")
    db.commit()
    assert security_counts(db,seller.id)=={"blocked_intents":1,"failed_otps":1,"token_replays":1,"injection_detections":1,"reconciliation_mismatches":0}


def test_export_routes_authorize_and_verify_scoped_snapshot(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    owner=make_seller(db,name="Export route owner",owner_subject=SUBJECT)
    other=make_seller(db,name="Export route other",owner_subject="eeeeeeee-0000-0000-0000-000000000053")
    prefix=f"/api/kosh/sellers/{owner.id}/audit"
    assert client.get(prefix+"/export").status_code==401
    assert client.get(prefix+"/security-events").status_code==401
    assert client.post(prefix+"/verify-export",json={"jsonl":""}).status_code==401
    sign_in(client.app,SUBJECT)
    assert client.get(f"/api/kosh/sellers/{other.id}/audit/export").status_code==403
    assert client.get(f"/api/kosh/sellers/{other.id}/audit/security-events").status_code==403
    assert client.post(f"/api/kosh/sellers/{other.id}/audit/verify-export",json={"jsonl":""}).status_code==403
    exported=client.get(prefix+"/export");assert exported.status_code==200
    verified=client.post(prefix+"/verify-export",json={"jsonl":exported.text})
    assert verified.status_code==200 and verified.json()["valid"]
    assert client.get(prefix+"/security-events").status_code==200


def test_cli_verifies_scoped_export_against_same_database(db,settings,tmp_path):
    import os,sys,subprocess
    seller=make_seller(db,name="CLI audit owner",owner_subject=SUBJECT)
    append_event(db,seller_id=seller.id,actor_type="HUMAN",actor_id="1",action="cli.fixture",tier="T0",payload={},policy_decision="ALLOW");db.commit()
    path=tmp_path/"export.jsonl";path.write_text(export_jsonl(db,seller.id),encoding="utf-8")
    env=dict(os.environ,DATABASE_URL=settings.resolved_database_url,SCHEDULER_ENABLED="false",AUTO_MIGRATE="false",COLLECT_ON_STARTUP="false",STARTUP_RECOVERY_ENABLED="false",APP_ENV="development",KOSH_AS_OF_DATE="2026-10-13")
    result=subprocess.run([sys.executable,"scripts/verify_audit_chain.py","--verify-jsonl",str(path),"--seller-id",str(seller.id)],env=env,capture_output=True,text=True,check=False)
    assert result.returncode==0 and json.loads(result.stdout)["valid"]
