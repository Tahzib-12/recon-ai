"""
Tests for the synthetic reconciliation dataset generator.
Verifies reproducibility, scenario integrity, decimal precision, and data invariants.
"""

from decimal import Decimal
from pathlib import Path
import pytest

from data.generate_dataset import (
    CENT,
    quantize_money,
    ScenarioDistribution,
    SyntheticDataGenerator,
)


@pytest.fixture
def generator_output():
    """Generates a default dataset in memory for test assertions."""
    gen = SyntheticDataGenerator(seed=42)
    payments, settlements, refunds, ground_truth = gen.generate()
    return {
        "payments": payments,
        "settlements": settlements,
        "refunds": refunds,
        "ground_truth": ground_truth,
    }


def test_reproducibility():
    """Verify that identical seeds produce identical byte-for-byte outputs."""
    gen1 = SyntheticDataGenerator(seed=42)
    p1, s1, r1, g1 = gen1.generate()

    gen2 = SyntheticDataGenerator(seed=42)
    p2, s2, r2, g2 = gen2.generate()

    assert p1 == p2
    assert s1 == s2
    assert r1 == r2
    assert g1 == g2


def test_different_seeds_produce_different_data():
    """Verify that different seeds alter generated values."""
    gen1 = SyntheticDataGenerator(seed=42)
    p1, _, _, _ = gen1.generate()

    gen2 = SyntheticDataGenerator(seed=999)
    p2, _, _, _ = gen2.generate()

    assert p1 != p2


def test_all_scenarios_represented(generator_output):
    """Verify that every required scenario is present in ground truth."""
    gt_records = generator_output["ground_truth"]
    scenarios_present = {r.scenario for r in gt_records}

    expected_scenarios = {
        "PERFECT_MATCH",
        "FEE_DISCREPANCY",
        "MISSING_TRANSACTION_ID",
        "MISSING_SETTLEMENT",
        "ORPHAN_SETTLEMENT",
        "DELAYED_SETTLEMENT",
        "PARTIAL_SETTLEMENT",
        "DUPLICATE_SETTLEMENT",
        "FULL_REFUND",
        "PARTIAL_REFUND",
        "ROUNDING_DIFFERENCE",
        "AMBIGUOUS_CANDIDATES",
        "UNRESOLVED",
    }

    assert scenarios_present == expected_scenarios


def test_unique_identifiers(generator_output):
    """Verify primary key uniqueness across generated records."""
    payments = generator_output["payments"]
    settlements = generator_output["settlements"]
    refunds = generator_output["refunds"]

    payment_ids = [p.transaction_id for p in payments]
    settlement_ids = [s.settlement_id for s in settlements]
    refund_ids = [r.refund_id for r in refunds]

    assert len(payment_ids) == len(set(payment_ids)), "Duplicate payment transaction_id found"
    assert len(settlement_ids) == len(set(settlement_ids)), "Duplicate settlement_id found"
    assert len(refund_ids) == len(set(refund_ids)), "Duplicate refund_id found"


def test_monetary_formatting(generator_output):
    """Verify all currency amounts are valid strings with exactly 2 decimal places."""
    for p in generator_output["payments"]:
        dec = Decimal(p.amount)
        assert p.amount == str(dec.quantize(CENT))

    for s in generator_output["settlements"]:
        dec = Decimal(s.settled_amount)
        assert s.settled_amount == str(dec.quantize(CENT))

    for r in generator_output["refunds"]:
        dec = Decimal(r.refund_amount)
        assert r.refund_amount == str(dec.quantize(CENT))


def test_missing_transaction_id_is_empty(generator_output):
    """Verify settlements in MISSING_TRANSACTION_ID scenario have empty transaction_ids."""
    gt_missing_tx = [r for r in generator_output["ground_truth"] if r.scenario == "MISSING_TRANSACTION_ID"]
    assert len(gt_missing_tx) > 0

    settlement_map = {s.settlement_id: s for s in generator_output["settlements"]}
    for gt in gt_missing_tx:
        settlement = settlement_map[gt.expected_settlement_id]
        assert settlement.transaction_id == ""


def test_missing_settlement_has_no_settlement_record(generator_output):
    """Verify MISSING_SETTLEMENT payments truly have no settlement record."""
    gt_missing_set = [r for r in generator_output["ground_truth"] if r.scenario == "MISSING_SETTLEMENT"]
    assert len(gt_missing_set) > 0

    existing_set_txns = {s.transaction_id for s in generator_output["settlements"] if s.transaction_id}
    for gt in gt_missing_set:
        assert gt.expected_settlement_id == "NONE"
        assert gt.transaction_id not in existing_set_txns


def test_orphan_settlement_has_no_payment_record(generator_output):
    """Verify ORPHAN_SETTLEMENT records have no matching payment."""
    gt_orphans = [r for r in generator_output["ground_truth"] if r.scenario == "ORPHAN_SETTLEMENT"]
    assert len(gt_orphans) > 0

    existing_pay_txns = {p.transaction_id for p in generator_output["payments"]}
    for gt in gt_orphans:
        assert gt.transaction_id not in existing_pay_txns


def test_duplicate_settlement_references_same_payment(generator_output):
    """Verify DUPLICATE_SETTLEMENT generates multiple settlements for one transaction_id."""
    gt_dupes = [r for r in generator_output["ground_truth"] if r.scenario == "DUPLICATE_SETTLEMENT"]
    assert len(gt_dupes) > 0

    settlements = generator_output["settlements"]
    for gt in gt_dupes:
        matching_sets = [s for s in settlements if s.transaction_id == gt.transaction_id]
        assert len(matching_sets) == 2


def test_refund_references_valid_payment(generator_output):
    """Verify all refund records reference existing payments."""
    payments_map = {p.transaction_id: p for p in generator_output["payments"]}
    for refund in generator_output["refunds"]:
        assert refund.transaction_id in payments_map


def test_csv_export(tmp_path: Path):
    """Verify complete CSV export writes expected headers and non-empty files."""
    gen = SyntheticDataGenerator(seed=42)
    stats = gen.export_to_csv(tmp_path)

    assert (tmp_path / "payments.csv").exists()
    assert (tmp_path / "settlements.csv").exists()
    assert (tmp_path / "refunds.csv").exists()
    assert (tmp_path / "ground_truth.csv").exists()

    assert stats["payments"] > 0
    assert stats["settlements"] > 0
    assert stats["ground_truth"] > 0