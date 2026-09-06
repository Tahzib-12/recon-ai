"""
ReconAI - Reconciliation Audit Domain Models.

Defines immutable domain structures for append-only audit tracking across
reconciliation, scoring, AI investigation, and human review workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


class AuditEventType(str, Enum):
    """Controlled taxonomy of business audit events."""

    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    CANDIDATES_SCORED = "CANDIDATES_SCORED"
    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    REVIEW_CREATED = "REVIEW_CREATED"
    REVIEW_ASSIGNED = "REVIEW_ASSIGNED"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    SETTLEMENT_SELECTED = "SETTLEMENT_SELECTED"
    CASE_RESOLVED = "CASE_RESOLVED"
    CASE_ESCALATED = "CASE_ESCALATED"


class ActorType(str, Enum):
    """Categorizes the originator of an event."""

    SYSTEM = "SYSTEM"
    AI = "AI"
    HUMAN = "HUMAN"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable business audit event representing an action or state transition."""

    case_id: str
    event_type: AuditEventType
    actor_type: ActorType
    actor_id: str
    description: str
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert event to clean dictionary representation."""
        return {
            "event_id": self.event_id,
            "case_id": self.case_id,
            "event_type": self.event_type.value,
            "actor_type": self.actor_type.value,
            "actor_id": self.actor_id,
            "description": self.description,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }