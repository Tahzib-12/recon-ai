"""
ReconAI - Human Verification Domain Models.

Defines the state taxonomy, decisions, review entities, and final resolution
structures. Preserves the original automated reconciliation result and the
advisory AI verdict alongside the authoritative human decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.services.investigation_models import InvestigationClassification, RecommendedAction
from app.services.reconciliation import ReconStatus


class ReviewStatus(str, Enum):
    """Lifecycle state of a review task."""

    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ReviewDecision(str, Enum):
    """Action taken by the human reviewer."""

    APPROVE_MATCH = "APPROVE_MATCH"
    REJECT_MATCH = "REJECT_MATCH"
    SELECT_SETTLEMENT = "SELECT_SETTLEMENT"
    MARK_UNRESOLVED = "MARK_UNRESOLVED"
    ESCALATE = "ESCALATE"


class FinalResolutionStatus(str, Enum):
    """The authoritative business outcome of the case."""

    MATCH_CONFIRMED = "MATCH_CONFIRMED"
    MATCH_REJECTED = "MATCH_REJECTED"
    MANUALLY_MATCHED = "MANUALLY_MATCHED"
    UNRESOLVED = "UNRESOLVED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class ReviewQueueItem:
    """Lightweight projection for display in an investigator's review queue."""

    case_id: str
    reconciliation_status: ReconStatus
    reason_code: str
    ai_classification: Optional[InvestigationClassification]
    ai_recommended_action: Optional[RecommendedAction]
    review_status: ReviewStatus
    priority: str  # "HIGH", "MEDIUM", "LOW"
    created_at: datetime


@dataclass(frozen=True)
class FinalResolution:
    """The complete, permanent business resolution of an exception case."""

    case_id: str
    resolution_status: FinalResolutionStatus
    original_reconciliation_status: ReconStatus
    ai_classification: Optional[InvestigationClassification]
    ai_recommended_action: Optional[RecommendedAction]
    human_decision: ReviewDecision
    reviewer_id: str
    selected_settlement_id: Optional[str]
    notes: Optional[str]
    resolved_at: datetime


@dataclass
class HumanReview:
    """Core domain entity tracking the lifecycle and decision on a review case."""

    case_id: str
    original_reconciliation_status: ReconStatus
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewer_id: Optional[str] = None
    decision: Optional[ReviewDecision] = None
    selected_settlement_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: Optional[datetime] = None

    # Advisory AI metadata preserved for lineage
    ai_classification: Optional[InvestigationClassification] = None
    ai_recommended_action: Optional[RecommendedAction] = None

    # Final derived resolution
    final_resolution: Optional[FinalResolution] = None