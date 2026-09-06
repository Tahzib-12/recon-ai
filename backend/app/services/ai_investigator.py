"""
ReconAI - AI Investigator Abstraction & Policy.

Defines the abstract interface for AI exception investigation and the
centralized policy determining which reconciliation statuses require investigation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Set

from app.services.investigation_models import EvidencePackage, InvestigationResult
from app.services.reconciliation import ReconStatus


class AIInvestigator(ABC):
    """Abstract interface for all AI investigation providers."""

    @abstractmethod
    def investigate(self, evidence: EvidencePackage) -> InvestigationResult:
        """Analyze the evidence package and produce a structured verdict."""
        pass


class InvestigationPolicy:
    """Centralized policy governing when AI investigation is warranted."""

    INVESTIGATIVE_STATUSES: Set[ReconStatus] = {
        ReconStatus.AMBIGUOUS,
        ReconStatus.AMOUNT_MISMATCH,
        ReconStatus.MISSING_SETTLEMENT,
        ReconStatus.ORPHAN_SETTLEMENT,
        ReconStatus.PARTIAL_SETTLEMENT,
        ReconStatus.UNRESOLVED,
    }

    @classmethod
    def should_investigate(cls, status: ReconStatus) -> bool:
        """Determines if a reconciliation outcome requires AI investigation."""
        return status in cls.INVESTIGATIVE_STATUSES