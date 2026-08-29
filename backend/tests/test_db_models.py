from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import Payment, Refund, Settlement
from collections.abc import Generator

# In-memory SQLite engine isolated for testing
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Fixture providing a fresh in-memory database session for each test."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_insert_payment(db_session: Session) -> None:
    payment = Payment(
        transaction_id="txn_1001",
        merchant_id="merch_55",
        customer_id="cust_99",
        amount=Decimal("150.2500"),
        currency="USD",
        payment_status="SUCCESS",
        payment_method="CREDIT_CARD",
        payment_timestamp=datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(payment)
    db_session.commit()

    saved = db_session.query(Payment).filter_by(transaction_id="txn_1001").first()
    assert saved is not None
    assert saved.merchant_id == "merch_55"
    assert saved.amount == Decimal("150.2500")
    assert isinstance(saved.amount, Decimal)


def test_insert_settlement_with_null_transaction_id(db_session: Session) -> None:
    settlement = Settlement(
        settlement_id="stl_5001",
        transaction_id=None,  # Verifying that nullable is explicitly supported
        merchant_id="merch_55",
        settled_amount=Decimal("148.0000"),
        currency="USD",
        settlement_status="SETTLED",
        settlement_timestamp=datetime(2026, 8, 27, 14, 30, 0, tzinfo=timezone.utc),
    )
    db_session.add(settlement)
    db_session.commit()

    saved = db_session.query(Settlement).filter_by(settlement_id="stl_5001").first()
    assert saved is not None
    assert saved.transaction_id is None
    assert saved.settled_amount == Decimal("148.0000")


def test_insert_refund(db_session: Session) -> None:
    refund = Refund(
        refund_id="ref_9001",
        transaction_id="txn_1001",
        refund_amount=Decimal("50.0000"),
        refund_status="PROCESSED",
        refund_timestamp=datetime(2026, 8, 27, 16, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(refund)
    db_session.commit()

    saved = db_session.query(Refund).filter_by(refund_id="ref_9001").first()
    assert saved is not None
    assert saved.transaction_id == "txn_1001"
    assert saved.refund_amount == Decimal("50.0000")


def test_decimal_precision_preservation(db_session: Session) -> None:
    precise_amount = Decimal("9999999999.1234")
    payment = Payment(
        transaction_id="txn_precision",
        merchant_id="merch_1",
        customer_id="cust_1",
        amount=precise_amount,
        currency="EUR",
        payment_status="SUCCESS",
        payment_method="BANK_TRANSFER",
        payment_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(payment)
    db_session.commit()

    saved = db_session.query(Payment).filter_by(transaction_id="txn_precision").first()
    assert saved is not None
    assert saved.amount == precise_amount