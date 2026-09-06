"""
ReconAI - Dashboard & Reconciliation Query API.

Exposes high-level reconciliation metrics, filterable exception queues,
and complete case drill-down details (candidates, AI verdicts, human reviews, audit logs).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Payment, Refund, ReviewRecord, Settlement
from app.services.audit_service import AuditService
from app.services.evidence_builder import build_evidence_package
from app.services.fake_investigator import FakeAIInvestigator
from app.services.investigation_orchestrator import investigate_exceptions
from app.services.reconciliation import (
    ReconciliationItem,
    ReconciliationSummary,
    ReconStatus,
    run_database_reconciliation,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------------------------


class StatusCounts(BaseModel):
    MATCHED: int
    MATCHED_WITH_TOLERANCE: int
    AMOUNT_MISMATCH: int
    MISSING_SETTLEMENT: int
    ORPHAN_SETTLEMENT: int
    AMBIGUOUS: int
    DUPLICATE_SETTLEMENT: int
    PARTIAL_SETTLEMENT: int
    REFUNDED: int
    PARTIALLY_REFUNDED: int
    UNRESOLVED: int


class DashboardSummaryResponse(BaseModel):
    total_cases: int
    total_payments: int
    total_settlements: int
    total_refunds: int
    resolved_cases: int
    exception_cases: int
    match_rate_pct: float
    exception_rate_pct: float
    status_counts: StatusCounts


class CaseListItem(BaseModel):
    case_id: str
    reconciliation_status: str
    reason_code: str
    matched_by: str
    payment_amount: Optional[str] = None
    settled_amount: Optional[str] = None
    difference: Optional[str] = None
    merchant_id: Optional[str] = None
    currency: Optional[str] = None
    candidate_count: int
    review_status: str
    has_ai_investigation: bool


class CaseListResponse(BaseModel):
    total: int
    cases: list[CaseListItem]


class CaseDetailResponse(BaseModel):
    case_id: str
    reconciliation_status: str
    reason_code: str
    matched_by: str
    payment_amount: Optional[str] = None
    settled_amount: Optional[str] = None
    difference: Optional[str] = None
    notes: Optional[str] = None
    payment: Optional[dict[str, Any]] = None
    settlement: Optional[dict[str, Any]] = None
    refunds: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    ai_investigation: Optional[dict[str, Any]] = None
    human_review: Optional[dict[str, Any]] = None
    audit_timeline: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryResponse:
    """Returns high-level reconciliation counts and operational health metrics."""
    summary = run_database_reconciliation(db)

    # Resolved represents clean matches + fully refunded life-cycles
    resolved = summary.matched + summary.matched_with_tolerance + summary.refunded
    # Exceptions require investigation or review
    exceptions = (
        summary.amount_mismatch
        + summary.missing_settlement
        + summary.orphan_settlement
        + summary.ambiguous
        + summary.duplicate_settlement
        + summary.partial_settlement
        + summary.partially_refunded
        + summary.unresolved
    )

    total_evaluated = len(summary.items)
    match_rate = round((resolved / total_evaluated * 100), 2) if total_evaluated > 0 else 0.0
    exception_rate = round((exceptions / total_evaluated * 100), 2) if total_evaluated > 0 else 0.0

    return DashboardSummaryResponse(
        total_cases=total_evaluated,
        total_payments=summary.total_payments,
        total_settlements=summary.total_settlements,
        total_refunds=summary.total_refunds,
        resolved_cases=resolved,
        exception_cases=exceptions,
        match_rate_pct=match_rate,
        exception_rate_pct=exception_rate,
        status_counts=StatusCounts(
            MATCHED=summary.matched,
            MATCHED_WITH_TOLERANCE=summary.matched_with_tolerance,
            AMOUNT_MISMATCH=summary.amount_mismatch,
            MISSING_SETTLEMENT=summary.missing_settlement,
            ORPHAN_SETTLEMENT=summary.orphan_settlement,
            AMBIGUOUS=summary.ambiguous,
            DUPLICATE_SETTLEMENT=summary.duplicate_settlement,
            PARTIAL_SETTLEMENT=summary.partial_settlement,
            REFUNDED=summary.refunded,
            PARTIALLY_REFUNDED=summary.partially_refunded,
            UNRESOLVED=summary.unresolved,
        ),
    )


@router.get("/cases", response_model=CaseListResponse)
def list_reconciliation_cases(
    status: Optional[str] = Query(None, description="Filter by ReconStatus (e.g. AMBIGUOUS, AMOUNT_MISMATCH)"),
    merchant_id: Optional[str] = Query(None, description="Filter by Merchant ID"),
    currency: Optional[str] = Query(None, description="Filter by Currency"),
    search: Optional[str] = Query(None, description="Search case ID / Transaction ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> CaseListResponse:
    """Returns a filtered, paginated list of reconciliation cases."""
    summary = run_database_reconciliation(db)
    payments_map = {p.transaction_id: p for p in db.query(Payment).all()}
    reviews_map = {r.case_id: r for r in db.query(ReviewRecord).all()}

    filtered_items: list[ReconciliationItem] = []
    for item in summary.items:
        case_id = item.transaction_id or item.settlement_id or "UNKNOWN"
        p = payments_map.get(item.transaction_id) if item.transaction_id else None

        # Filter by status
        if status and item.status.value != status:
            continue

        # Filter by merchant
        if merchant_id and (not p or p.merchant_id != merchant_id):
            continue

        # Filter by currency
        if currency and (not p or p.currency != currency):
            continue

        # Search query
        if search and search.lower() not in case_id.lower():
            continue

        filtered_items.append(item)

    total = len(filtered_items)
    paginated = filtered_items[offset : offset + limit]

    cases_out: list[CaseListItem] = []
    for item in paginated:
        case_id = item.transaction_id or item.settlement_id or "UNKNOWN"
        p = payments_map.get(item.transaction_id) if item.transaction_id else None
        rev = reviews_map.get(case_id)

        # Cases that trigger AI investigation
        has_ai = item.status in {
            ReconStatus.AMBIGUOUS,
            ReconStatus.AMOUNT_MISMATCH,
            ReconStatus.MISSING_SETTLEMENT,
            ReconStatus.ORPHAN_SETTLEMENT,
            ReconStatus.PARTIAL_SETTLEMENT,
            ReconStatus.UNRESOLVED,
        }

        cases_out.append(
            CaseListItem(
                case_id=case_id,
                reconciliation_status=item.status.value,
                reason_code=item.reason_code.value,
                matched_by=item.matched_by.value,
                payment_amount=str(item.payment_amount) if item.payment_amount is not None else None,
                settled_amount=str(item.settled_amount) if item.settled_amount is not None else None,
                difference=str(item.difference) if item.difference is not None else None,
                merchant_id=p.merchant_id if p else None,
                currency=p.currency if p else None,
                candidate_count=len(item.candidate_settlement_ids) or len(item.candidate_scores),
                review_status=rev.review_status if rev else "UNASSIGNED",
                has_ai_investigation=has_ai,
            )
        )

    return CaseListResponse(total=total, cases=cases_out)


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
def get_case_detail(case_id: str, db: Session = Depends(get_db)) -> CaseDetailResponse:
    """Returns complete 360-degree case details: data, candidate evidence, AI findings, review state, and audit trail."""
    summary = run_database_reconciliation(db)
    target_item = next(
        (it for it in summary.items if (it.transaction_id == case_id or it.settlement_id == case_id)),
        None,
    )

    if not target_item:
        raise HTTPException(status_code=404, detail=f"Reconciliation case '{case_id}' not found.")

    payments = db.query(Payment).all()
    settlements = db.query(Settlement).all()
    refunds = db.query(Refund).all()

    # Resolve payment details
    p_rec = next((p for p in payments if p.transaction_id == target_item.transaction_id), None)
    payment_dict = (
        {
            "transaction_id": p_rec.transaction_id,
            "merchant_id": p_rec.merchant_id,
            "customer_id": p_rec.customer_id,
            "amount": str(p_rec.amount),
            "currency": p_rec.currency,
            "payment_status": p_rec.payment_status,
            "payment_method": p_rec.payment_method,
            "payment_timestamp": p_rec.payment_timestamp.isoformat(),
        }
        if p_rec
        else None
    )

    # Resolve settlement details
    s_rec = next((s for s in settlements if s.settlement_id == target_item.settlement_id), None)
    settlement_dict = (
        {
            "settlement_id": s_rec.settlement_id,
            "transaction_id": s_rec.transaction_id,
            "merchant_id": s_rec.merchant_id,
            "settled_amount": str(s_rec.settled_amount),
            "currency": s_rec.currency,
            "settlement_status": s_rec.settlement_status,
            "settlement_timestamp": s_rec.settlement_timestamp.isoformat(),
        }
        if s_rec
        else None
    )

    # Resolve refunds
    rel_refunds = [r for r in refunds if r.transaction_id == target_item.transaction_id]
    refunds_list = [
        {
            "refund_id": r.refund_id,
            "transaction_id": r.transaction_id,
            "refund_amount": str(r.refund_amount),
            "refund_status": r.refund_status,
            "refund_timestamp": r.refund_timestamp.isoformat(),
        }
        for r in rel_refunds
    ]

    # Resolve candidates and score breakdown
    candidates_list: list[dict[str, Any]] = []
    if target_item.candidate_scores:
        for cs in target_item.candidate_scores:
            candidates_list.append(
                {
                    "settlement_id": cs.settlement_id,
                    "total_score": str(cs.total_score),
                    "amount_score": str(cs.breakdown.amount_score),
                    "merchant_score": str(cs.breakdown.merchant_score),
                    "currency_score": str(cs.breakdown.currency_score),
                    "timestamp_score": str(cs.breakdown.timestamp_score),
                    "raw_amount_diff": str(cs.breakdown.raw_amount_diff),
                    "time_delta_seconds": cs.breakdown.time_delta_seconds,
                    "settled_amount": str(cs.settlement.settled_amount),
                    "settlement_timestamp": cs.settlement.settlement_timestamp.isoformat(),
                }
            )

    # Resolve AI Investigation finding
    ai_dict: Optional[dict[str, Any]] = None
    needs_ai = target_item.status in {
        ReconStatus.AMBIGUOUS,
        ReconStatus.AMOUNT_MISMATCH,
        ReconStatus.MISSING_SETTLEMENT,
        ReconStatus.ORPHAN_SETTLEMENT,
        ReconStatus.PARTIAL_SETTLEMENT,
        ReconStatus.UNRESOLVED,
    }
    if needs_ai:
        # Use deterministic investigator to guarantee consistent explainability
        evidence = build_evidence_package(target_item, payments, settlements, refunds)
        investigator = FakeAIInvestigator()
        verdict = investigator.investigate(evidence)
        ai_dict = {
            "classification": verdict.classification.value,
            "summary": verdict.summary,
            "observed_facts": verdict.observed_facts,
            "inferences": verdict.inferences,
            "uncertainties": verdict.uncertainties,
            "recommended_action": verdict.recommended_action.value,
            "needs_human_review": verdict.needs_human_review,
            "investigator_model": verdict.investigator_model,
        }

    # Resolve Human Review state
    rev_rec = db.query(ReviewRecord).filter_by(case_id=case_id).first()
    review_dict = (
        {
            "review_status": rev_rec.review_status,
            "reviewer_id": rev_rec.reviewer_id,
            "decision": rev_rec.decision,
            "selected_settlement_id": rev_rec.selected_settlement_id,
            "final_resolution_status": rev_rec.final_resolution_status,
            "notes": rev_rec.notes,
            "created_at": rev_rec.created_at.isoformat() if rev_rec.created_at else None,
            "decided_at": rev_rec.decided_at.isoformat() if rev_rec.decided_at else None,
        }
        if rev_rec
        else None
    )

    # Resolve chronological audit timeline
    audit_events = AuditService.get_case_history(case_id, db)
    audit_list = [ev.to_dict() for ev in audit_events]

    return CaseDetailResponse(
        case_id=case_id,
        reconciliation_status=target_item.status.value,
        reason_code=target_item.reason_code.value,
        matched_by=target_item.matched_by.value,
        payment_amount=str(target_item.payment_amount) if target_item.payment_amount is not None else None,
        settled_amount=str(target_item.settled_amount) if target_item.settled_amount is not None else None,
        difference=str(target_item.difference) if target_item.difference is not None else None,
        notes=target_item.notes,
        payment=payment_dict,
        settlement=settlement_dict,
        refunds=refunds_list,
        candidates=candidates_list,
        ai_investigation=ai_dict,
        human_review=review_dict,
        audit_timeline=audit_list,
    )