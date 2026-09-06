"""
Unit and invariant tests for the Verification & Human Review Workflow.
Verifies state transitions, human authority over AI, manual settlement binding,
and audit trail integrity.
"""

from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import ReviewRecord
from app.services.investigation_models import (
    InvestigationClassification,
    InvestigationResult,
    RecommendedAction,
)
from app.services.reconciliation import (
    MatchedBy,
    ReasonCode,
    ReconciliationItem,
    ReconStatus,
)
from app.services.review_models import (
    FinalResolutionStatus,
    ReviewDecision,
    ReviewStatus,
)
from app.services.review_service import ReviewService, ReviewWorkflowError


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def create_sample_item() -> ReconciliationItem:
    return ReconciliationItem(
        transaction_id="TXN_REV_001",
        settlement_id=None,
        status=ReconStatus.AMBIGUOUS,
        reason_code=ReasonCode.MULTIPLE_CANDIDATES,
        matched_by=MatchedBy.NONE,
        payment_amount=Decimal("5000.00"),
        candidate_settlement_ids=["SET_A", "SET_B"],
    )


def test_create_and_assign_review(memory_db):
    item = create_sample_item()
    review = ReviewService.create_review(item, session=memory_db)

    assert review.case_id == "TXN_REV_001"
    assert review.review_status == ReviewStatus.PENDING
    assert review.reviewer_id is None

    # Assign reviewer
    ReviewService.assign_reviewer(review, reviewer_id="analyst_alice", session=memory_db)
    assert review.reviewer_id == "analyst_alice"
    assert review.review_status == ReviewStatus.IN_REVIEW

    # Check persistence
    db_rec = memory_db.query(ReviewRecord).filter_by(case_id="TXN_REV_001").first()
    assert db_rec is not None
    assert db_rec.reviewer_id == "analyst_alice"
    assert db_rec.review_status == "IN_REVIEW"


def test_human_rejection_overrides_ai_recommendation(memory_db):
    """
    CRITICAL INVARIANT:
    AI recommends APPROVE_MATCH, but human reviewer rejects the match.
    Final resolution must strictly follow the human verdict.
    """
    item = create_sample_item()
    ai_verdict = InvestigationResult(
        case_id="TXN_REV_001",
        classification=InvestigationClassification.LIKELY_MATCH,
        summary="AI suggests candidate SET_A is likely correct.",
        observed_facts=["Candidate score is high"],
        inferences=["Timing matches batch SLA"],
        uncertainties=[],
        recommended_action=RecommendedAction.APPROVE_MATCH,
        needs_human_review=True,
        investigator_model="gemini-2.5-flash",
    )

    review = ReviewService.create_review(item, ai_verdict=ai_verdict, session=memory_db)
    assert review.ai_recommended_action == RecommendedAction.APPROVE_MATCH

    # Human decides to REJECT_MATCH
    resolved_review = ReviewService.apply_decision(
        review=review,
        decision=ReviewDecision.REJECT_MATCH,
        reviewer_id="analyst_bob",
        notes="Evidence is contradictory; duplicate authorization code found.",
        session=memory_db,
    )

    assert resolved_review.review_status == ReviewStatus.RESOLVED
    assert resolved_review.decision == ReviewDecision.REJECT_MATCH
    assert resolved_review.final_resolution is not None
    assert resolved_review.final_resolution.resolution_status == FinalResolutionStatus.MATCH_REJECTED

    # Lineage preserved
    assert resolved_review.final_resolution.original_reconciliation_status == ReconStatus.AMBIGUOUS
    assert resolved_review.final_resolution.ai_recommended_action == RecommendedAction.APPROVE_MATCH
    assert resolved_review.final_resolution.human_decision == ReviewDecision.REJECT_MATCH


def test_manual_settlement_selection(memory_db):
    item = create_sample_item()
    review = ReviewService.create_review(item, session=memory_db)

    # Missing selected_settlement_id must raise an error
    with pytest.raises(ReviewWorkflowError, match="requires a valid selected_settlement_id"):
        ReviewService.apply_decision(
            review=review,
            decision=ReviewDecision.SELECT_SETTLEMENT,
            reviewer_id="analyst_alice",
            selected_settlement_id=None,
        )

    # Valid manual settlement selection
    resolved = ReviewService.apply_decision(
        review=review,
        decision=ReviewDecision.SELECT_SETTLEMENT,
        reviewer_id="analyst_alice",
        selected_settlement_id="SET_B",
        notes="Confirmed bank reference with acquiring bank ops.",
        session=memory_db,
    )

    assert resolved.review_status == ReviewStatus.RESOLVED
    assert resolved.final_resolution.resolution_status == FinalResolutionStatus.MANUALLY_MATCHED
    assert resolved.final_resolution.selected_settlement_id == "SET_B"

    # Verify DB persistence
    db_rec = memory_db.query(ReviewRecord).filter_by(case_id="TXN_REV_001").first()
    assert db_rec.final_resolution_status == "MANUALLY_MATCHED"
    assert db_rec.selected_settlement_id == "SET_B"


def test_resolved_case_cannot_be_re_modified():
    item = create_sample_item()
    review = ReviewService.create_review(item)
    ReviewService.apply_decision(
        review=review,
        decision=ReviewDecision.APPROVE_MATCH,
        reviewer_id="analyst_alice",
    )

    assert review.review_status == ReviewStatus.RESOLVED

    # Cannot apply decision again
    with pytest.raises(ReviewWorkflowError, match="already been resolved"):
        ReviewService.apply_decision(
            review=review,
            decision=ReviewDecision.REJECT_MATCH,
            reviewer_id="analyst_charlie",
        )

    # Cannot re-assign
    with pytest.raises(ReviewWorkflowError, match="Cannot assign reviewer"):
        ReviewService.assign_reviewer(review, "analyst_charlie")


def test_escalation_workflow(memory_db):
    item = create_sample_item()
    review = ReviewService.create_review(item, session=memory_db)

    ReviewService.apply_decision(
        review=review,
        decision=ReviewDecision.ESCALATE,
        reviewer_id="analyst_alice",
        notes="High-value dispute; escalates to Tier-2 Finance Lead.",
        session=memory_db,
    )

    assert review.review_status == ReviewStatus.ESCALATED
    assert review.final_resolution.resolution_status == FinalResolutionStatus.ESCALATED


def test_build_review_queue():
    item_matched = ReconciliationItem(
        transaction_id="TXN_OK",
        settlement_id="SET_OK",
        status=ReconStatus.MATCHED,
        reason_code=ReasonCode.EXACT_MATCH,
        matched_by=MatchedBy.EXACT_TRANSACTION_ID,
    )
    item_ambiguous = create_sample_item()
    item_mismatch = ReconciliationItem(
        transaction_id="TXN_FEE",
        settlement_id="SET_FEE",
        status=ReconStatus.AMOUNT_MISMATCH,
        reason_code=ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE,
        matched_by=MatchedBy.EXACT_TRANSACTION_ID,
    )

    queue = ReviewService.build_queue([item_matched, item_ambiguous, item_mismatch])

    # Exactly 2 items enqueued (MATCHED excluded)
    assert len(queue) == 2
    # Priority ordering check: AMBIGUOUS (HIGH) comes before AMOUNT_MISMATCH (MEDIUM)
    assert queue[0].case_id == "TXN_REV_001"
    assert queue[0].priority == "HIGH"
    assert queue[1].case_id == "TXN_FEE"
    assert queue[1].priority == "MEDIUM"