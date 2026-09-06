"""
ReconAI - Deterministic Reconciliation Engine with Candidate Scoring Integration.

Implements pure, explainable, rule-based reconciliation between payments,
settlements, and refunds. Integrates deterministic candidate scoring for
unlinked and fallback settlement matching.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.db.models import Payment, Refund, Settlement
from app.services.scoring import (
    CandidateScoringConfig,
    CandidateScore,
    ScoringDecision,
    evaluate_candidates,
)

# ---------------------------------------------------------------------------
# Enums and Taxonomy
# ---------------------------------------------------------------------------


class ReconStatus(str, Enum):
    """Normalized reconciliation outcome statuses."""

    MATCHED = "MATCHED"
    MATCHED_WITH_TOLERANCE = "MATCHED_WITH_TOLERANCE"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    ORPHAN_SETTLEMENT = "ORPHAN_SETTLEMENT"
    AMBIGUOUS = "AMBIGUOUS"
    DUPLICATE_SETTLEMENT = "DUPLICATE_SETTLEMENT"
    PARTIAL_SETTLEMENT = "PARTIAL_SETTLEMENT"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    UNRESOLVED = "UNRESOLVED"


class ReasonCode(str, Enum):
    """Machine-readable reason codes explaining why a status was assigned."""

    EXACT_MATCH = "EXACT_MATCH"
    WITHIN_ALLOWED_TOLERANCE = "WITHIN_ALLOWED_TOLERANCE"
    EXACT_ID_AMOUNT_DIFFERENCE = "EXACT_ID_AMOUNT_DIFFERENCE"
    NO_SETTLEMENT_FOUND = "NO_SETTLEMENT_FOUND"
    NO_PAYMENT_FOUND = "NO_PAYMENT_FOUND"
    SCORED_SINGLE_CANDIDATE = "SCORED_SINGLE_CANDIDATE"
    SCORED_DECISIVE_WINNER = "SCORED_DECISIVE_WINNER"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    MULTIPLE_EXACT_ID_SETTLEMENTS = "MULTIPLE_EXACT_ID_SETTLEMENTS"
    PARTIAL_SETTLEMENT_DETECTED = "PARTIAL_SETTLEMENT_DETECTED"
    FULL_REFUND_RECORDED = "FULL_REFUND_RECORDED"
    PARTIAL_REFUND_RECORDED = "PARTIAL_REFUND_RECORDED"
    GATEWAY_STATUS_INCONCLUSIVE = "GATEWAY_STATUS_INCONCLUSIVE"


class MatchedBy(str, Enum):
    """Identifies the rule layer that resolved the link."""

    EXACT_TRANSACTION_ID = "EXACT_TRANSACTION_ID"
    SCORED_CANDIDATE = "SCORED_CANDIDATE"
    FALLBACK_CANDIDATE = "FALLBACK_CANDIDATE"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Configuration and Result Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationConfig:
    """Centralized configuration parameters for deterministic rules."""

    amount_tolerance: Decimal = Decimal("0.01")
    fallback_time_window: timedelta = timedelta(days=3)
    scoring_config: CandidateScoringConfig = field(default_factory=CandidateScoringConfig)


@dataclass
class ReconciliationItem:
    """Detailed reconciliation result for an individual payment or orphan settlement."""

    transaction_id: Optional[str]
    settlement_id: Optional[str]
    status: ReconStatus
    reason_code: ReasonCode
    matched_by: MatchedBy
    payment_amount: Optional[Decimal] = None
    settled_amount: Optional[Decimal] = None
    difference: Optional[Decimal] = None
    candidate_settlement_ids: list[str] = field(default_factory=list)
    refund_ids: list[str] = field(default_factory=list)
    candidate_scores: list[CandidateScore] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class ReconciliationSummary:
    """Aggregated metrics from a reconciliation run."""

    total_payments: int = 0
    total_settlements: int = 0
    total_refunds: int = 0
    matched: int = 0
    matched_with_tolerance: int = 0
    amount_mismatch: int = 0
    missing_settlement: int = 0
    orphan_settlement: int = 0
    ambiguous: int = 0
    duplicate_settlement: int = 0
    partial_settlement: int = 0
    refunded: int = 0
    partially_refunded: int = 0
    unresolved: int = 0
    items: list[ReconciliationItem] = field(default_factory=list)

    def record_item(self, item: ReconciliationItem) -> None:
        self.items.append(item)
        match item.status:
            case ReconStatus.MATCHED:
                self.matched += 1
            case ReconStatus.MATCHED_WITH_TOLERANCE:
                self.matched_with_tolerance += 1
            case ReconStatus.AMOUNT_MISMATCH:
                self.amount_mismatch += 1
            case ReconStatus.MISSING_SETTLEMENT:
                self.missing_settlement += 1
            case ReconStatus.ORPHAN_SETTLEMENT:
                self.orphan_settlement += 1
            case ReconStatus.AMBIGUOUS:
                self.ambiguous += 1
            case ReconStatus.DUPLICATE_SETTLEMENT:
                self.duplicate_settlement += 1
            case ReconStatus.PARTIAL_SETTLEMENT:
                self.partial_settlement += 1
            case ReconStatus.REFUNDED:
                self.refunded += 1
            case ReconStatus.PARTIALLY_REFUNDED:
                self.partially_refunded += 1
            case ReconStatus.UNRESOLVED:
                self.unresolved += 1


# ---------------------------------------------------------------------------
# Pure Reconciliation Algorithm
# ---------------------------------------------------------------------------


def reconcile_records(
    payments: Sequence[Payment],
    settlements: Sequence[Settlement],
    refunds: Sequence[Refund],
    config: Optional[ReconciliationConfig] = None,
) -> ReconciliationSummary:
    """
    Pure deterministic reconciliation algorithm integrating candidate scoring.

    Executes in O(P + S + R) time using in-memory hash indexes.
    """
    cfg = config or ReconciliationConfig()

    sorted_payments = sorted(payments, key=lambda p: p.transaction_id)
    sorted_settlements = sorted(settlements, key=lambda s: s.settlement_id)
    sorted_refunds = sorted(refunds, key=lambda r: r.refund_id)

    summary = ReconciliationSummary(
        total_payments=len(sorted_payments),
        total_settlements=len(sorted_settlements),
        total_refunds=len(sorted_refunds),
    )

    # 1. Build In-Memory Hash Indexes
    settlements_by_tx: dict[str, list[Settlement]] = defaultdict(list)
    unlinked_settlements: dict[tuple[str, str], list[Settlement]] = defaultdict(list)

    for s in sorted_settlements:
        if s.transaction_id:
            settlements_by_tx[s.transaction_id].append(s)
        else:
            unlinked_settlements[(s.merchant_id, s.currency)].append(s)

    refunds_by_tx: dict[str, list[Refund]] = defaultdict(list)
    for r in sorted_refunds:
        refunds_by_tx[r.transaction_id].append(r)

    matched_settlement_ids: set[str] = set()

    # 2. Forward Pass: Reconcile Payments
    for p in sorted_payments:
        # Special Case: Inconclusive gateway status -> UNRESOLVED
        if p.payment_status == "PENDING_GATEWAY_RESPONSE":
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=None,
                    status=ReconStatus.UNRESOLVED,
                    reason_code=ReasonCode.GATEWAY_STATUS_INCONCLUSIVE,
                    matched_by=MatchedBy.NONE,
                    payment_amount=p.amount,
                    notes="Payment status is pending gateway confirmation.",
                )
            )
            continue

        # Level 1: Exact transaction_id matching
        exact_candidates = settlements_by_tx.get(p.transaction_id, [])

        matched_by = MatchedBy.EXACT_TRANSACTION_ID
        candidates = exact_candidates
        candidate_scores: list[CandidateScore] = []

        # Level 2 & 3: Fallback Candidate Scoring if no exact match
        if not candidates:
            potential = unlinked_settlements.get((p.merchant_id, p.currency), [])
            unclaimed_pool = [
                s
                for s in potential
                if s.settlement_id not in matched_settlement_ids
                and abs(s.settlement_timestamp - p.payment_timestamp) <= cfg.fallback_time_window
            ]

            if unclaimed_pool:
                decision: ScoringDecision = evaluate_candidates(
                    payment=p,
                    candidates=unclaimed_pool,
                    config=cfg.scoring_config,
                )
                candidate_scores = decision.ranked_candidates

                if decision.is_ambiguous:
                    summary.record_item(
                        ReconciliationItem(
                            transaction_id=p.transaction_id,
                            settlement_id=None,
                            status=ReconStatus.AMBIGUOUS,
                            reason_code=ReasonCode.MULTIPLE_CANDIDATES,
                            matched_by=MatchedBy.NONE,
                            payment_amount=p.amount,
                            candidate_settlement_ids=[
                                c.settlement_id for c in decision.ranked_candidates
                            ],
                            candidate_scores=decision.ranked_candidates,
                            notes=f"Candidate scoring evaluated {len(decision.ranked_candidates)} options: {decision.decision_reason}",
                        )
                    )
                    continue

                if decision.is_acceptable and decision.best_candidate:
                    candidates = [decision.best_candidate.settlement]
                    matched_by = MatchedBy.SCORED_CANDIDATE
                else:
                    candidates = []

        # Missing Settlement Check
        if len(candidates) == 0:
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=None,
                    status=ReconStatus.MISSING_SETTLEMENT,
                    reason_code=ReasonCode.NO_SETTLEMENT_FOUND,
                    matched_by=MatchedBy.NONE,
                    payment_amount=p.amount,
                    candidate_scores=candidate_scores,
                    notes="No settlement record found with matching transaction ID or qualifying candidate score.",
                )
            )
            continue

        # Duplicate Settlement Check
        if len(candidates) > 1:
            cand_ids = [s.settlement_id for s in candidates]
            matched_settlement_ids.update(cand_ids)
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=cand_ids[0],
                    status=ReconStatus.DUPLICATE_SETTLEMENT,
                    reason_code=ReasonCode.MULTIPLE_EXACT_ID_SETTLEMENTS,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    candidate_settlement_ids=cand_ids,
                    notes=f"Multiple settlements ({', '.join(cand_ids)}) reference the same payment transaction.",
                )
            )
            continue

        # Exactly 1 candidate found
        settlement = candidates[0]
        matched_settlement_ids.add(settlement.settlement_id)
        diff = p.amount - settlement.settled_amount

        # Check Refund Lifecycle
        related_refunds = refunds_by_tx.get(p.transaction_id, [])
        refund_ids = [r.refund_id for r in related_refunds]
        total_refunded = (
            sum(r.refund_amount for r in related_refunds)
            if related_refunds
            else Decimal("0.00")
        )

        if total_refunded > Decimal("0.00"):
            if total_refunded == p.amount:
                summary.record_item(
                    ReconciliationItem(
                        transaction_id=p.transaction_id,
                        settlement_id=settlement.settlement_id,
                        status=ReconStatus.REFUNDED,
                        reason_code=ReasonCode.FULL_REFUND_RECORDED,
                        matched_by=matched_by,
                        payment_amount=p.amount,
                        settled_amount=settlement.settled_amount,
                        difference=diff,
                        refund_ids=refund_ids,
                        candidate_scores=candidate_scores,
                        notes=f"Full refund of {total_refunded} recorded. Net position zeroed.",
                    )
                )
            else:
                summary.record_item(
                    ReconciliationItem(
                        transaction_id=p.transaction_id,
                        settlement_id=settlement.settlement_id,
                        status=ReconStatus.PARTIALLY_REFUNDED,
                        reason_code=ReasonCode.PARTIAL_REFUND_RECORDED,
                        matched_by=matched_by,
                        payment_amount=p.amount,
                        settled_amount=settlement.settled_amount,
                        difference=diff,
                        refund_ids=refund_ids,
                        candidate_scores=candidate_scores,
                        notes=f"Partial refund of {total_refunded} recorded against payment of {p.amount}.",
                    )
                )
            continue

        # Amount & Tolerance Evaluation
        reason = (
            ReasonCode.SCORED_DECISIVE_WINNER
            if matched_by == MatchedBy.SCORED_CANDIDATE
            else ReasonCode.EXACT_MATCH
        )

        if diff == Decimal("0.00"):
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=settlement.settlement_id,
                    status=ReconStatus.MATCHED,
                    reason_code=reason,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    settled_amount=settlement.settled_amount,
                    difference=diff,
                    candidate_scores=candidate_scores,
                )
            )
        elif abs(diff) <= cfg.amount_tolerance:
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=settlement.settlement_id,
                    status=ReconStatus.MATCHED_WITH_TOLERANCE,
                    reason_code=ReasonCode.WITHIN_ALLOWED_TOLERANCE,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    settled_amount=settlement.settled_amount,
                    difference=diff,
                    candidate_scores=candidate_scores,
                    notes=f"Difference of {diff} is within allowed tolerance of {cfg.amount_tolerance}.",
                )
            )
        elif settlement.settlement_status == "PARTIALLY_SETTLED":
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=settlement.settlement_id,
                    status=ReconStatus.PARTIAL_SETTLEMENT,
                    reason_code=ReasonCode.PARTIAL_SETTLEMENT_DETECTED,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    settled_amount=settlement.settled_amount,
                    difference=diff,
                    candidate_scores=candidate_scores,
                    notes=f"Explicit partial settlement payout: {settlement.settled_amount} of {p.amount}.",
                )
            )
        else:
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=settlement.settlement_id,
                    status=ReconStatus.AMOUNT_MISMATCH,
                    reason_code=ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    settled_amount=settlement.settled_amount,
                    difference=diff,
                    candidate_scores=candidate_scores,
                    notes=f"Amount difference of {diff} detected. Source records lack explicit fee breakdown.",
                )
            )

    # 3. Reverse Pass: Identify Orphan Settlements
    for s in sorted_settlements:
        if s.settlement_id not in matched_settlement_ids:
            summary.record_item(
                ReconciliationItem(
                    transaction_id=s.transaction_id,
                    settlement_id=s.settlement_id,
                    status=ReconStatus.ORPHAN_SETTLEMENT,
                    reason_code=ReasonCode.NO_PAYMENT_FOUND,
                    matched_by=MatchedBy.NONE,
                    settled_amount=s.settled_amount,
                    notes="Settlement record exists in bank feed but no corresponding internal payment could be linked.",
                )
            )

    return summary


# ---------------------------------------------------------------------------
# Database Runner / CLI Helper
# ---------------------------------------------------------------------------


def run_database_reconciliation(
    session: Session, config: Optional[ReconciliationConfig] = None
) -> ReconciliationSummary:
    """Loads all records from database session and runs deterministic reconciliation."""
    payments = session.query(Payment).all()
    settlements = session.query(Settlement).all()
    refunds = session.query(Refund).all()

    return reconcile_records(payments, settlements, refunds, config)


def main() -> None:
    """CLI runner to execute reconciliation against the database."""
    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        summary = run_database_reconciliation(session)

        print("==================================================")
        print("ReconAI - Deterministic Reconciliation Summary")
        print("==================================================")
        print(f"Total Payments Analyzed:      {summary.total_payments:>5}")
        print(f"Total Settlements Analyzed:   {summary.total_settlements:>5}")
        print(f"Total Refunds Analyzed:       {summary.total_refunds:>5}")
        print("--------------------------------------------------")
        print(f"MATCHED:                      {summary.matched:>5}")
        print(f"MATCHED_WITH_TOLERANCE:       {summary.matched_with_tolerance:>5}")
        print(f"AMOUNT_MISMATCH:              {summary.amount_mismatch:>5}")
        print(f"MISSING_SETTLEMENT:           {summary.missing_settlement:>5}")
        print(f"ORPHAN_SETTLEMENT:            {summary.orphan_settlement:>5}")
        print(f"AMBIGUOUS:                    {summary.ambiguous:>5}")
        print(f"DUPLICATE_SETTLEMENT:         {summary.duplicate_settlement:>5}")
        print(f"PARTIAL_SETTLEMENT:           {summary.partial_settlement:>5}")
        print(f"REFUNDED:                     {summary.refunded:>5}")
        print(f"PARTIALLY_REFUNDED:           {summary.partially_refunded:>5}")
        print(f"UNRESOLVED:                   {summary.unresolved:>5}")
        print("==================================================")
    finally:
        session.close()


if __name__ == "__main__":
    main()