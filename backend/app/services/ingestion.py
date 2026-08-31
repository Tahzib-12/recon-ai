"""
Data ingestion pipeline service for ReconAI.

Reads, validates, parses, and safely persists payment, settlement, and refund
CSV records into the application database with atomic transaction safety.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar
import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import Base, SessionLocal, engine
from app.db.models import Payment, Refund, Settlement

# ---------------------------------------------------------------------------
# Custom Ingestion Exceptions
# ---------------------------------------------------------------------------


class IngestionError(Exception):
    """Base exception for all ingestion pipeline errors."""

    pass


class SchemaValidationError(IngestionError):
    """Raised when CSV header structure is missing required columns."""

    def __init__(self, filename: str, missing_columns: Iterable[str]) -> None:
        self.filename = filename
        self.missing_columns = list(missing_columns)
        super().__init__(
            f"{filename}: missing required column(s): {', '.join(self.missing_columns)}"
        )


class RowValidationError(IngestionError):
    """Raised when an individual row contains malformed, missing, or unparseable data."""

    def __init__(
        self, filename: str, row_number: int, column: str, value: str, message: str
    ) -> None:
        self.filename = filename
        self.row_number = row_number
        self.column = column
        self.value = value
        super().__init__(
            f"{filename} row {row_number}: column '{column}' with value '{value}' failed validation - {message}"
        )


class DuplicateRecordError(IngestionError):
    """Raised when duplicate primary/domain keys are encountered during ingestion."""

    def __init__(self, filename: str, row_number: int, key_name: str, key_value: str) -> None:
        self.filename = filename
        self.row_number = row_number
        self.key_name = key_name
        self.key_value = key_value
        super().__init__(
            f"{filename} row {row_number}: duplicate {key_name} '{key_value}' detected. Ingestion aborted to prevent corruption."
        )


# ---------------------------------------------------------------------------
# Ingestion Summary Data Structures
# ---------------------------------------------------------------------------


@dataclass
class IngestionResult:
    """Summary metrics for an individual file ingestion operation."""

    source_file: str
    total_rows: int = 0
    inserted: int = 0
    failed: int = 0
    status: str = "SUCCESS"
    error_message: Optional[str] = None


@dataclass
class IngestionSummary:
    """Consolidated summary for multi-file ingestion batches."""

    payments: IngestionResult = field(default_factory=lambda: IngestionResult("payments.csv"))
    settlements: IngestionResult = field(default_factory=lambda: IngestionResult("settlements.csv"))
    refunds: IngestionResult = field(default_factory=lambda: IngestionResult("refunds.csv"))

    @property
    def total_inserted(self) -> int:
        return self.payments.inserted + self.settlements.inserted + self.refunds.inserted

    @property
    def has_failures(self) -> bool:
        return (
            self.payments.failed > 0
            or self.settlements.failed > 0
            or self.refunds.failed > 0
        )


# ---------------------------------------------------------------------------
# Type Parsers and Row Validators
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=Base)


def _parse_decimal(filename: str, row_idx: int, col_name: str, raw_val: str) -> Decimal:
    """Parse string value into Decimal without passing through binary float."""
    cleaned = raw_val.strip()
    if not cleaned:
        raise RowValidationError(filename, row_idx, col_name, raw_val, "Monetary amount cannot be empty")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise RowValidationError(filename, row_idx, col_name, raw_val, "Value is not a valid decimal number")


def _parse_datetime(filename: str, row_idx: int, col_name: str, raw_val: str) -> datetime:
    """Parse ISO-8601 timestamp string into timezone-aware datetime."""
    cleaned = raw_val.strip()
    if not cleaned:
        raise RowValidationError(filename, row_idx, col_name, raw_val, "Timestamp cannot be empty")
    try:
        dt = datetime.fromisoformat(cleaned)
        # Normalize naive datetimes to UTC if necessary
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        raise RowValidationError(filename, row_idx, col_name, raw_val, "Invalid ISO-8601 timestamp format")


def _parse_required_string(filename: str, row_idx: int, col_name: str, raw_val: str) -> str:
    """Ensure non-nullable string fields are not blank."""
    cleaned = raw_val.strip()
    if not cleaned:
        raise RowValidationError(filename, row_idx, col_name, raw_val, "Required string field cannot be empty")
    return cleaned


def _parse_nullable_string(raw_val: Optional[str]) -> Optional[str]:
    """Convert empty or whitespace-only strings to None."""
    if raw_val is None:
        return None
    cleaned = raw_val.strip()
    return cleaned if cleaned else None


# ---------------------------------------------------------------------------
# Core Ingestion Logic
# ---------------------------------------------------------------------------


def _validate_headers(filename: str, actual_headers: list[str], required_headers: set[str]) -> None:
    """Verify that all required columns are present in the CSV header."""
    actual_set = set(actual_headers)
    missing = required_headers - actual_set
    if missing:
        raise SchemaValidationError(filename, missing)


def ingest_payments(csv_path: Path, session: Session) -> IngestionResult:
    """
    Ingest payments CSV file into the database.

    Atomic: entire file succeeds or rolls back.
    """
    filename = csv_path.name
    if filename == "ground_truth.csv":
        raise IngestionError("ground_truth.csv is an evaluation dataset and cannot be ingested into source tables.")

    required_cols = {
        "transaction_id",
        "merchant_id",
        "customer_id",
        "amount",
        "currency",
        "payment_status",
        "payment_method",
        "payment_timestamp",
    }

    if not csv_path.exists():
        raise IngestionError(f"File not found: {csv_path}")

    records_to_insert: list[Payment] = []
    seen_ids: set[str] = set()

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SchemaValidationError(filename, required_cols)

        _validate_headers(filename, reader.fieldnames, required_cols)

        for row_idx, row in enumerate(reader, start=2):  # row 1 is header
            tx_id = _parse_required_string(filename, row_idx, "transaction_id", row.get("transaction_id", ""))

            # In-file duplicate check
            if tx_id in seen_ids:
                raise DuplicateRecordError(filename, row_idx, "transaction_id", tx_id)
            seen_ids.add(tx_id)

            # Idempotency / DB duplicate check
            if session.query(Payment.transaction_id).filter_by(transaction_id=tx_id).first():
                raise DuplicateRecordError(filename, row_idx, "transaction_id (already exists in DB)", tx_id)

            record = Payment(
                transaction_id=tx_id,
                merchant_id=_parse_required_string(filename, row_idx, "merchant_id", row.get("merchant_id", "")),
                customer_id=_parse_required_string(filename, row_idx, "customer_id", row.get("customer_id", "")),
                amount=_parse_decimal(filename, row_idx, "amount", row.get("amount", "")),
                currency=_parse_required_string(filename, row_idx, "currency", row.get("currency", "")),
                payment_status=_parse_required_string(filename, row_idx, "payment_status", row.get("payment_status", "")),
                payment_method=_parse_required_string(filename, row_idx, "payment_method", row.get("payment_method", "")),
                payment_timestamp=_parse_datetime(filename, row_idx, "payment_timestamp", row.get("payment_timestamp", "")),
            )
            records_to_insert.append(record)

    # Persist atomically
    session.add_all(records_to_insert)
    session.commit()

    return IngestionResult(
        source_file=filename,
        total_rows=len(records_to_insert),
        inserted=len(records_to_insert),
        failed=0,
        status="SUCCESS",
    )


def ingest_settlements(csv_path: Path, session: Session) -> IngestionResult:
    """
    Ingest settlements CSV file into the database.

    Allows transaction_id to be NULL/empty. Atomic execution.
    """
    filename = csv_path.name
    if filename == "ground_truth.csv":
        raise IngestionError("ground_truth.csv is an evaluation dataset and cannot be ingested into source tables.")

    required_cols = {
        "settlement_id",
        "transaction_id",
        "merchant_id",
        "settled_amount",
        "currency",
        "settlement_status",
        "settlement_timestamp",
    }

    if not csv_path.exists():
        raise IngestionError(f"File not found: {csv_path}")

    records_to_insert: list[Settlement] = []
    seen_ids: set[str] = set()

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SchemaValidationError(filename, required_cols)

        _validate_headers(filename, reader.fieldnames, required_cols)

        for row_idx, row in enumerate(reader, start=2):
            set_id = _parse_required_string(filename, row_idx, "settlement_id", row.get("settlement_id", ""))

            if set_id in seen_ids:
                raise DuplicateRecordError(filename, row_idx, "settlement_id", set_id)
            seen_ids.add(set_id)

            if session.query(Settlement.settlement_id).filter_by(settlement_id=set_id).first():
                raise DuplicateRecordError(filename, row_idx, "settlement_id (already exists in DB)", set_id)

            # transaction_id is explicitly allowed to be None
            tx_id = _parse_nullable_string(row.get("transaction_id"))

            record = Settlement(
                settlement_id=set_id,
                transaction_id=tx_id,
                merchant_id=_parse_required_string(filename, row_idx, "merchant_id", row.get("merchant_id", "")),
                settled_amount=_parse_decimal(filename, row_idx, "settled_amount", row.get("settled_amount", "")),
                currency=_parse_required_string(filename, row_idx, "currency", row.get("currency", "")),
                settlement_status=_parse_required_string(filename, row_idx, "settlement_status", row.get("settlement_status", "")),
                settlement_timestamp=_parse_datetime(filename, row_idx, "settlement_timestamp", row.get("settlement_timestamp", "")),
            )
            records_to_insert.append(record)

    session.add_all(records_to_insert)
    session.commit()

    return IngestionResult(
        source_file=filename,
        total_rows=len(records_to_insert),
        inserted=len(records_to_insert),
        failed=0,
        status="SUCCESS",
    )


def ingest_refunds(csv_path: Path, session: Session) -> IngestionResult:
    """
    Ingest refunds CSV file into the database.

    Atomic execution.
    """
    filename = csv_path.name
    if filename == "ground_truth.csv":
        raise IngestionError("ground_truth.csv is an evaluation dataset and cannot be ingested into source tables.")

    required_cols = {
        "refund_id",
        "transaction_id",
        "refund_amount",
        "refund_status",
        "refund_timestamp",
    }

    if not csv_path.exists():
        raise IngestionError(f"File not found: {csv_path}")

    records_to_insert: list[Refund] = []
    seen_ids: set[str] = set()

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SchemaValidationError(filename, required_cols)

        _validate_headers(filename, reader.fieldnames, required_cols)

        for row_idx, row in enumerate(reader, start=2):
            ref_id = _parse_required_string(filename, row_idx, "refund_id", row.get("refund_id", ""))

            if ref_id in seen_ids:
                raise DuplicateRecordError(filename, row_idx, "refund_id", ref_id)
            seen_ids.add(ref_id)

            if session.query(Refund.refund_id).filter_by(refund_id=ref_id).first():
                raise DuplicateRecordError(filename, row_idx, "refund_id (already exists in DB)", ref_id)

            record = Refund(
                refund_id=ref_id,
                transaction_id=_parse_required_string(filename, row_idx, "transaction_id", row.get("transaction_id", "")),
                refund_amount=_parse_decimal(filename, row_idx, "refund_amount", row.get("refund_amount", "")),
                refund_status=_parse_required_string(filename, row_idx, "refund_status", row.get("refund_status", "")),
                refund_timestamp=_parse_datetime(filename, row_idx, "refund_timestamp", row.get("refund_timestamp", "")),
            )
            records_to_insert.append(record)

    session.add_all(records_to_insert)
    session.commit()

    return IngestionResult(
        source_file=filename,
        total_rows=len(records_to_insert),
        inserted=len(records_to_insert),
        failed=0,
        status="SUCCESS",
    )


def ingest_all(data_directory: Path, session: Session) -> IngestionSummary:
    """
    Convenience orchestrator to ingest payments, settlements, and refunds
    from a data directory. Each file executes in its own atomic transaction.
    """
    summary = IngestionSummary()

    # Ingest Payments
    payments_file = data_directory / "payments.csv"
    if payments_file.exists():
        try:
            summary.payments = ingest_payments(payments_file, session)
        except Exception as e:
            session.rollback()
            summary.payments.status = "FAILED"
            summary.payments.failed = 1
            summary.payments.error_message = str(e)
            raise

    # Ingest Settlements
    settlements_file = data_directory / "settlements.csv"
    if settlements_file.exists():
        try:
            summary.settlements = ingest_settlements(settlements_file, session)
        except Exception as e:
            session.rollback()
            summary.settlements.status = "FAILED"
            summary.settlements.failed = 1
            summary.settlements.error_message = str(e)
            raise

    # Ingest Refunds
    refunds_file = data_directory / "refunds.csv"
    if refunds_file.exists():
        try:
            summary.refunds = ingest_refunds(refunds_file, session)
        except Exception as e:
            session.rollback()
            summary.refunds.status = "FAILED"
            summary.refunds.failed = 1
            summary.refunds.error_message = str(e)
            raise

    return summary


# ---------------------------------------------------------------------------
# CLI Execution Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI runner to ingest sample data files into the database."""
    # Ensure database schema is created
    Base.metadata.create_all(bind=engine)

    data_dir = Path("data/sample")
    if not data_dir.exists():
        # Fallback relative to backend/ directory if run from there
        data_dir = Path("../data/sample")

    if not data_dir.exists():
        print(f"Error: Sample data directory not found at '{data_dir}'. Generate dataset first.", file=sys.stderr)
        sys.exit(1)

    print("==================================================")
    print(f"Starting ReconAI Data Ingestion from {data_dir.resolve()}")
    print("==================================================")

    session = SessionLocal()
    try:
        summary = ingest_all(data_dir, session)
        print(f"\n[OK] Ingestion completed successfully.")
        print(f"Payments:    {summary.payments.inserted:>5} inserted")
        print(f"Settlements: {summary.settlements.inserted:>5} inserted")
        print(f"Refunds:     {summary.refunds.inserted:>5} inserted")
        print(f"Total:       {summary.total_inserted:>5} records persisted.")
        print("==================================================")
    except IngestionError as err:
        print(f"\n[ERROR] Ingestion Failed: {err}", file=sys.stderr)
        print("Transaction rolled back. Database remains consistent.", file=sys.stderr)
        print("==================================================", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()