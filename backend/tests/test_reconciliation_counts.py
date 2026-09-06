"""
Regression test for authoritative dataset record count consistency and orphan accounting.
"""

from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Payment, Refund, Settlement
from app.services.ingestion import ingest_all
from app.services.reconciliation import ReconStatus, run_database_reconciliation


@pytest.fixture
def sample_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()

    data_dir = Path("../data/sample")
    if not data_dir.exists():
        data_dir = Path("data/sample")

    ingest_all(data_dir, session)
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_authoritative_reconciliation_counts(sample_db):
    summary = run_database_reconciliation(sample_db)

    # Authoritative physical counts
    assert summary.total_payments == 118
    assert summary.total_settlements == 120
    assert summary.total_refunds == 12

    # Status breakdown
    assert summary.matched == 64
    assert summary.matched_with_tolerance == 6
    assert summary.amount_mismatch == 10
    assert summary.missing_settlement == 8
    assert summary.orphan_settlement == 5  # True orphans only (not ambiguous candidates)
    assert summary.ambiguous == 4
    assert summary.duplicate_settlement == 5
    assert summary.partial_settlement == 5
    assert summary.refunded == 6
    assert summary.partially_refunded == 6
    assert summary.unresolved == 4