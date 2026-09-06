"""
ReconAI - AI Investigation Domain Models.

Strongly-typed, provider-independent data structures for investigation cases,
evidence packages, and structured AI verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class InvestigationClassification(str, Enum):
    """Controlled taxonomy of AI exception findings."""

    LIKELY_MATCH = "LIKELY_MATCH"
    LIKELY_AMOUNT_DISCREPANCY = "LIKELY_AMOUNT_DISCREPANCY"
    LIKELY_DELAYED_SETTLEMENT = "LIKELY_DELAYED_SETTLEMENT"
    LIKELY_MISSING_SETTLEMENT = "LIKELY_MISSING_SETTLEMENT"
    LIKELY_ORPHAN_SETTLEMENT = "LIKELY_ORPHAN_SETTLEMENT"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RecommendedAction(str, Enum):
    """Recommended operational next step."""

    APPROVE_MATCH = "APPROVE_MATCH"
    REQUEST_MERCHANT_FEE_SCHEDULE = "REQUEST_MERCHANT_FEE_SCHEDULE"
    FLAG_FOR_MANUAL_REVIEW = "FLAG_FOR_MANUAL_REVIEW"
    QUERY_GATEWAY_SLA = "QUERY_GATEWAY_SLA"
    ESCALATE_UNALLOCATED_FUNDS = "ESCALATE_UNALLOCATED_FUNDS"
    REVERSE_DUPLICATE = "REVERSE_DUPLICATE"
    AWAIT_SETTLEMENT_WINDOW = "AWAIT_SETTLEMENT_WINDOW"


@dataclass(frozen=True)
class PaymentEvidence:
    transaction_id: str
    merchant_id: str
    customer_id: str
    amount: str
    currency: str
    payment_status: str
    payment_method: str
    payment_timestamp: str


@dataclass(frozen=True)
class SettlementEvidence:
    settlement_id: str
    transaction_id: Optional[str]
    merchant_id: str
    settled_amount: str
    currency: str
    settlement_status: str
    settlement_timestamp: str


@dataclass(frozen=True)
class RefundEvidence:
    refund_id: str
    transaction_id: str
    refund_amount: str
    refund_status: str
    refund_timestamp: str


@dataclass(frozen=True)
class CandidateEvidence:
    settlement_id: str
    total_score: str
    amount_score: str
    merchant_score: str
    currency_score: str
    timestamp_score: str
    raw_amount_diff: str
    time_delta_seconds: float


@dataclass(frozen=True)
class EvidencePackage:
    """Consolidated, focused evidence payload prepared for AI reasoning."""

    case_id: str
    reconciliation_status: str
    reason_code: str
    payment: Optional[PaymentEvidence]
    settlements: list[SettlementEvidence]
    refunds: list[RefundEvidence]
    candidate_scores: list[CandidateEvidence]
    computed_amount_difference: Optional[str]
    notes: Optional[str]


@dataclass(frozen=True)
class InvestigationResult:
    """Structured, auditable output returned by the AI investigation layer."""

    case_id: str
    classification: InvestigationClassification
    summary: str
    observed_facts: list[str]
    inferences: list[str]
    uncertainties: list[str]
    recommended_action: RecommendedAction
    needs_human_review: bool
    investigator_model: str