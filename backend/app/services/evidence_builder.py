"""
ReconAI - Investigation Evidence Builder.

Extracts minimal, focused, and deterministic facts from reconciliation results
into an EvidencePackage. Computes all financial differences deterministically.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from app.db.models import Payment, Refund, Settlement
from app.services.investigation_models import (
    CandidateEvidence,
    EvidencePackage,
    PaymentEvidence,
    RefundEvidence,
    SettlementEvidence,
)
from app.services.reconciliation import ReconciliationItem


def build_evidence_package(
    item: ReconciliationItem,
    payments: Sequence[Payment],
    settlements: Sequence[Settlement],
    refunds: Sequence[Refund],
) -> EvidencePackage:
    """
    Construct a structured EvidencePackage for an exception item.
    All mathematical differences and scores are computed deterministically.
    """
    case_id = item.transaction_id or item.settlement_id or "UNKNOWN_CASE"

    # 1. Resolve Payment Evidence
    payment_evidence: Optional[PaymentEvidence] = None
    matched_payments = [p for p in payments if p.transaction_id == item.transaction_id]
    if matched_payments:
        p = matched_payments[0]
        payment_evidence = PaymentEvidence(
            transaction_id=p.transaction_id,
            merchant_id=p.merchant_id,
            customer_id=p.customer_id,
            amount=str(p.amount),
            currency=p.currency,
            payment_status=p.payment_status,
            payment_method=p.payment_method,
            payment_timestamp=p.payment_timestamp.isoformat(),
        )

    # 2. Resolve Relevant Settlements (Exact match, target, or candidates)
    relevant_set_ids = set()
    if item.settlement_id:
        relevant_set_ids.add(item.settlement_id)
    relevant_set_ids.update(item.candidate_settlement_ids)

    relevant_settlements = [s for s in settlements if s.settlement_id in relevant_set_ids]
    settlement_evidence = [
        SettlementEvidence(
            settlement_id=s.settlement_id,
            transaction_id=s.transaction_id,
            merchant_id=s.merchant_id,
            settled_amount=str(s.settled_amount),
            currency=s.currency,
            settlement_status=s.settlement_status,
            settlement_timestamp=s.settlement_timestamp.isoformat(),
        )
        for s in relevant_settlements
    ]

    # 3. Resolve Relevant Refunds
    matched_refunds = [r for r in refunds if r.transaction_id == item.transaction_id]
    refund_evidence = [
        RefundEvidence(
            refund_id=r.refund_id,
            transaction_id=r.transaction_id,
            refund_amount=str(r.refund_amount),
            refund_status=r.refund_status,
            refund_timestamp=r.refund_timestamp.isoformat(),
        )
        for r in matched_refunds
    ]

    # 4. Resolve Candidate Scores
    candidate_evidence = [
        CandidateEvidence(
            settlement_id=cs.settlement_id,
            total_score=str(cs.total_score),
            amount_score=str(cs.breakdown.amount_score),
            merchant_score=str(cs.breakdown.merchant_score),
            currency_score=str(cs.breakdown.currency_score),
            timestamp_score=str(cs.breakdown.timestamp_score),
            raw_amount_diff=str(cs.breakdown.raw_amount_diff),
            time_delta_seconds=cs.breakdown.time_delta_seconds,
        )
        for cs in item.candidate_scores
    ]

    diff_str = str(item.difference) if item.difference is not None else None

    return EvidencePackage(
        case_id=case_id,
        reconciliation_status=item.status.value,
        reason_code=item.reason_code.value,
        payment=payment_evidence,
        settlements=settlement_evidence,
        refunds=refund_evidence,
        candidate_scores=candidate_evidence,
        computed_amount_difference=diff_str,
        notes=item.notes,
    )