"""
Comprehensive test suite for the CSV data ingestion pipeline.
Covers schema validation, row parsing, decimal preservation, atomic rollback,
idempotency, null handling, and ground truth isolation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import Payment, Refund, Settlement
from app.services.ingestion import (
    DuplicateRecordError,
    IngestionError,
    RowValidationError,
    SchemaValidationError,
    ingest_all,
    ingest_payments,
    ingest_refunds,
    ingest_settlements,
)


@pytest.fixture
def db_session() -> Session:
    """Provides a clean in-memory SQLite database session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Test 1: Valid Payment Ingestion
# ---------------------------------------------------------------------------


def test_valid_payment_ingestion(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN001,MER01,CUS01,1500.50,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    result = ingest_payments(csv_file, db_session)
    assert result.inserted == 1
    assert result.status == "SUCCESS"

    db_rec = db_session.query(Payment).filter_by(transaction_id="TXN001").first()
    assert db_rec is not None
    assert db_rec.merchant_id == "MER01"
    assert db_rec.amount == Decimal("1500.50")
    assert db_rec.payment_method == "UPI"


# ---------------------------------------------------------------------------
# Test 2: Valid Settlement Ingestion with Null Transaction ID
# ---------------------------------------------------------------------------


def test_valid_settlement_with_null_transaction_id(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "settlements.csv"
    csv_file.write_text(
        "settlement_id,transaction_id,merchant_id,settled_amount,currency,settlement_status,settlement_timestamp\n"
        "SET001,,MER01,1500.50,INR,SETTLED,2026-08-01T14:00:00+00:00\n",
        encoding="utf-8",
    )

    result = ingest_settlements(csv_file, db_session)
    assert result.inserted == 1

    db_rec = db_session.query(Settlement).filter_by(settlement_id="SET001").first()
    assert db_rec is not None
    assert db_rec.transaction_id is None
    assert db_rec.settled_amount == Decimal("1500.50")


# ---------------------------------------------------------------------------
# Test 3: Valid Refund Ingestion
# ---------------------------------------------------------------------------


def test_valid_refund_ingestion(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "refunds.csv"
    csv_file.write_text(
        "refund_id,transaction_id,refund_amount,refund_status,refund_timestamp\n"
        "REF001,TXN001,500.00,PROCESSED,2026-08-02T10:00:00+00:00\n",
        encoding="utf-8",
    )

    result = ingest_refunds(csv_file, db_session)
    assert result.inserted == 1

    db_rec = db_session.query(Refund).filter_by(refund_id="REF001").first()
    assert db_rec is not None
    assert db_rec.refund_amount == Decimal("500.00")


# ---------------------------------------------------------------------------
# Test 4: Decimal Precision Integrity (No binary float corruption)
# ---------------------------------------------------------------------------


def test_decimal_precision_integrity(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN_DEC,MER01,CUS01,1000.10,INR,SUCCESS,CREDIT_CARD,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    ingest_payments(csv_file, db_session)
    db_rec = db_session.query(Payment).filter_by(transaction_id="TXN_DEC").first()
    assert db_rec is not None
    assert db_rec.amount == Decimal("1000.10")
    assert str(db_rec.amount) == "1000.1000" or str(db_rec.amount) == "1000.10"
    assert isinstance(db_rec.amount, Decimal)


# ---------------------------------------------------------------------------
# Test 5: Missing Required Header Column
# ---------------------------------------------------------------------------


def test_missing_required_column_raises_schema_error(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    # Omit 'amount' column
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN001,MER01,CUS01,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaValidationError) as exc:
        ingest_payments(csv_file, db_session)
    assert "amount" in str(exc.value)


# ---------------------------------------------------------------------------
# Test 6: Invalid Decimal Value
# ---------------------------------------------------------------------------


def test_invalid_decimal_raises_row_validation_error(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN001,MER01,CUS01,INVALID_AMOUNT,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(RowValidationError) as exc:
        ingest_payments(csv_file, db_session)
    assert "row 2" in str(exc.value)
    assert "amount" in str(exc.value)


# ---------------------------------------------------------------------------
# Test 7: Invalid Timestamp Format
# ---------------------------------------------------------------------------


def test_invalid_timestamp_raises_row_validation_error(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN001,MER01,CUS01,100.00,INR,SUCCESS,UPI,not-a-timestamp\n",
        encoding="utf-8",
    )

    with pytest.raises(RowValidationError) as exc:
        ingest_payments(csv_file, db_session)
    assert "row 2" in str(exc.value)
    assert "payment_timestamp" in str(exc.value)


# ---------------------------------------------------------------------------
# Test 8: Nullable Settlement Transaction ID Handling
# ---------------------------------------------------------------------------


def test_empty_string_settlement_transaction_id_becomes_none(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "settlements.csv"
    csv_file.write_text(
        "settlement_id,transaction_id,merchant_id,settled_amount,currency,settlement_status,settlement_timestamp\n"
        "SET_NULL,   ,MER01,100.00,INR,SETTLED,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    ingest_settlements(csv_file, db_session)
    db_rec = db_session.query(Settlement).filter_by(settlement_id="SET_NULL").first()
    assert db_rec is not None
    assert db_rec.transaction_id is None


# ---------------------------------------------------------------------------
# Test 9: In-File Duplicate Identifier Detection
# ---------------------------------------------------------------------------


def test_duplicate_primary_key_in_file_raises_duplicate_error(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN_DUP,MER01,CUS01,100.00,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n"
        "TXN_DUP,MER01,CUS02,200.00,INR,SUCCESS,UPI,2026-08-01T11:00:00+00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(DuplicateRecordError) as exc:
        ingest_payments(csv_file, db_session)
    assert "row 3" in str(exc.value)
    assert "TXN_DUP" in str(exc.value)


# ---------------------------------------------------------------------------
# Test 10: Atomic Rollback on Mid-File Failure
# ---------------------------------------------------------------------------


def test_atomic_rollback_on_failure(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    # Row 2 & 3 valid; Row 4 invalid amount
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN_A,MER01,CUS01,100.00,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n"
        "TXN_B,MER01,CUS02,200.00,INR,SUCCESS,UPI,2026-08-01T11:00:00+00:00\n"
        "TXN_C,MER01,CUS03,BAD_AMOUNT,INR,SUCCESS,UPI,2026-08-01T12:00:00+00:00\n",
        encoding="utf-8",
    )

    with pytest.raises(RowValidationError):
        ingest_payments(csv_file, db_session)

    # Assert that zero rows were persisted
    assert db_session.query(Payment).count() == 0


# ---------------------------------------------------------------------------
# Test 11: Idempotency / Repeat Ingestion Detection
# ---------------------------------------------------------------------------


def test_repeat_ingestion_fails_safely(tmp_path: Path, db_session: Session) -> None:
    csv_file = tmp_path / "payments.csv"
    csv_file.write_text(
        "transaction_id,merchant_id,customer_id,amount,currency,payment_status,payment_method,payment_timestamp\n"
        "TXN_IDEMP,MER01,CUS01,100.00,INR,SUCCESS,UPI,2026-08-01T10:00:00+00:00\n",
        encoding="utf-8",
    )

    # First run succeeds
    result1 = ingest_payments(csv_file, db_session)
    assert result1.inserted == 1

    # Second run detects existing DB record and raises DuplicateRecordError
    with pytest.raises(DuplicateRecordError):
        ingest_payments(csv_file, db_session)


# ---------------------------------------------------------------------------
# Test 12: Ground Truth File Ingestion Exclusion
# ---------------------------------------------------------------------------


def test_ground_truth_file_cannot_be_ingested(tmp_path: Path, db_session: Session) -> None:
    gt_file = tmp_path / "ground_truth.csv"
    gt_file.write_text(
        "transaction_id,scenario,expected_outcome,expected_settlement_id,expected_refund_id,notes\n"
        "TXN001,PERFECT_MATCH,MATCHED,SET001,NONE,Test\n",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError) as exc:
        ingest_payments(gt_file, db_session)
    assert "evaluation dataset" in str(exc.value)