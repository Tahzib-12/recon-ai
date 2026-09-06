"""
ReconAI - Human Verification & Review Service.

Manages case lifecycle transitions, applies human decisions over AI recommendations,
constructs final resolutions, and persists records safely.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import ReviewRecord
from app.services.investigation_models import InvestigationResult
from app.services.reconciliation import ReconciliationItem, ReconStatus
from app.services.review_models import (
    FinalResolution,
    FinalResolutionStatus,
    HumanReview,
    ReviewDecision,
    ReviewQueueItem,
    ReviewStatus,
)


class ReviewWorkflowError(Exception):
    """Base exception for invalid review state transitions or validation errors."""

    pass


class ReviewService:
    """Service handling investigator actions and final case resolutions."""

    @staticmethod
    def create_review(
        item: ReconciliationItem,
        ai_verdict: Optional[InvestigationResult] = None,
        session: Optional[Session] = None,
    ) -> HumanReview:
        """Initialize a new human review task from a reconciliation item and optional AI finding."""
        case_id = item.transaction_id or item.settlement_id
        if not case_id:
            raise ReviewWorkflowError("Cannot create a review for an item without an identifier.")

        now = datetime.now(timezone.utc)
        review = HumanReview(
            case_id=case_id,
            original_reconciliation_status=item.status,
            review_status=ReviewStatus.PENDING,
            created_at=now,
            updated_at=now,
            ai_classification=ai_verdict.classification if ai_verdict else None,
            ai_recommended_action=ai_verdict.recommended_action if ai_verdict else None,
        )

        if session:
            db_record = ReviewRecord(
                case_id=review.case_id,
                original_reconciliation_status=review.original_reconciliation_status.value,
                review_status=review.review_status.value,
                ai_classification=review.ai_classification.value if review.ai_classification else None,
                ai_recommended_action=review.ai_recommended_action.value if review.ai_recommended_action else None,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )
            session.merge(db_record)
            session.commit()

        return review

    @staticmethod
    def assign_reviewer(
        review: HumanReview,
        reviewer_id: str,
        session: Optional[Session] = None,
    ) -> HumanReview:
        """Assign an investigator to the case and transition status to IN_REVIEW."""
        if review.review_status in {ReviewStatus.RESOLVED, ReviewStatus.ESCALATED}:
            raise ReviewWorkflowError(f"Cannot assign reviewer to a case in '{review.review_status.value}' status.")

        if not reviewer_id.strip():
            raise ReviewWorkflowError("Reviewer identity cannot be empty.")

        review.reviewer_id = reviewer_id.strip()
        review.review_status = ReviewStatus.IN_REVIEW
        review.updated_at = datetime.now(timezone.utc)

        if session:
            db_record = session.query(ReviewRecord).filter_by(case_id=review.case_id).first()
            if db_record:
                db_record.reviewer_id = review.reviewer_id
                db_record.review_status = review.review_status.value
                db_record.updated_at = review.updated_at
                session.commit()

        return review

    @staticmethod
    def apply_decision(
        review: HumanReview,
        decision: ReviewDecision,
        reviewer_id: str,
        selected_settlement_id: Optional[str] = None,
        notes: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> HumanReview:
        """
        Record the authoritative human decision, derive the final resolution,
        and close the review lifecycle.
        """
        if review.review_status == ReviewStatus.RESOLVED:
            raise ReviewWorkflowError("Cannot modify a case that has already been resolved.")

        if decision == ReviewDecision.SELECT_SETTLEMENT:
            if not selected_settlement_id or not selected_settlement_id.strip():
                raise ReviewWorkflowError("SELECT_SETTLEMENT decision requires a valid selected_settlement_id.")

        now = datetime.now(timezone.utc)
        review.reviewer_id = reviewer_id.strip()
        review.decision = decision
        review.selected_settlement_id = selected_settlement_id.strip() if selected_settlement_id else None
        review.notes = notes
        review.decided_at = now
        review.updated_at = now

        # Derive final resolution and transition status
        if decision == ReviewDecision.APPROVE_MATCH:
            final_status = FinalResolutionStatus.MATCH_CONFIRMED
            review.review_status = ReviewStatus.RESOLVED
        elif decision == ReviewDecision.REJECT_MATCH:
            final_status = FinalResolutionStatus.MATCH_REJECTED
            review.review_status = ReviewStatus.RESOLVED
        elif decision == ReviewDecision.SELECT_SETTLEMENT:
            final_status = FinalResolutionStatus.MANUALLY_MATCHED
            review.review_status = ReviewStatus.RESOLVED
        elif decision == ReviewDecision.MARK_UNRESOLVED:
            final_status = FinalResolutionStatus.UNRESOLVED
            review.review_status = ReviewStatus.RESOLVED
        elif decision == ReviewDecision.ESCALATE:
            final_status = FinalResolutionStatus.ESCALATED
            review.review_status = ReviewStatus.ESCALATED
        else:
            raise ReviewWorkflowError(f"Unhandled review decision: {decision}")

        review.final_resolution = FinalResolution(
            case_id=review.case_id,
            resolution_status=final_status,
            original_reconciliation_status=review.original_reconciliation_status,
            ai_classification=review.ai_classification,
            ai_recommended_action=review.ai_recommended_action,
            human_decision=decision,
            reviewer_id=review.reviewer_id,
            selected_settlement_id=review.selected_settlement_id,
            notes=review.notes,
            resolved_at=now,
        )

        if session:
            db_record = session.query(ReviewRecord).filter_by(case_id=review.case_id).first()
            if db_record:
                db_record.reviewer_id = review.reviewer_id
                db_record.decision = review.decision.value
                db_record.selected_settlement_id = review.selected_settlement_id
                db_record.review_status = review.review_status.value
                db_record.final_resolution_status = final_status.value
                db_record.notes = review.notes
                db_record.decided_at = review.decided_at
                db_record.updated_at = review.updated_at
                session.commit()

        return review

    @staticmethod
    def get_queue_priority(status: ReconStatus) -> str:
        """Determines operational priority for triage."""
        if status in {ReconStatus.AMBIGUOUS, ReconStatus.DUPLICATE_SETTLEMENT}:
            return "HIGH"
        if status in {ReconStatus.AMOUNT_MISMATCH, ReconStatus.MISSING_SETTLEMENT}:
            return "MEDIUM"
        return "LOW"

    @classmethod
    def build_queue(
        cls,
        items: Sequence[ReconciliationItem],
        ai_verdicts: Optional[dict[str, InvestigationResult]] = None,
    ) -> list[ReviewQueueItem]:
        """Filter reconciliation items that require human review and construct queue items."""
        verdicts = ai_verdicts or {}
        queue: list[ReviewQueueItem] = []

        for item in items:
            case_id = item.transaction_id or item.settlement_id or "UNKNOWN"
            verdict = verdicts.get(case_id)

            # Enqueue if status is an exception or AI flagged it for review
            needs_review = verdict.needs_human_review if verdict else item.status != ReconStatus.MATCHED

            if needs_review:
                queue.append(
                    ReviewQueueItem(
                        case_id=case_id,
                        reconciliation_status=item.status,
                        reason_code=item.reason_code.value,
                        ai_classification=verdict.classification if verdict else None,
                        ai_recommended_action=verdict.recommended_action if verdict else None,
                        review_status=ReviewStatus.PENDING,
                        priority=cls.get_queue_priority(item.status),
                        created_at=datetime.now(timezone.utc),
                    )
                )

        return sorted(queue, key=lambda q: (0 if q.priority == "HIGH" else 1 if q.priority == "MEDIUM" else 2, q.case_id))