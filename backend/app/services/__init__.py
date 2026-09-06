"""Application business logic and operational service modules."""

from app.services.ingestion import (
    DuplicateRecordError,
    IngestionError,
    IngestionResult,
    IngestionSummary,
    RowValidationError,
    SchemaValidationError,
    ingest_all,
    ingest_payments,
    ingest_refunds,
    ingest_settlements,
)

__all__ = [
    "DuplicateRecordError",
    "IngestionError",
    "IngestionResult",
    "IngestionSummary",
    "RowValidationError",
    "SchemaValidationError",
    "ingest_all",
    "ingest_payments",
    "ingest_refunds",
    "ingest_settlements",
    "MatchedBy",
    "ReasonCode",
    "ReconciliationConfig",
    "ReconciliationItem",
    "ReconciliationSummary",
    "ReconStatus",
    "reconcile_records",
    "run_database_reconciliation",
    "CandidateScoringConfig",
    "ScoringWeights",
    "CandidateScore",
    "ScoreBreakdown",
    "ScoringDecision",
    "evaluate_candidates",
    "score_candidate",
    "AIInvestigator",
    "InvestigationPolicy",
    "build_evidence_package",
    "FakeAIInvestigator",
    "GeminiInvestigator",
    "CandidateEvidence",
    "EvidencePackage",
    "InvestigationClassification",
    "InvestigationResult",
    "PaymentEvidence",
    "RecommendedAction",
    "RefundEvidence",
    "SettlementEvidence",
    "investigate_exceptions",
]


def __getattr__(name: str):
    if name in {
        "MatchedBy",
        "ReasonCode",
        "ReconciliationConfig",
        "ReconciliationItem",
        "ReconciliationSummary",
        "ReconStatus",
        "reconcile_records",
        "run_database_reconciliation",
    }:
        from app.services import reconciliation

        return getattr(reconciliation, name)
    if name in {
        "CandidateScoringConfig",
        "ScoringWeights",
        "CandidateScore",
        "ScoreBreakdown",
        "ScoringDecision",
        "evaluate_candidates",
        "score_candidate",
    }:
        from app.services import scoring

        return getattr(scoring, name)
    if name in {
        "CandidateEvidence",
        "EvidencePackage",
        "InvestigationClassification",
        "InvestigationResult",
        "PaymentEvidence",
        "RecommendedAction",
        "RefundEvidence",
        "SettlementEvidence",
    }:
        from app.services import investigation_models

        return getattr(investigation_models, name)
    if name in {"AIInvestigator", "InvestigationPolicy"}:
        from app.services import ai_investigator

        return getattr(ai_investigator, name)
    if name == "build_evidence_package":
        from app.services import evidence_builder

        return getattr(evidence_builder, name)
    if name == "FakeAIInvestigator":
        from app.services import fake_investigator

        return getattr(fake_investigator, name)
    if name == "GeminiInvestigator":
        from app.services import gemini_investigator

        return getattr(gemini_investigator, name)
    if name == "investigate_exceptions":
        from app.services import investigation_orchestrator

        return getattr(investigation_orchestrator, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")