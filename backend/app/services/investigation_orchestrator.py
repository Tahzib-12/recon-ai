"""
ReconAI - Investigation Pipeline Orchestrator.

Applies the InvestigationPolicy to reconciliation results, builds evidence
packages, and invokes the configured AIInvestigator.
"""

from __future__ import annotations

from typing import Optional, Sequence
from sqlalchemy.orm import Session

from app.db.models import Payment, Refund, Settlement
from app.services.ai_investigator import AIInvestigator, InvestigationPolicy
from app.services.audit_models import ActorType, AuditEventType
from app.services.audit_service import AuditService
from app.services.evidence_builder import build_evidence_package
from app.services.investigation_models import InvestigationResult
from app.services.reconciliation import ReconciliationSummary


def investigate_exceptions(
    summary: ReconciliationSummary,
    payments: Sequence[Payment],
    settlements: Sequence[Settlement],
    refunds: Sequence[Refund],
    investigator: AIInvestigator,
    session: Optional[Session] = None,
) -> list[InvestigationResult]:
    """
    Scans reconciliation summary items, invokes AI only for items requiring
    investigation according to InvestigationPolicy, and returns structured findings.
    """
    results: list[InvestigationResult] = []

    for item in summary.items:
        if InvestigationPolicy.should_investigate(item.status):
            case_id = item.transaction_id or item.settlement_id or "UNKNOWN"
            if session:
                AuditService.record_event(
                    case_id=case_id,
                    event_type=AuditEventType.INVESTIGATION_STARTED,
                    actor_type=ActorType.SYSTEM,
                    actor_id="investigation_orchestrator",
                    description=f"Automated AI investigation initiated for status {item.status.value}.",
                    previous_state=item.status.value,
                    metadata={"reason_code": item.reason_code.value},
                    session=session,
                )

            evidence = build_evidence_package(item, payments, settlements, refunds)
            verdict = investigator.investigate(evidence)
            results.append(verdict)

            if session:
                AuditService.record_event(
                    case_id=case_id,
                    event_type=AuditEventType.INVESTIGATION_COMPLETED,
                    actor_type=ActorType.AI,
                    actor_id=verdict.investigator_model,
                    description=f"AI Investigation concluded: {verdict.classification.value}.",
                    new_state=verdict.classification.value,
                    metadata={
                        "summary": verdict.summary,
                        "recommended_action": verdict.recommended_action.value,
                        "needs_human_review": verdict.needs_human_review,
                    },
                    session=session,
                )
    return results