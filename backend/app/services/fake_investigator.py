"""
ReconAI - Deterministic Fake AI Investigator.

Provides offline, reproducible, structured investigation results for unit tests
and local environments without external API calls or network access.
"""

from __future__ import annotations

from app.services.ai_investigator import AIInvestigator
from app.services.investigation_models import (
    EvidencePackage,
    InvestigationClassification,
    InvestigationResult,
    RecommendedAction,
)


class FakeAIInvestigator(AIInvestigator):
    """Predictable, rule-based investigator for testing and offline development."""

    def investigate(self, evidence: EvidencePackage) -> InvestigationResult:
        status = evidence.reconciliation_status

        if status == "AMOUNT_MISMATCH":
            diff = evidence.computed_amount_difference or "0"
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.LIKELY_AMOUNT_DISCREPANCY,
                summary=f"Settlement amount differs from payment by ₹{diff}.",
                observed_facts=[
                    f"Payment amount: {evidence.payment.amount if evidence.payment else 'N/A'}",
                    f"Computed difference: ₹{diff}",
                ],
                inferences=["Difference is consistent with a payment processing fee or tax deduction."],
                uncertainties=["No explicit fee rate or deduction schedule exists in the dataset."],
                recommended_action=RecommendedAction.REQUEST_MERCHANT_FEE_SCHEDULE,
                needs_human_review=True,
                investigator_model="fake-investigator-v1",
            )

        if status == "AMBIGUOUS":
            count = len(evidence.candidate_scores)
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.AMBIGUOUS,
                summary=f"Identified {count} settlement candidates with overlapping timestamps and identical amounts.",
                observed_facts=[f"{count} candidates scored within ambiguity margin."],
                inferences=["Candidates belong to multiple transactions occurring in close succession."],
                uncertainties=["Cannot verify terminal authorization code from source data."],
                recommended_action=RecommendedAction.FLAG_FOR_MANUAL_REVIEW,
                needs_human_review=True,
                investigator_model="fake-investigator-v1",
            )

        if status == "MISSING_SETTLEMENT":
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.LIKELY_MISSING_SETTLEMENT,
                summary="Payment recorded as SUCCESS internally, but no settlement credit was received.",
                observed_facts=["Internal payment succeeded", "Zero matching settlements in batch"],
                inferences=["Settlement may be delayed past standard batch SLA or failed at acquirer."],
                uncertainties=["Acquirer batch receipt status unknown"],
                recommended_action=RecommendedAction.QUERY_GATEWAY_SLA,
                needs_human_review=True,
                investigator_model="fake-investigator-v1",
            )

        if status == "ORPHAN_SETTLEMENT":
            return InvestigationResult(
                case_id=evidence.case_id,
                classification=InvestigationClassification.LIKELY_ORPHAN_SETTLEMENT,
                summary="Settlement credit received from bank with no matching internal payment order.",
                observed_facts=["Bank credit exists", "No internal order found"],
                inferences=["Direct bank transfer or out-of-band payment occurred."],
                uncertainties=["Customer identity unverified"],
                recommended_action=RecommendedAction.ESCALATE_UNALLOCATED_FUNDS,
                needs_human_review=True,
                investigator_model="fake-investigator-v1",
            )

        return InvestigationResult(
            case_id=evidence.case_id,
            classification=InvestigationClassification.INSUFFICIENT_EVIDENCE,
            summary=f"Exception status '{status}' requires manual operator inspection.",
            observed_facts=[f"Status: {status}", f"Reason code: {evidence.reason_code}"],
            inferences=[],
            uncertainties=["Insufficient evidence for automated inference."],
            recommended_action=RecommendedAction.FLAG_FOR_MANUAL_REVIEW,
            needs_human_review=True,
            investigator_model="fake-investigator-v1",
        )