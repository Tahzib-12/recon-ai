"""
ReconAI - Deterministic Candidate Scoring Engine.

Evaluates evidence strength between payment records and prospective settlement
candidates using configurable, explainable feature weights and explicit
decision thresholds. Pure Python: zero external I/O, zero AI/ML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from app.db.models import Payment, Settlement

# ---------------------------------------------------------------------------
# Scoring Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringWeights:
    """Configurable feature weights summing to 1.0."""

    amount: Decimal = Decimal("0.40")
    merchant: Decimal = Decimal("0.25")
    currency: Decimal = Decimal("0.15")
    timestamp: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        total = self.amount + self.merchant + self.currency + self.timestamp
        if total != Decimal("1.00"):
            raise ValueError(f"Scoring weights must sum to 1.00, got {total}")


@dataclass(frozen=True)
class CandidateScoringConfig:
    """Centralized thresholds and tolerances for deterministic candidate scoring."""

    weights: ScoringWeights = field(default_factory=ScoringWeights)
    amount_tolerance: Decimal = Decimal("0.01")  # Penny/paisa tolerance for amount similarity
    max_timestamp_window: timedelta = timedelta(days=3)  # Window for proximity decay
    acceptance_threshold: Decimal = Decimal("0.85")  # Minimum score to qualify as strong match
    ambiguity_margin: Decimal = Decimal("0.05")  # Minimum separation between #1 and #2


# ---------------------------------------------------------------------------
# Scoring Result Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreBreakdown:
    """Normalized [0.0 - 1.0] sub-scores for each evaluated dimension."""

    amount_score: Decimal
    merchant_score: Decimal
    currency_score: Decimal
    timestamp_score: Decimal
    raw_amount_diff: Decimal
    time_delta_seconds: float


@dataclass(frozen=True)
class CandidateScore:
    """Evaluated evidence score and breakdown for a single settlement candidate."""

    settlement_id: str
    total_score: Decimal
    breakdown: ScoreBreakdown
    settlement: Settlement


@dataclass(frozen=True)
class ScoringDecision:
    """Outcome of scoring a pool of candidates against a payment."""

    payment_id: str
    best_candidate: Optional[CandidateScore]
    ranked_candidates: list[CandidateScore]
    is_ambiguous: bool
    is_acceptable: bool
    decision_reason: str


# ---------------------------------------------------------------------------
# Feature Scoring Primitives
# ---------------------------------------------------------------------------


def score_amount_similarity(
    payment_amount: Decimal,
    settlement_amount: Decimal,
    tolerance: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    Score amount similarity using exact Decimal arithmetic.

    - Exact match -> 1.00
    - Within tolerance (e.g. <= 0.01) -> 0.90
    - Outside tolerance -> 0.00
    """
    diff = abs(payment_amount - settlement_amount)
    if diff == Decimal("0.00"):
        return Decimal("1.00"), diff
    if diff <= tolerance:
        return Decimal("0.90"), diff
    return Decimal("0.00"), diff


def score_merchant_match(payment_merchant: str, settlement_merchant: str) -> Decimal:
    """Exact merchant string matching."""
    return Decimal("1.00") if payment_merchant == settlement_merchant else Decimal("0.00")


def score_currency_match(payment_currency: str, settlement_currency: str) -> Decimal:
    """Exact ISO currency string matching."""
    return Decimal("1.00") if payment_currency == settlement_currency else Decimal("0.00")


def score_timestamp_proximity(
    payment_time: datetime,
    settlement_time: datetime,
    max_window: timedelta,
) -> tuple[Decimal, float]:
    """
    Calculate linear timestamp proximity score [0.00 - 1.00].

    Scores 1.00 if times are identical.
    Decays linearly to 0.00 at max_window.
    Settlements occurring strictly before payment are heavily penalized (0.00)
    since settlement follows payment in financial workflows.
    """
    delta = settlement_time - payment_time
    delta_seconds = delta.total_seconds()

    if delta_seconds < 0:
        # Settlement occurred before payment: invalid chronological order
        return Decimal("0.00"), delta_seconds

    max_seconds = max_window.total_seconds()
    if delta_seconds >= max_seconds:
        return Decimal("0.00"), delta_seconds

    # Linear decay: 1.0 - (delta / max)
    decay_ratio = Decimal(str(delta_seconds)) / Decimal(str(max_seconds))
    score = Decimal("1.00") - decay_ratio
    return score.quantize(Decimal("0.0001")), delta_seconds


# ---------------------------------------------------------------------------
# Core Scoring & Decision Engine
# ---------------------------------------------------------------------------


def score_candidate(
    payment: Payment,
    settlement: Settlement,
    config: Optional[CandidateScoringConfig] = None,
) -> CandidateScore:
    """Compute weighted evidence score for a single payment-settlement pair."""
    cfg = config or CandidateScoringConfig()
    w = cfg.weights

    amount_score, raw_diff = score_amount_similarity(
        payment.amount, settlement.settled_amount, cfg.amount_tolerance
    )
    merchant_score = score_merchant_match(payment.merchant_id, settlement.merchant_id)
    currency_score = score_currency_match(payment.currency, settlement.currency)
    timestamp_score, delta_secs = score_timestamp_proximity(
        payment.payment_timestamp, settlement.settlement_timestamp, cfg.max_timestamp_window
    )

    total_score = (
        (amount_score * w.amount)
        + (merchant_score * w.merchant)
        + (currency_score * w.currency)
        + (timestamp_score * w.timestamp)
    ).quantize(Decimal("0.0001"))

    breakdown = ScoreBreakdown(
        amount_score=amount_score,
        merchant_score=merchant_score,
        currency_score=currency_score,
        timestamp_score=timestamp_score,
        raw_amount_diff=raw_diff,
        time_delta_seconds=delta_secs,
    )

    return CandidateScore(
        settlement_id=settlement.settlement_id,
        total_score=total_score,
        breakdown=breakdown,
        settlement=settlement,
    )


def evaluate_candidates(
    payment: Payment,
    candidates: Sequence[Settlement],
    config: Optional[CandidateScoringConfig] = None,
) -> ScoringDecision:
    """
    Score, rank, and evaluate a pool of candidate settlements for a payment.

    Enforces deterministic sorting (total_score DESC, settlement_id ASC) and
    rigorous ambiguity detection using acceptance_threshold and ambiguity_margin.
    """
    cfg = config or CandidateScoringConfig()

    if not candidates:
        return ScoringDecision(
            payment_id=payment.transaction_id,
            best_candidate=None,
            ranked_candidates=[],
            is_ambiguous=False,
            is_acceptable=False,
            decision_reason="NO_CANDIDATES",
        )

    # Score each candidate
    scored = [score_candidate(payment, s, cfg) for s in candidates]

    # Deterministic ranking: score descending, tie-break by settlement_id ascending
    ranked = sorted(scored, key=lambda c: (-c.total_score, c.settlement_id))
    top = ranked[0]

    # Single candidate evaluation
    if len(ranked) == 1:
        is_acceptable = top.total_score >= cfg.acceptance_threshold
        reason = "SINGLE_STRONG_CANDIDATE" if is_acceptable else "SCORE_BELOW_ACCEPTANCE_THRESHOLD"
        return ScoringDecision(
            payment_id=payment.transaction_id,
            best_candidate=top if is_acceptable else None,
            ranked_candidates=ranked,
            is_ambiguous=False,
            is_acceptable=is_acceptable,
            decision_reason=reason,
        )

    # Multiple candidates: check for ties or near-ties within ambiguity margin
    second = ranked[1]
    margin = top.total_score - second.total_score

    if margin < cfg.ambiguity_margin:
        return ScoringDecision(
            payment_id=payment.transaction_id,
            best_candidate=None,
            ranked_candidates=ranked,
            is_ambiguous=True,
            is_acceptable=False,
            decision_reason=f"AMBIGUOUS_CANDIDATES_MARGIN_{margin:.4f}_BELOW_{cfg.ambiguity_margin:.4f}",
        )

    if top.total_score < cfg.acceptance_threshold:
        return ScoringDecision(
            payment_id=payment.transaction_id,
            best_candidate=None,
            ranked_candidates=ranked,
            is_ambiguous=False,
            is_acceptable=False,
            decision_reason="TOP_SCORE_BELOW_ACCEPTANCE_THRESHOLD",
        )

    return ScoringDecision(
        payment_id=payment.transaction_id,
        best_candidate=top,
        ranked_candidates=ranked,
        is_ambiguous=False,
        is_acceptable=True,
        decision_reason="DECISIVE_WINNER",
    )