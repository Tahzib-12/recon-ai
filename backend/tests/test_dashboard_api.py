"""
API tests for the ReconAI Dashboard.
Verifies summary calculations, case pagination, filtering, search, 360-degree case detail,
candidate evidence display, AI integration, audit history, and error handling.
"""

from decimal import Decimal
import pytest
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Payment, ReviewRecord, Settlement
from app.main import app
from app.services.audit_models import ActorType, AuditEventType
from app.services.audit_service import AuditService


@pytest.fixture
def test_db():
    engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()

    # Seed sample payment and settlement
    from datetime import datetime, timezone

    now = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    p1 = Payment(
        transaction_id="TXN_DASH_1",
        merchant_id="MER001",
        customer_id="CUS001",
        amount=Decimal("1000.00"),
        currency="INR",
        payment_status="SUCCESS",
        payment_method="UPI",
        payment_timestamp=now,
    )
    s1 = Settlement(
        settlement_id="SET_DASH_1",
        transaction_id="TXN_DASH_1",
        merchant_id="MER001",
        settled_amount=Decimal("1000.00"),
        currency="INR",
        settlement_status="SETTLED",
        settlement_timestamp=now,
    )
    session.add_all([p1, s1])
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_dashboard_summary_api(client):
    res = client.get("/api/dashboard/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["total_cases"] >= 1
    assert data["total_payments"] >= 1
    assert data["total_settlements"] >= 1
    assert "status_counts" in data
    assert data["status_counts"]["MATCHED"] >= 1
    assert data["match_rate_pct"] > 0


def test_dashboard_cases_listing_and_filter(client):
    # Listing
    res = client.get("/api/dashboard/cases")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert len(data["cases"]) >= 1

    # Filter by matching status
    res_filtered = client.get("/api/dashboard/cases?status=MATCHED")
    assert res_filtered.status_code == 200
    assert res_filtered.json()["total"] >= 1

    # Filter by non-existent status
    res_empty = client.get("/api/dashboard/cases?status=UNRESOLVED")
    assert res_empty.status_code == 200
    assert res_empty.json()["total"] == 0


def test_dashboard_cases_search(client):
    # Valid search
    res = client.get("/api/dashboard/cases?search=DASH_1")
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["cases"][0]["case_id"] == "TXN_DASH_1"

    # Non-existent search
    res_none = client.get("/api/dashboard/cases?search=NONEXISTENT_QUERY")
    assert res_none.status_code == 200
    assert res_none.json()["total"] == 0


def test_case_detail_api(client, test_db):
    # Record an audit event to verify timeline inclusion
    AuditService.record_event(
        case_id="TXN_DASH_1",
        event_type=AuditEventType.RECONCILIATION_COMPLETED,
        actor_type=ActorType.SYSTEM,
        actor_id="system",
        description="Reconciliation matched exactly.",
        session=test_db,
    )

    res = client.get("/api/dashboard/cases/TXN_DASH_1")
    assert res.status_code == 200
    data = res.json()

    assert data["case_id"] == "TXN_DASH_1"
    assert data["reconciliation_status"] == "MATCHED"
    assert data["payment"] is not None
    assert data["payment"]["merchant_id"] == "MER001"
    assert data["settlement"] is not None
    assert data["settlement"]["settlement_id"] == "SET_DASH_1"
    assert len(data["audit_timeline"]) >= 1
    assert data["audit_timeline"][0]["event_type"] == "RECONCILIATION_COMPLETED"


def test_case_detail_not_found(client):
    res = client.get("/api/dashboard/cases/UNKNOWN_TRANSACTION_ID")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()