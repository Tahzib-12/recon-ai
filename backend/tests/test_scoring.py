"""
Unit tests for the deterministic candidate scoring engine.
Verifies scoring formulas, weight balance, decimal precision, and ambiguity resolution.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from app.db.models import Payment, Settlement
from app.services.scoring import (
    CandidateScoringConfig,
    ScoringWeights,
    evaluate_candidates,
    score_amount_similarity,
    score_candidate,
    score_currency_match,
    score_merchant_match,
    score_timestamp_proximity,
)

BASE_TIME = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


def make_payment(
    tx_id: str = "TXN001",
    merchant: str = "MER01",
    amount: str = "100.00",
    currency: str = "INR",
    timestamp: datetime = BASE_TIME,
) -> Payment:
    return Payment(
        transaction_id=tx_id,
        merchant_id=merchant,
        customer_id="CUS01",
        amount=Decimal(amount),
        currency=currency,
        payment_status="SUCCESS",
        payment_method="UPI",
        payment_timestamp=timestamp,
    )


def make_settlement(
    set_id: str = "SET001",
    merchant: str = "MER01",
    amount: str = "100.00",
    currency: str = "INR",
    timestamp: datetime = BASE_TIME + timedelta(hours=2),
) -> Settlement:
    return Settlement(
        settlement_id=set_id,
        transaction_id=None,
        merchant_id=merchant,
        settled_amount=Decimal(amount),
        currency=currency,
        settlement_status="SETTLED",
        settlement_timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Feature Scoring Tests
# ---------------------------------------------------------------------------


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="Scoring weights must sum to 1.00"):
        ScoringWeights(amount=Decimal("0.50"), merchant=Decimal("0.50"), currency=Decimal("0.10"), timestamp=Decimal("0.10"))


def test_amount_similarity_exact():
    score, diff = score_amount_similarity(Decimal("100.00"), Decimal("100.00"), Decimal("0.01"))
    assert score == Decimal("1.00")
    assert diff == Decimal("0.00")


def test_amount_similarity_within_tolerance():
    score, diff = score_amount_similarity(Decimal("100.00"), Decimal("100.01"), Decimal("0.01"))
    assert score == Decimal("0.90")
    assert diff == Decimal("0.01")


def test_amount_similarity_outside_tolerance():
    score, diff = score_amount_similarity(Decimal("100.00"), Decimal("95.00"), Decimal("0.01"))
    assert score == Decimal("0.00")
    assert diff == Decimal("5.00")


def test_merchant_and_currency_matches():
    assert score_merchant_match("MER01", "MER01") == Decimal("1.00")
    assert score_merchant_match("MER01", "MER02") == Decimal("0.00")
    assert score_currency_match("USD", "USD") == Decimal("1.00")
    assert score_currency_match("USD", "INR") == Decimal("0.00")


def test_timestamp_proximity_decay():
    window = timedelta(days=2)
    # Exact same time -> 1.0
    score, _ = score_timestamp_proximity(BASE_TIME, BASE_TIME, window)
    assert score == Decimal("1.0000")

    # Exactly halfway (1 day in a 2-day window) -> 0.5
    score, _ = score_timestamp_proximity(BASE_TIME, BASE_TIME + timedelta(days=1), window)
    assert score == Decimal("0.5000")

    # Beyond window -> 0.0
    score, _ = score_timestamp_proximity(BASE_TIME, BASE_TIME + timedelta(days=3), window)
    assert score == Decimal("0.0000")

    # Settlement before payment (chronologically backwards) -> 0.0
    score, _ = score_timestamp_proximity(BASE_TIME, BASE_TIME - timedelta(hours=1), window)
    assert score == Decimal("0.0000")


# ---------------------------------------------------------------------------
# Decision & Ranking Tests
# ---------------------------------------------------------------------------


def test_single_strong_candidate():
    p = make_payment()
    s = make_settlement()
    decision = evaluate_candidates(p, [s])

    assert decision.is_acceptable is True
    assert decision.is_ambiguous is False
    assert decision.best_candidate is not None
    assert decision.best_candidate.settlement_id == "SET001"
    assert decision.best_candidate.total_score >= Decimal("0.85")


def test_multiple_candidates_decisive_winner():
    p = make_payment(amount="100.00")
    # Candidate A: exact amount, close time
    s_a = make_settlement(set_id="SET_A", amount="100.00", timestamp=BASE_TIME + timedelta(hours=1))
    # Candidate B: different merchant and amount outside tolerance
    s_b = make_settlement(set_id="SET_B", merchant="OTHER_MERCH", amount="50.00", timestamp=BASE_TIME + timedelta(days=1))

    decision = evaluate_candidates(p, [s_a, s_b])
    assert decision.is_acceptable is True
    assert decision.is_ambiguous is False
    assert decision.best_candidate is not None
    assert decision.best_candidate.settlement_id == "SET_A"
    assert decision.decision_reason == "DECISIVE_WINNER"


def test_near_tie_detected_as_ambiguous():
    p = make_payment(amount="100.00")
    # Both candidates have identical amount, merchant, currency, and proximate timestamps (1 min apart)
    s_a = make_settlement(set_id="SET_A", timestamp=BASE_TIME + timedelta(minutes=5))
    s_b = make_settlement(set_id="SET_B", timestamp=BASE_TIME + timedelta(minutes=6))

    decision = evaluate_candidates(p, [s_a, s_b])
    assert decision.is_ambiguous is True
    assert decision.is_acceptable is False
    assert decision.best_candidate is None
    assert "AMBIGUOUS_CANDIDATES" in decision.decision_reason


def test_exact_tie_deterministic_ranking():
    p = make_payment(amount="100.00")
    # Identical timestamps and attributes
    s_b = make_settlement(set_id="SET_B", timestamp=BASE_TIME + timedelta(hours=1))
    s_a = make_settlement(set_id="SET_A", timestamp=BASE_TIME + timedelta(hours=1))

    decision = evaluate_candidates(p, [s_b, s_a])
    assert decision.is_ambiguous is True
    # Verify deterministic ordering: score tied, but SET_A comes before SET_B alphabetically
    assert decision.ranked_candidates[0].settlement_id == "SET_A"
    assert decision.ranked_candidates[1].settlement_id == "SET_B"


def test_no_candidates_unresolved():
    p = make_payment()
    decision = evaluate_candidates(p, [])
    assert decision.is_acceptable is False
    assert decision.is_ambiguous is False
    assert decision.decision_reason == "NO_CANDIDATES"