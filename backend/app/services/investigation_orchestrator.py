"""
ReconAI - Investigation Pipeline Orchestrator.

Applies the InvestigationPolicy to reconciliation results, builds evidence
packages, and invokes the configured AIInvestigator.
"""

from __future__ import annotations

from typing import Sequence

from app.db.models import Payment, Refund, Settlement
from app.services.ai_investigator import AIInvestigator, InvestigationPolicy
from app.services.evidence_builder import build_evidence_package
from app.services.investigation_models import InvestigationResult
from app.services.reconciliation import ReconciliationSummary


def investigate_exceptions(
    summary: ReconciliationSummary,
    payments: Sequence[Payment],
    settlements: Sequence[Settlement],
    refunds: Sequence[Refund],
    investigator: AIInvestigator,
) -> list[InvestigationResult]:
    """
    Scans reconciliation summary items, invokes AI only for items requiring
    investigation according to InvestigationPolicy, and returns structured findings.
    """
    results: list[InvestigationResult] = []

    for item in summary.items:
        if InvestigationPolicy.should_investigate(item.status):
            evidence = build_evidence_package(item, payments, settlements, refunds)
            verdict = investigator.investigate(evidence)
            results.append(verdict)

    return results