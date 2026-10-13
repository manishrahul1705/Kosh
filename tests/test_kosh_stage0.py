"""Additive schema and private endpoint boundaries on disposable databases."""

from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Base, Seller
from app.database.kosh_models import KoshCounterparty, KoshInvoice
from app.policy.tiers import PermissionTier
from tests.conftest import sign_in
from tests.matching_factories import make_seller
from tests.test_stage2b_migration_cli import alembic_cfg

SUBJECT = "eeeeeeee-0000-0000-0000-000000000001"
ENDPOINTS = [
    ("GET", "documents"), ("POST", "documents"),
    ("GET", "ledger"), ("GET", "forecast/latest"),
    ("GET", "alerts"), ("GET", "plan"),
    ("GET", "approvals"), ("GET", "audit"),
]
EXPECTED = {
    "kosh_counterparties": {"name", "kind", "gstin", "is_cpse", "treds_onboarded", "notes"},
    "kosh_invoices": {"counterparty_id", "direction", "invoice_number", "invoice_date", "due_date",
                      "amount_paise", "currency", "status", "paid_date", "paid_amount_paise",
                      "source_document_version_id", "source_location", "extraction_confidence", "content_hash"},
    "kosh_obligations": {"kind", "label", "amount_paise", "recurrence", "next_due_date", "day_of_month", "active"},
    "kosh_consent_artifacts": {"granted_by_user_id", "purpose", "data_types", "data_from", "data_to",
                               "expires_at", "revoked_at", "status"},
    "kosh_audit_entries": {"sequence", "actor_type", "actor_id", "action", "tier", "params_hash", "payload",
                           "policy_decision", "approval_id", "prev_hash", "entry_hash", "recorded_at"},
}
STAGE1_TABLES = {"kosh_private_documents", "kosh_private_document_versions", "kosh_bank_transactions"}


@pytest.fixture(autouse=True)
def configured_auth(monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL", "https://kosh-tests.supabase.co")
    get_token_verifier.cache_clear()
    yield
    get_token_verifier.cache_clear()


@pytest.fixture
def businesses(db):
    owner = make_seller(db, name="Business A", owner_subject=SUBJECT)
    other = make_seller(db, name="Business B", owner_subject="eeeeeeee-0000-0000-0000-000000000002")
    return owner.id, other.id


def test_migration_columns_indexes_and_metadata(session_factory):
    engine = session_factory.kw["bind"]
    schema = inspect(engine)
    assert set(EXPECTED) <= set(schema.get_table_names())
    for table, fields in EXPECTED.items():
        columns = {c["name"]: c for c in schema.get_columns(table)}
        assert set(columns) == fields | {"id", "seller_id", "created_at", "updated_at"}
        assert columns["id"]["primary_key"]
        assert columns["seller_id"]["nullable"] == (table == "kosh_audit_entries")
        assert any(i["column_names"] == ["seller_id"] for i in schema.get_indexes(table))
        assert any(f["referred_table"] == "sellers" for f in schema.get_foreign_keys(table))
    with engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    assert not [d for d in diffs if "kosh_" in str(d)]


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_new_endpoint_requires_token(client, method, path):
    response = client.request(method, f"/api/kosh/sellers/1/{path}")
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_private_endpoint_rejects_other_seller(client, businesses, method, path):
    owner, other = businesses
    sign_in(client.app, SUBJECT)
    assert client.request(method, f"/api/kosh/sellers/{other}/{path}").status_code == 403
    response = client.request(method, f"/api/kosh/sellers/{owner}/{path}")
    assert response.status_code == (422 if method == "POST" else 200)
    if method == "GET":
        if path == "documents":
            assert response.json() == []
        elif path not in {"ledger", "audit"}:
            assert response.json() == {"seller_id": owner, "status": "NOT_IMPLEMENTED", "items": []}


def test_viewer_can_read_but_cannot_upload(client, db):
    seller = make_seller(db, name="Read-only business", owner_subject=SUBJECT, role="VIEWER")
    sign_in(client.app, SUBJECT)
    base = f"/api/kosh/sellers/{seller.id}/documents"
    assert client.get(base).status_code == 200
    assert client.post(base).status_code == 403


def _invoice(seller_id, counterparty_id):
    return KoshInvoice(seller_id=seller_id, counterparty_id=counterparty_id,
                       direction="RECEIVABLE", invoice_number="INV-001",
                       invoice_date=date(2026, 10, 1), due_date=date(2026, 10, 31),
                       amount_paise=12345, status="OPEN")


def test_invoice_duplicate_identity_is_rejected(db):
    seller = Seller(name="Invoice business")
    db.add(seller)
    db.flush()
    party = KoshCounterparty(seller_id=seller.id, name="Customer", kind="CUSTOMER")
    db.add(party)
    db.flush()
    assert party.is_cpse is False and party.treds_onboarded is None
    db.add(_invoice(seller.id, party.id))
    db.commit()
    db.add(_invoice(seller.id, party.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    invoice = db.scalar(select(KoshInvoice))
    assert invoice.amount_paise == 12345 and isinstance(invoice.amount_paise, int)
    assert invoice.currency == "INR"


def test_invoice_cannot_reference_another_sellers_counterparty(db):
    a, b = Seller(name="A"), Seller(name="B")
    db.add_all([a, b])
    db.flush()
    party = KoshCounterparty(seller_id=b.id, name="B Customer", kind="CUSTOMER")
    db.add(party)
    db.flush()
    db.add(_invoice(a.id, party.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_downgrade_drops_only_new_tables(tmp_path):
    cfg = alembic_cfg(tmp_path / "downgrade.db")
    command.upgrade(cfg, "0018_tender_status_and_seller_matching")
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade.db'}")
    before = set(inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert set(inspect(engine).get_table_names()) == before | set(EXPECTED) | STAGE1_TABLES
    command.downgrade(cfg, "0018_tender_status_and_seller_matching")
    assert set(inspect(engine).get_table_names()) == before
    command.upgrade(cfg, "head")
    assert set(EXPECTED) | STAGE1_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_permission_tiers_are_only_declared_values():
    assert [tier.value for tier in PermissionTier] == [
        "T0_READ", "T1_DRAFT", "T2_COMMUNICATE", "T3_MONEY_OR_DATA_SHARE", "T4_FORBIDDEN",
    ]
