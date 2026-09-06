"""
Unit and invariant tests for the Reconciliation Audit Logging System.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AuditEventRecord
from app.services.audit_models import ActorType, AuditEvent, AuditEventType
from app.services.audit_service import AuditService
from app.services.fake_investigator import FakeAIInvestigator
from app.services.investigation_models import (
    InvestigationClassification,
    InvestigationResult,
    RecommendedAction,
)
from app.services.investigation_orchestrator import investigate_exceptions
from app.services.reconciliation import (
    MatchedBy,
    ReasonCode,
    ReconciliationItem,
    ReconciliationSummary,
    ReconStatus,
)
from app.services.review_models import ReviewDecision
from app.services.review_service import ReviewService


@pytest.fixture
def audit_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_record_and_retrieve_audit_event(audit_db):
    event = AuditService.record_event(
        case_id="TXN_AUDIT_1",
        event_type=AuditEventType.RECONCILIATION_COMPLETED,
        actor_type=ActorType.SYSTEM,
        actor_id="reconciliation_engine",
        description="Reconciliation marked as AMOUNT_MISMATCH.",
        previous_state=None,
        new_state="AMOUNT_MISMATCH",
        metadata={"amount_diff": "29.00", "currency": "INR"},
        session=audit_db,
    )

    assert event.case_id == "TXN_AUDIT_1"
    assert event.event_type == AuditEventType.RECONCILIATION_COMPLETED

    history = AuditService.get_case_history("TXN_AUDIT_1", session=audit_db)
    assert len(history) == 1
    assert history[0].description == "Reconciliation marked as AMOUNT_MISMATCH."
    assert history[0].metadata.get("amount_diff") == "29.00"


def test_append_only_chronological_ordering(audit_db):
    # Record sequence of events
    AuditService.record_event(
        case_id="TXN_CHRONO",
        event_type=AuditEventType.RECONCILIATION_COMPLETED,
        actor_type=ActorType.SYSTEM,
        actor_id="system",
        description="Step 1: Discovered discrepancy",
        session=audit_db,
    )
    AuditService.record_event(
        case_id="TXN_CHRONO",
        event_type=AuditEventType.INVESTIGATION_COMPLETED,
        actor_type=ActorType.AI,
        actor_id="gemini",
        description="Step 2: AI suggested fee deduction",
        session=audit_db,
    )
    AuditService.record_event(
        case_id="TXN_CHRONO",
        event_type=AuditEventType.REVIEW_APPROVED,
        actor_type=ActorType.HUMAN,
        actor_id="analyst_alice",
        description="Step 3: Human confirmed fee",
        session=audit_db,
    )

    history = AuditService.get_case_history("TXN_CHRONO", session=audit_db)
    assert len(history) == 3
    assert history[0].event_type == AuditEventType.RECONCILIATION_COMPLETED
    assert history[1].event_type == AuditEventType.INVESTIGATION_COMPLETED
    assert history[2].event_type == AuditEventType.REVIEW_APPROVED


def test_human_override_lineage_preserved(audit_db):
    """
    CRITICAL INVARIANT:
    AI recommends APPROVE_MATCH, Human executes REJECT_MATCH.
    Both audit events must be retained in case history.
    """
    case_id = "TXN_OVERRIDE"

    # 1. AI Investigation event
    AuditService.record_event(
        case_id=case_id,
        event_type=AuditEventType.INVESTIGATION_COMPLETED,
        actor_type=ActorType.AI,
        actor_id="gemini-2.5-flash",
        description="AI recommended APPROVE_MATCH.",
        metadata={"recommended_action": "APPROVE_MATCH"},
        session=audit_db,
    )

    # 2. Human Reviewer rejects match
    AuditService.record_event(
        case_id=case_id,
        event_type=AuditEventType.REVIEW_REJECTED,
        actor_type=ActorType.HUMAN,
        actor_id="analyst_bob",
        description="Human rejected AI suggestion; terminal ID mismatch.",
        metadata={"decision": "REJECT_MATCH"},
        session=audit_db,
    )

    history = AuditService.get_case_history(case_id, session=audit_db)
    assert len(history) == 2
    assert history[0].actor_type == ActorType.AI
    assert history[0].metadata.get("recommended_action") == "APPROVE_MATCH"

    assert history[1].actor_type == ActorType.HUMAN
    assert history[1].metadata.get("decision") == "REJECT_MATCH"


def test_metadata_credential_redaction(audit_db):
    event = AuditService.record_event(
        case_id="TXN_SECURE",
        event_type=AuditEventType.INVESTIGATION_STARTED,
        actor_type=ActorType.SYSTEM,
        actor_id="system",
        description="Test security redaction",
        metadata={
            "safe_key": "safe_value",
            "api_key": "SUPER_SECRET_KEY",
            "GEMINI_API_KEY": "GEMINI_SECRET",
        },
        session=audit_db,
    )

    assert event.metadata["safe_key"] == "safe_value"
    assert event.metadata["api_key"] == "[REDACTED]"
    assert event.metadata["GEMINI_API_KEY"] == "[REDACTED]"

    history = AuditService.get_case_history("TXN_SECURE", session=audit_db)
    assert history[0].metadata["api_key"] == "[REDACTED]"


def test_end_to_end_investigation_and_review_audit_integration(audit_db):
    # Set up exception reconciliation item
    item = ReconciliationItem(
        transaction_id="TXN_E2E",
        settlement_id="SET_E2E",
        status=ReconStatus.AMOUNT_MISMATCH,
        reason_code=ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE,
        matched_by=MatchedBy.EXACT_TRANSACTION_ID,
        payment_amount=Decimal("1000.00"),
        settled_amount=Decimal("971.00"),
        difference=Decimal("29.00"),
    )
    summary = ReconciliationSummary()
    summary.record_item(item)

    # 1. Trigger AI investigation with session -> creates INVESTIGATION_STARTED and COMPLETED
    investigator = FakeAIInvestigator()
    verdicts = investigate_exceptions(summary, [], [], [], investigator, session=audit_db)
    assert len(verdicts) == 1

    # 2. Trigger Human Review workflow -> creates REVIEW_CREATED, REVIEW_ASSIGNED, SETTLEMENT_SELECTED
    review = ReviewService.create_review(item, ai_verdict=verdicts[0], session=audit_db)
    ReviewService.assign_reviewer(review, "analyst_alice", session=audit_db)
    ReviewService.apply_decision(
        review=review,
        decision=ReviewDecision.SELECT_SETTLEMENT,
        reviewer_id="analyst_alice",
        selected_settlement_id="SET_E2E",
        notes="Validated processor fee.",
        session=audit_db,
    )

    # 3. Verify complete audit trail
    history = AuditService.get_case_history("TXN_E2E", session=audit_db)
    event_types = [h.event_type for h in history]

    assert event_types == [
        AuditEventType.INVESTIGATION_STARTED,
        AuditEventType.INVESTIGATION_COMPLETED,
        AuditEventType.REVIEW_CREATED,
        AuditEventType.REVIEW_ASSIGNED,
        AuditEventType.SETTLEMENT_SELECTED,
    ]
    assert history[1].actor_type == ActorType.AI
    assert history[4].actor_type == ActorType.HUMAN