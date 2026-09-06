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
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")