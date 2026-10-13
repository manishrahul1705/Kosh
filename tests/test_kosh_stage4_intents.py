"""Intent provenance, tenant boundaries and atomic audit contracts."""
import ast
from pathlib import Path
from datetime import date,timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.database.auth_models import AppUser
from app.database.kosh_models import KoshActionIntent,KoshPlan,KoshPlanLine,KoshForecastRun,KoshCounterparty,KoshInvoice
from app.actions.planner import create_from_plan_line
from app.actions.integrity import current_hash
from app.policy.controls import editable_control
from app.utils.dates import utcnow
from tests.matching_factories import make_seller
from tests.conftest import sign_in

SUBJECT="eeeeeeee-0000-0000-0000-000000000043"


def planned_line(db,*,name="Trusted line",subject=SUBJECT,product="COLLECTIONS_PUSH"):
    seller=make_seller(db,name=name,owner_subject=subject)
    user=db.scalar(select(AppUser).where(AppUser.supabase_user_id==subject))
    party=KoshCounterparty(seller_id=seller.id,name="Buyer",kind="CUSTOMER",treds_onboarded=True);db.add(party);db.flush()
    invoice=KoshInvoice(seller_id=seller.id,counterparty_id=party.id,direction="RECEIVABLE",invoice_number=f"INV-{seller.id}",invoice_date=date(2026,10,1),due_date=date(2026,12,2),amount_paise=100_000,status="OPEN",accepted_by_buyer=True);db.add(invoice);db.flush()
    run=KoshForecastRun(seller_id=seller.id,as_of_date=date(2026,10,13),n_paths=10,seed=42,params={},input_fingerprint="a"*64,include_forecast_sales=False,buffer_paise=1,status="SUCCESS",created_by_user_id=user.id);db.add(run);db.flush()
    plan=KoshPlan(seller_id=seller.id,forecast_run_id=run.id,forecast_fingerprint=run.input_fingerprint,method="GREEDY",status="VALID",total_cost_paise=0,baseline_cost_paise=0,before_probabilities=[.8]*13,after_probabilities=[.1]*13,planning_details={"target_probability":".20","alert_threshold":".50","alert_week":6});db.add(plan);db.flush()
    terms={"funding_date":"2026-10-16" if product=="TREDS_INVOICE_DISCOUNTING" else "2026-10-14","repayment_date":"2026-12-02" if product=="TREDS_INVOICE_DISCOUNTING" else None,"days":47 if product=="TREDS_INVOICE_DISCOUNTING" else 0}
    line=KoshPlanLine(plan_id=plan.id,product_id=product,scope_ids=[invoice.id],amount_paise=50_000,arrival_week=1,cost_paise=0,effective_annual_rate="0",required_tier="T3" if product=="TREDS_INVOICE_DISCOUNTING" else "T2",evidence=[terms],status="VALID");db.add(line);db.flush()
    control=editable_control(db,seller.id);control.allowlist=[{"key":f"counterparty:{party.id}","added_at":(utcnow()-timedelta(days=2)).isoformat()+"Z"},{"key":f"recipient:{product}","added_at":(utcnow()-timedelta(days=2)).isoformat()+"Z"}];db.commit()
    return seller,user,invoice,line


def test_only_server_plan_parameters_create_intent_and_repeat_is_idempotent(db):
    seller,user,invoice,line=planned_line(db)
    row=create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id);db.commit()
    assert row.source=="PLANNER" and row.status=="PROPOSED"
    assert row.params["amount_paise"]==line.amount_paise and row.params["invoice_id"]==invoice.id
    assert row.params_hash==current_hash(row)
    same=create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id)
    assert same.id==row.id
    assert db.scalar(select(func.count()).select_from(KoshActionIntent))==1
    with pytest.raises(ValueError,match="UNREGISTERED_SOURCE"):create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id,source="DOCUMENT")


def test_invalid_proof_and_stale_plan_rejected(db):
    seller,user,invoice,line=planned_line(db)
    plan=db.get(KoshPlan,line.plan_id)
    plan.after_probabilities=[.8]*13;db.flush()
    with pytest.raises(ValueError,match="PLAN_PROOF_INVALID"):create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id)
    plan.after_probabilities=[.1]*13;plan.forecast_fingerprint="b"*64;db.flush()
    with pytest.raises(ValueError,match="STALE_PLAN"):create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id)


def test_intent_routes_reject_free_parameters_and_cross_tenant(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,invoice,line=planned_line(db)
    other,other_user,other_invoice,other_line=planned_line(db,name="Other line",subject="eeeeeeee-0000-0000-0000-000000000044")
    prefix=f"/api/kosh/sellers/{seller.id}/actions/intents"
    assert client.post(prefix,json={"plan_line_id":line.id}).status_code==401
    assert client.get(prefix).status_code==401
    assert client.get(prefix+"/unknown").status_code==401
    sign_in(client.app,SUBJECT)
    assert client.post(f"/api/kosh/sellers/{other.id}/actions/intents",json={"plan_line_id":other_line.id}).status_code==403
    assert client.get(f"/api/kosh/sellers/{other.id}/actions/intents").status_code==403
    assert client.get(f"/api/kosh/sellers/{other.id}/actions/intents/unknown").status_code==403
    assert client.post(prefix,json={"plan_line_id":other_line.id}).status_code==404
    blocked=client.post(prefix,json={"action_type":"PAYMENT","amount_paise":48_000_000,"payee":"XXXX"})
    assert blocked.status_code==403 and blocked.json()["detail"]["tier"]=="T4"
    assert db.scalar(select(func.count()).select_from(KoshActionIntent))==0
    allowed=client.post(prefix,json={"plan_line_id":line.id})
    assert "ALLOWLIST" in blocked.json()["detail"]["rule_ids"]
    assert allowed.status_code==200 and allowed.json()["params_hash"]
    assert client.get(prefix+"/"+allowed.json()["id"]).status_code==200
    from app.database.auth_models import SellerMembership
    db.rollback();db.expire_all()
    membership=db.scalar(select(SellerMembership).where(SellerMembership.user_id==user.id,SellerMembership.seller_id==seller.id))
    membership.role="VIEWER";db.commit()
    assert client.post(prefix,json={"plan_line_id":line.id}).status_code==403


def test_audit_failure_rolls_back_intent_instead_of_leaving_unaudited_state(client,db,monkeypatch):
    seller,user,invoice,line=planned_line(db)
    sign_in(client.app,SUBJECT)
    def fail(*args,**kwargs):raise RuntimeError("audit unavailable")
    monkeypatch.setattr("app.actions.planner.append_event",fail)
    with pytest.raises(RuntimeError,match="audit unavailable"):client.post(f"/api/kosh/sellers/{seller.id}/actions/intents",json={"plan_line_id":line.id})
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(KoshActionIntent))==0


def test_document_and_chat_import_graph_cannot_reach_intent_factory():
    root=Path(__file__).resolve().parents[1]
    seeds=["app.finance.intake.service","app.finance.intake.invoice_pdf","app.api.business_documents"]
    seeds += [".".join(path.relative_to(root).with_suffix("").parts) for path in (root/"app").rglob("*chat*.py")]
    visited=set()
    def walk(module):
        if module in visited:return
        visited.add(module)
        assert module!="app.actions.planner"
        path=root.joinpath(*module.split(".")).with_suffix(".py")
        if not path.exists():path=root.joinpath(*module.split("."),"__init__.py")
        if not path.exists():return
        tree=ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app."):walk(alias.name)
            elif isinstance(node,ast.ImportFrom) and node.module and node.module.startswith("app."):
                walk(node.module)
                for alias in node.names:walk(node.module+"."+alias.name)
            elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name):assert node.func.id!="create_from_plan_line"
    for seed in seeds:walk(seed)
    assert "app.finance.intake.service" in visited
