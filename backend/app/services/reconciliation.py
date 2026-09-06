"""
ReconAI - Deterministic Reconciliation Engine.

Implements pure, explainable, rule-based reconciliation between payments,
settlements, and refunds without using AI or external services.
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
    FALLBACK_SINGLE_CANDIDATE = "FALLBACK_SINGLE_CANDIDATE"
    MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
    MULTIPLE_EXACT_ID_SETTLEMENTS = "MULTIPLE_EXACT_ID_SETTLEMENTS"
    PARTIAL_SETTLEMENT_DETECTED = "PARTIAL_SETTLEMENT_DETECTED"
    FULL_REFUND_RECORDED = "FULL_REFUND_RECORDED"
    PARTIAL_REFUND_RECORDED = "PARTIAL_REFUND_RECORDED"
    GATEWAY_STATUS_INCONCLUSIVE = "GATEWAY_STATUS_INCONCLUSIVE"


class MatchedBy(str, Enum):
    """Identifies the heuristic or rule layer that resolved the link."""

    EXACT_TRANSACTION_ID = "EXACT_TRANSACTION_ID"
    FALLBACK_CANDIDATE = "FALLBACK_CANDIDATE"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Configuration and Result Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationConfig:
    """Centralized configuration parameters for deterministic rules."""

    amount_tolerance: Decimal = Decimal("0.01")  # Maximum allowed penny/paisa rounding diff
    fallback_time_window: timedelta = timedelta(days=2)  # Window for unlinked candidate search
    fallback_amount_tolerance: Decimal = Decimal("0.00")  # Strict amount match for candidate search


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
    Pure deterministic reconciliation algorithm.

    Executes in O(P + S + R) time using in-memory hash indexes.
    Does not read from or write to the database.
    """
    cfg = config or ReconciliationConfig()
    summary = ReconciliationSummary(
        total_payments=len(payments),
        total_settlements=len(settlements),
        total_refunds=len(refunds),
    )

    # 1. Build In-Memory Hash Indexes
    # Fast lookup for exact matches
    settlements_by_tx: dict[str, list[Settlement]] = defaultdict(list)
    # Group unlinked settlements (where transaction_id is None or empty)
    unlinked_settlements: dict[tuple[str, str], list[Settlement]] = defaultdict(list)

    for s in settlements:
        if s.transaction_id:
            settlements_by_tx[s.transaction_id].append(s)
        else:
            unlinked_settlements[(s.merchant_id, s.currency)].append(s)

    # Index refunds by transaction_id
    refunds_by_tx: dict[str, list[Refund]] = defaultdict(list)
    for r in refunds:
        refunds_by_tx[r.transaction_id].append(r)

    # Track settlements that have been associated with a payment
    matched_settlement_ids: set[str] = set()

    # 2. Forward Pass: Reconcile Payments
    for p in payments:
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

        # Stage 1: Exact transaction_id matching
        exact_candidates = settlements_by_tx.get(p.transaction_id, [])

        # Stage 2: Fallback Candidate Discovery if no exact match
        matched_by = MatchedBy.EXACT_TRANSACTION_ID
        candidates = exact_candidates

        if not candidates:
            # Look in unlinked pool for matching merchant, currency, amount within time window
            potential = unlinked_settlements.get((p.merchant_id, p.currency), [])
            matching_unlinked = [
                s
                for s in potential
                if abs(s.settled_amount - p.amount) <= cfg.fallback_amount_tolerance
                and abs(s.settlement_timestamp - p.payment_timestamp) <= cfg.fallback_time_window
                and s.settlement_id not in matched_settlement_ids
            ]

            if len(matching_unlinked) == 1:
                candidates = matching_unlinked
                matched_by = MatchedBy.FALLBACK_CANDIDATE
            elif len(matching_unlinked) > 1:
                summary.record_item(
                    ReconciliationItem(
                        transaction_id=p.transaction_id,
                        settlement_id=None,
                        status=ReconStatus.AMBIGUOUS,
                        reason_code=ReasonCode.MULTIPLE_CANDIDATES,
                        matched_by=MatchedBy.NONE,
                        payment_amount=p.amount,
                        candidate_settlement_ids=[s.settlement_id for s in matching_unlinked],
                        notes=f"Found {len(matching_unlinked)} equally plausible unlinked settlement candidates.",
                    )
                )
                continue

        # Stage 3: Candidate Count Evaluation
        if len(candidates) == 0:
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=None,
                    status=ReconStatus.MISSING_SETTLEMENT,
                    reason_code=ReasonCode.NO_SETTLEMENT_FOUND,
                    matched_by=MatchedBy.NONE,
                    payment_amount=p.amount,
                    notes="No settlement record found with matching transaction ID or attributes.",
                )
            )
            continue

        if len(candidates) > 1:
            # Duplicate settlements referencing the same payment ID
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
        total_refunded = sum(r.refund_amount for r in related_refunds) if related_refunds else Decimal("0.00")

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
                        notes=f"Partial refund of {total_refunded} recorded against payment of {p.amount}.",
                    )
                )
            continue

        # Amount & Tolerance Evaluation
        if diff == Decimal("0.00"):
            summary.record_item(
                ReconciliationItem(
                    transaction_id=p.transaction_id,
                    settlement_id=settlement.settlement_id,
                    status=ReconStatus.MATCHED,
                    reason_code=ReasonCode.EXACT_MATCH,
                    matched_by=matched_by,
                    payment_amount=p.amount,
                    settled_amount=settlement.settled_amount,
                    difference=diff,
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
                    notes=f"Explicit partial settlement payout: {settlement.settled_amount} of {p.amount}.",
                )
            )
        else:
            # Deterministic detection of amount mismatch (could be fees, adjustments, or errors)
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
                    notes=f"Amount difference of {diff} detected. Source records lack explicit fee breakdown.",
                )
            )

    # 3. Reverse Pass: Identify Orphan Settlements
    for s in settlements:
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
    """
    Loads all records from the database session and runs deterministic reconciliation.
    """
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
        print(f"Total Payments Analyzed:    {summary.total_payments:>5}")
        print(f"Total Settlements Analyzed: {summary.total_settlements:>5}")
        print(f"Total Refunds Analyzed:     {summary.total_refunds:>5}")
        print("--------------------------------------------------")
        print(f"MATCHED:                    {summary.matched:>5}")
        print(f"MATCHED_WITH_TOLERANCE:     {summary.matched_with_tolerance:>5}")
        print(f"AMOUNT_MISMATCH:            {summary.amount_mismatch:>5}")
        print(f"MISSING_SETTLEMENT:         {summary.missing_settlement:>5}")
        print(f"ORPHAN_SETTLEMENT:          {summary.orphan_settlement:>5}")
        print(f"AMBIGUOUS:                  {summary.ambiguous:>5}")
        print(f"DUPLICATE_SETTLEMENT:       {summary.duplicate_settlement:>5}")
        print(f"PARTIAL_SETTLEMENT:         {summary.partial_settlement:>5}")
        print(f"REFUNDED:                   {summary.refunded:>5}")
        print(f"PARTIALLY_REFUNDED:         {summary.partially_refunded:>5}")
        print(f"UNRESOLVED:                 {summary.unresolved:>5}")
        print("==================================================")
    finally:
        session.close()


if __name__ == "__main__":
    main()