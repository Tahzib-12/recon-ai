"""
Unit and invariant tests for the AI Exception Investigation Engine.
"""

from datetime import datetime, timezone
from decimal import Decimal
import inspect
import pytest

from app.db.models import Payment, Refund, Settlement
from app.services.ai_investigator import InvestigationPolicy
from app.services.evidence_builder import build_evidence_package
from app.services.fake_investigator import FakeAIInvestigator
from app.services.gemini_investigator import GeminiInvestigator
from app.services.investigation_models import (
    InvestigationClassification,
    RecommendedAction,
)
from app.services.investigation_orchestrator import investigate_exceptions
from app.services.reconciliation import (
    MatchedBy,
    ReasonCode,
    ReconciliationItem,
    ReconciliationSummary,
    ReconStatus,
)

BASE_TIME = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_investigation_policy():
    assert InvestigationPolicy.should_investigate(ReconStatus.MATCHED) is False
    assert InvestigationPolicy.should_investigate(ReconStatus.MATCHED_WITH_TOLERANCE) is False
    assert InvestigationPolicy.should_investigate(ReconStatus.REFUNDED) is False
    assert InvestigationPolicy.should_investigate(ReconStatus.AMBIGUOUS) is True
    assert InvestigationPolicy.should_investigate(ReconStatus.AMOUNT_MISMATCH) is True
    assert InvestigationPolicy.should_investigate(ReconStatus.MISSING_SETTLEMENT) is True
    assert InvestigationPolicy.should_investigate(ReconStatus.ORPHAN_SETTLEMENT) is True


def test_evidence_builder_deterministic_diff():
    item = ReconciliationItem(
        transaction_id="TXN100",
        settlement_id="SET100",
        status=ReconStatus.AMOUNT_MISMATCH,
        reason_code=ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE,
        matched_by=MatchedBy.EXACT_TRANSACTION_ID,
        payment_amount=Decimal("1000.00"),
        settled_amount=Decimal("971.00"),
        difference=Decimal("29.00"),
    )
    p = Payment(
        transaction_id="TXN100",
        merchant_id="MER01",
        customer_id="CUS01",
        amount=Decimal("1000.00"),
        currency="INR",
        payment_status="SUCCESS",
        payment_method="UPI",
        payment_timestamp=BASE_TIME,
    )
    s = Settlement(
        settlement_id="SET100",
        transaction_id="TXN100",
        merchant_id="MER01",
        settled_amount=Decimal("971.00"),
        currency="INR",
        settlement_status="SETTLED",
        settlement_timestamp=BASE_TIME,
    )

    pkg = build_evidence_package(item, [p], [s], [])
    assert pkg.case_id == "TXN100"
    assert pkg.computed_amount_difference == "29.00"
    assert pkg.payment is not None
    assert pkg.payment.amount == "1000.00"
    assert len(pkg.settlements) == 1
    assert pkg.settlements[0].settled_amount == "971.00"


def test_fake_investigator_amount_mismatch():
    investigator = FakeAIInvestigator()
    item = ReconciliationItem(
        transaction_id="TXN100",
        settlement_id="SET100",
        status=ReconStatus.AMOUNT_MISMATCH,
        reason_code=ReasonCode.EXACT_ID_AMOUNT_DIFFERENCE,
        matched_by=MatchedBy.EXACT_TRANSACTION_ID,
        difference=Decimal("29.00"),
    )
    pkg = build_evidence_package(item, [], [], [])
    verdict = investigator.investigate(pkg)

    assert verdict.classification == InvestigationClassification.LIKELY_AMOUNT_DISCREPANCY
    assert verdict.recommended_action == RecommendedAction.REQUEST_MERCHANT_FEE_SCHEDULE
    assert verdict.needs_human_review is True
    assert "29.00" in verdict.summary


def test_investigate_exceptions_filters_by_policy():
    summary = ReconciliationSummary()
    # 1 item that should NOT trigger AI
    summary.record_item(
        ReconciliationItem(
            transaction_id="TXN_MATCHED",
            settlement_id="SET_MATCHED",
            status=ReconStatus.MATCHED,
            reason_code=ReasonCode.EXACT_MATCH,
            matched_by=MatchedBy.EXACT_TRANSACTION_ID,
        )
    )
    # 1 item that SHOULD trigger AI
    summary.record_item(
        ReconciliationItem(
            transaction_id="TXN_AMB",
            settlement_id=None,
            status=ReconStatus.AMBIGUOUS,
            reason_code=ReasonCode.MULTIPLE_CANDIDATES,
            matched_by=MatchedBy.NONE,
        )
    )

    investigator = FakeAIInvestigator()
    verdicts = investigate_exceptions(summary, [], [], [], investigator)

    # Exactly 1 verdict produced
    assert len(verdicts) == 1
    assert verdicts[0].case_id == "TXN_AMB"
    assert verdicts[0].classification == InvestigationClassification.AMBIGUOUS


def test_gemini_fallback_without_api_key():
    investigator = GeminiInvestigator(api_key=None)
    item = ReconciliationItem(
        transaction_id="TXN_TEST",
        settlement_id=None,
        status=ReconStatus.MISSING_SETTLEMENT,
        reason_code=ReasonCode.NO_SETTLEMENT_FOUND,
        matched_by=MatchedBy.NONE,
    )
    pkg = build_evidence_package(item, [], [], [])
    verdict = investigator.investigate(pkg)

    assert verdict.classification == InvestigationClassification.INSUFFICIENT_EVIDENCE
    assert verdict.needs_human_review is True
    assert "disabled" in verdict.investigator_model


def test_ground_truth_isolation_in_investigation():
    from app.services import (
        ai_investigator,
        evidence_builder,
        fake_investigator,
        gemini_investigator,
        investigation_models,
        investigation_orchestrator,
    )

    for mod in [
        ai_investigator,
        evidence_builder,
        fake_investigator,
        gemini_investigator,
        investigation_models,
        investigation_orchestrator,
    ]:
        src = inspect.getsource(mod)
        assert "ground_truth" not in src