"""
ReconAI - Audit Logging Service.

Provides an append-only interface to record, persist, and retrieve structured
business audit events across the lifecycle of a reconciliation case.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Optional, Sequence
import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditEventRecord
from app.services.audit_models import ActorType, AuditEvent, AuditEventType

# Keys forbidden from audit metadata to prevent credential leakage
FORBIDDEN_METADATA_KEYS = {"api_key", "gemini_api_key", "password", "token", "secret"}


class AuditService:
    """Service for append-only audit event recording and history retrieval."""

    @staticmethod
    def _sanitize_metadata(metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Strip sensitive credentials and serialize Decimal/datetimes safely."""
        if not metadata:
            return {}

        clean: dict[str, Any] = {}
        for k, v in metadata.items():
            if k.lower() in FORBIDDEN_METADATA_KEYS:
                clean[k] = "[REDACTED]"
            elif isinstance(v, (datetime,)):
                clean[k] = v.isoformat()
            else:
                clean[k] = str(v) if not isinstance(v, (int, float, bool, list, dict)) else v

        return clean

    @classmethod
    def record_event(
        cls,
        case_id: str,
        event_type: AuditEventType,
        actor_type: ActorType,
        actor_id: str,
        description: str,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        session: Optional[Session] = None,
    ) -> AuditEvent:
        """
        Record a business audit event.
        Persists to the database if session is provided. Never mutates previous rows.
        """
        if not case_id or not case_id.strip():
            raise ValueError("Audit event requires a valid case_id.")

        clean_meta = cls._sanitize_metadata(metadata)
        event = AuditEvent(
            case_id=case_id.strip(),
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id.strip(),
            description=description.strip(),
            previous_state=previous_state,
            new_state=new_state,
            metadata=clean_meta,
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
        )

        if session:
            record = AuditEventRecord(
                event_id=event.event_id,
                case_id=event.case_id,
                event_type=event.event_type.value,
                actor_type=event.actor_type.value,
                actor_id=event.actor_id,
                description=event.description,
                previous_state=event.previous_state,
                new_state=event.new_state,
                metadata_json=json.dumps(event.metadata),
                timestamp=event.timestamp,
            )
            session.add(record)
            session.commit()

        return event

    @classmethod
    def get_case_history(
        cls,
        case_id: str,
        session: Session,
    ) -> list[AuditEvent]:
        """
        Retrieve complete audit history for a case, strictly ordered chronologically
        (timestamp ASC, event_id ASC).
        """
        records = (
            session.query(AuditEventRecord)
            .filter_by(case_id=case_id.strip())
            .order_by(AuditEventRecord.timestamp.asc(), AuditEventRecord.event_id.asc())
            .all()
        )

        events: list[AuditEvent] = []
        for r in records:
            meta = {}
            if r.metadata_json:
                try:
                    meta = json.loads(r.metadata_json)
                except Exception:
                    meta = {}

            events.append(
                AuditEvent(
                    case_id=r.case_id,
                    event_type=AuditEventType(r.event_type),
                    actor_type=ActorType(r.actor_type),
                    actor_id=r.actor_id,
                    description=r.description,
                    previous_state=r.previous_state,
                    new_state=r.new_state,
                    metadata=meta,
                    event_id=r.event_id,
                    timestamp=r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc),
                )
            )

        return events