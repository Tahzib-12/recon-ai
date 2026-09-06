"""
Unit and invariant tests for the deterministic reconciliation engine.
Tests all scenarios using isolated in-memory fixtures and verifies
seamless integration with candidate scoring.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import pytest

from app.db.models import Payment, Refund, Settlement
from app.services.reconciliation import (
    MatchedBy,
    ReasonCode,
    ReconciliationConfig,
    ReconStatus,
    reconcile_records,
)

BASE_TIME = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


def create_payment(
    tx_id: str = "TXN001",
    merchant: str = "MER01",
    customer: str = "CUS01",
    amount: str = "1000.00",
    currency: str = "INR",
    status: str = "SUCCESS",
    timestamp: datetime = BASE_TIME,
) -> Payment:
    return Payment(
        transaction_id=tx_id,
        merchant_id=merchant,
        customer_id=customer,
        amount=Decimal(amount),
        currency=currency,
        payment_status=status,
        payment_method="UPI",
        payment_timestamp=timestamp,
    )


def create_settlement(
    set_id: str = "SET001",
    tx_id: str | None = "TXN001",
    merchant: str = "MER01",
    amount: str = "1000.00",
    currency: str = "INR",
    status: str = "SETTLED",
    timestamp: datetime = BASE_TIME + timedelta(hours=4),
) -> Settlement:
    return Settlement(
        settlement_id=set_id,
        transaction_id=tx_id,
        merchant_id=merchant,
        settled_amount=Decimal(amount),
        currency=currency,
        settlement_status=status,
        settlement_timestamp=timestamp,
    )


def create_refund(
    ref_id: str = "REF001",
    tx_id: str = "TXN001",
    amount: str = "1000.00",
    status: str = "PROCESSED",
    timestamp: datetime = BASE_TIME + timedelta(hours=24),
) -> Refund:
    return Refund(
        refund_id=ref_id,
        transaction_id=tx_id,
        refund_amount=Decimal(amount),
        refund_status=status,
        refund_timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_exact_transaction_id_match():
    payment = create_payment(amount="1000.00")
    settlement = create_settlement(amount="1000.00")

    summary = reconcile_records([payment], [settlement], [])
    assert summary.matched == 1
    assert summary.items[0].status == ReconStatus.MATCHED
    assert summary.items[0].reason_code == ReasonCode.EXACT_MATCH
    assert summary.items[0].matched_by == MatchedBy.EXACT_TRANSACTION_ID


def test_exact_amount_match():
    payment = create_payment(amount="2500.50")
    settlement = create_settlement(amount="2500.50")

    summary = reconcile_records([payment], [settlement], [])
    assert summary.matched == 1
    assert summary.items[0].difference == Decimal("0.00")


def test_amount_mismatch():
    payment = create_payment(amount="1000.00")
    settlement = create_settlement(amount="971.00")

    summary = reconcile_records([payment], [settlement], [])
    assert summary.amount_mismatch == 1
    item = summary.items[0]
    assert item.status == ReconStatus.AMOUNT_MISMATCH
    assert item.difference == Decimal("29.00")
    assert item.reason_code == ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE


def test_missing_settlement():
    payment = create_payment()

    summary = reconcile_records([payment], [], [])
    assert summary.missing_settlement == 1
    assert summary.items[0].status == ReconStatus.MISSING_SETTLEMENT
    assert summary.items[0].settlement_id is None


def test_orphan_settlement():
    settlement = create_settlement(tx_id="NON_EXISTENT_TX")

    summary = reconcile_records([], [settlement], [])
    assert summary.orphan_settlement == 1
    assert summary.items[0].status == ReconStatus.ORPHAN_SETTLEMENT
    assert summary.items[0].settlement_id == "SET001"


def test_fallback_candidate_scoring_when_transaction_id_is_null():
    payment = create_payment(amount="500.00")
    settlement = create_settlement(tx_id=None, amount="500.00")

    summary = reconcile_records([payment], [settlement], [])
    assert summary.matched == 1
    item = summary.items[0]
    assert item.status == ReconStatus.MATCHED
    assert item.matched_by == MatchedBy.SCORED_CANDIDATE
    assert item.settlement_id == "SET001"
    assert len(item.candidate_scores) == 1
    assert item.candidate_scores[0].total_score >= Decimal("0.85")


def test_ambiguous_fallback_candidates():
    payment = create_payment(tx_id="TXN_AMB", amount="5000.00")
    set_a = create_settlement(
        set_id="SET_A",
        tx_id=None,
        amount="5000.00",
        timestamp=BASE_TIME + timedelta(minutes=4),
    )
    set_b = create_settlement(
        set_id="SET_B",
        tx_id=None,
        amount="5000.00",
        timestamp=BASE_TIME + timedelta(minutes=6),
    )

    summary = reconcile_records([payment], [set_a, set_b], [])
    assert summary.ambiguous == 1
    item = summary.items[0]
    assert item.status == ReconStatus.AMBIGUOUS
    assert item.reason_code == ReasonCode.MULTIPLE_CANDIDATES
    assert "SET_A" in item.candidate_settlement_ids
    assert "SET_B" in item.candidate_settlement_ids


def test_partial_settlement():
    payment = create_payment(amount="10000.00")
    settlement = create_settlement(amount="6000.00", status="PARTIALLY_SETTLED")

    summary = reconcile_records([payment], [settlement], [])
    assert summary.partial_settlement == 1
    item = summary.items[0]
    assert item.status == ReconStatus.PARTIAL_SETTLEMENT
    assert item.difference == Decimal("4000.00")


def test_duplicate_settlement():
    payment = create_payment()
    set1 = create_settlement(set_id="SET001")
    set2 = create_settlement(set_id="SET002")

    summary = reconcile_records([payment], [set1, set2], [])
    assert summary.duplicate_settlement == 1
    item = summary.items[0]
    assert item.status == ReconStatus.DUPLICATE_SETTLEMENT
    assert len(item.candidate_settlement_ids) == 2


def test_full_refund():
    payment = create_payment(amount="4000.00", status="REFUNDED")
    settlement = create_settlement(amount="4000.00")
    refund = create_refund(amount="4000.00")

    summary = reconcile_records([payment], [settlement], [refund])
    assert summary.refunded == 1
    item = summary.items[0]
    assert item.status == ReconStatus.REFUNDED
    assert item.reason_code == ReasonCode.FULL_REFUND_RECORDED


def test_partial_refund():
    payment = create_payment(amount="5000.00", status="PARTIALLY_REFUNDED")
    settlement = create_settlement(amount="5000.00")
    refund = create_refund(amount="2000.00")

    summary = reconcile_records([payment], [settlement], [refund])
    assert summary.partially_refunded == 1
    item = summary.items[0]
    assert item.status == ReconStatus.PARTIALLY_REFUNDED
    assert item.reason_code == ReasonCode.PARTIAL_REFUND_RECORDED


def test_rounding_tolerance():
    payment = create_payment(amount="1000.00")

    set_tol = create_settlement(amount="999.99")
    summary = reconcile_records([payment], [set_tol], [])
    assert summary.matched_with_tolerance == 1
    assert summary.items[0].status == ReconStatus.MATCHED_WITH_TOLERANCE

    set_exceed = create_settlement(amount="999.98")
    summary2 = reconcile_records([payment], [set_exceed], [])
    assert summary2.amount_mismatch == 1
    assert summary2.items[0].status == ReconStatus.AMOUNT_MISMATCH


def test_determinism_repeated_execution():
    payments = [
        create_payment(tx_id=f"TX_{i}", amount=str(100 * i)) for i in range(1, 10)
    ]
    settlements = [
        create_settlement(set_id=f"SET_{i}", tx_id=f"TX_{i}", amount=str(100 * i))
        for i in range(1, 10)
    ]

    run1 = reconcile_records(payments, settlements, [])
    run2 = reconcile_records(payments, settlements, [])

    assert run1.matched == run2.matched
    for i in range(len(run1.items)):
        assert run1.items[i].status == run2.items[i].status
        assert run1.items[i].difference == run2.items[i].difference


def test_ground_truth_isolation():
    from app.services import reconciliation

    source = inspect.getsource(reconciliation)
    assert "ground_truth" not in source