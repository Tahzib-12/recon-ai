"""
ReconAI - Synthetic Financial Reconciliation Dataset Generator.

Generates reproducible, realistic payments, settlements, refunds, and an
isolated ground-truth evaluation file representing 13 real-world reconciliation scenarios.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import random
from typing import Optional

# Two decimal places quantizer for currency formatting
CENT = Decimal("0.01")


def quantize_money(amount: Decimal | str | float) -> Decimal:
    """Format and round financial amount to exact 2 decimal places."""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PaymentRecord:
    transaction_id: str
    merchant_id: str
    customer_id: str
    amount: str
    currency: str
    payment_status: str
    payment_method: str
    payment_timestamp: str


@dataclass
class SettlementRecord:
    settlement_id: str
    transaction_id: str  # Empty string if NULL/missing
    merchant_id: str
    settled_amount: str
    currency: str
    settlement_status: str
    settlement_timestamp: str


@dataclass
class RefundRecord:
    refund_id: str
    transaction_id: str
    refund_amount: str
    refund_status: str
    refund_timestamp: str


@dataclass
class GroundTruthRecord:
    transaction_id: str
    scenario: str
    expected_outcome: str
    expected_settlement_id: str
    expected_refund_id: str
    notes: str


@dataclass
class ScenarioDistribution:
    """Configurable scenario count distribution."""
    perfect_match: int = 50
    fee_discrepancy: int = 10
    missing_transaction_id: int = 8
    missing_settlement: int = 8
    orphan_settlement: int = 5
    delayed_settlement: int = 6
    partial_settlement: int = 5
    duplicate_settlement: int = 5
    full_refund: int = 6
    partial_refund: int = 6
    rounding_difference: int = 6
    ambiguous_candidates: int = 4
    unresolved: int = 4


class SyntheticDataGenerator:
    """Generates synthetic reconciliation datasets with reproducible ground truth."""

    def __init__(self, seed: int = 42, distribution: Optional[ScenarioDistribution] = None) -> None:
        self.rng = random.Random(seed)
        self.dist = distribution or ScenarioDistribution()

        # ID sequences
        self._txn_counter = 1
        self._set_counter = 1
        self._ref_counter = 1

        # Base reference date
        self.base_time = datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc)

        # Reference entity pools
        self.merchants = ["MER001", "MER002", "MER003", "MER004", "MER005"]
        self.customers = [f"CUS{i:03d}" for i in range(1, 31)]
        self.payment_methods = ["CREDIT_CARD", "UPI", "DEBIT_CARD", "NET_BANKING"]

        # Output containers
        self.payments: list[PaymentRecord] = []
        self.settlements: list[SettlementRecord] = []
        self.refunds: list[RefundRecord] = []
        self.ground_truth: list[GroundTruthRecord] = []

    def _next_txn_id(self) -> str:
        tid = f"TXN{self._txn_counter:06d}"
        self._txn_counter += 1
        return tid

    def _next_set_id(self) -> str:
        sid = f"SET{self._set_counter:06d}"
        self._set_counter += 1
        return sid

    def _next_ref_id(self) -> str:
        rid = f"REF{self._ref_counter:06d}"
        self._ref_counter += 1
        return rid

    def _random_base_amount(self) -> Decimal:
        """Generate realistic purchase amount between ₹100 and ₹15,000."""
        val = self.rng.choice([
            Decimal(self.rng.randint(100, 1000)),
            Decimal(self.rng.randint(1000, 5000)),
            Decimal(self.rng.randint(5000, 15000)),
        ])
        return quantize_money(val)

    def _random_timestamp(self) -> datetime:
        """Offset randomly within a 7-day period."""
        seconds_offset = self.rng.randint(0, 7 * 86400)
        return self.base_time + timedelta(seconds=seconds_offset)

    # -------------------------------------------------------------------------
    # Scenario Generation Handlers
    # -------------------------------------------------------------------------

    def _gen_perfect_matches(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=self.rng.randint(2, 24))

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method=self.rng.choice(self.payment_methods),
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="PERFECT_MATCH",
                expected_outcome="MATCHED",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes="Exact match on ID, merchant, currency, and amount within standard settlement window.",
            ))

    def _gen_fee_discrepancies(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            gross_amount = quantize_money(self.rng.choice([1000, 2500, 5000, 8000, 10000]))
            # 2.0% to 3.5% MDR processor fee deduction
            fee_pct = Decimal(str(self.rng.choice([0.020, 0.025, 0.029, 0.030])))
            fee_amount = quantize_money(gross_amount * fee_pct)
            net_settled = quantize_money(gross_amount - fee_amount)

            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=self.rng.randint(4, 24))

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(gross_amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="CREDIT_CARD",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(net_settled),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="FEE_DISCREPANCY",
                expected_outcome="AMOUNT_MISMATCH",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes=f"Synthetic MDR fee deduction ({fee_pct * 100}%): ₹{gross_amount} -> ₹{net_settled} (Fee: ₹{fee_amount}).",
            ))

    def _gen_missing_transaction_ids(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=self.rng.randint(1, 12))

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="UPI",
                payment_timestamp=t_pay.isoformat(),
            ))
            # Omit transaction_id in settlement record
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id="",  # Empty string representing NULL
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="MISSING_TRANSACTION_ID",
                expected_outcome="CANDIDATE_MATCH",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes="Settlement has no transaction_id; candidate match must be determined via merchant, amount, and timestamp.",
            ))

    def _gen_missing_settlements(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method=self.rng.choice(self.payment_methods),
                payment_timestamp=t_pay.isoformat(),
            ))
            # No settlement created
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="MISSING_SETTLEMENT",
                expected_outcome="MISSING_SETTLEMENT",
                expected_settlement_id="NONE",
                expected_refund_id="NONE",
                notes="Payment succeeded internally but no settlement record exists in the settlement batch.",
            ))

    def _gen_orphan_settlements(self, count: int) -> None:
        for _ in range(count):
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            amount = self._random_base_amount()
            t_set = self._random_timestamp()

            # Settlement with non-existent or unlinked transaction ID
            orphan_txn_ref = f"TXN_UNKNOWN_{self.rng.randint(900000, 999999)}"

            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=orphan_txn_ref,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=orphan_txn_ref,
                scenario="ORPHAN_SETTLEMENT",
                expected_outcome="ORPHAN_SETTLEMENT",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes="Settlement record received from bank with no corresponding internal payment record.",
            ))

    def _gen_delayed_settlements(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()
            # Delayed settlement: 6 to 14 days later
            delay_days = self.rng.randint(6, 14)
            t_set = t_pay + timedelta(days=delay_days)

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="NET_BANKING",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="DELAYED_SETTLEMENT",
                expected_outcome="DELAYED_SETTLEMENT",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes=f"Settlement arrived {delay_days} days after payment (exceeds standard T+2 window).",
            ))

    def _gen_partial_settlements(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            gross_amount = quantize_money(Decimal("10000.00"))
            settled_amount = quantize_money(Decimal("6000.00"))
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=self.rng.randint(6, 24))

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(gross_amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="BANK_TRANSFER",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(settled_amount),
                currency="INR",
                settlement_status="PARTIALLY_SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="PARTIAL_SETTLEMENT",
                expected_outcome="PARTIAL_SETTLEMENT",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes=f"Partial settlement payout: ₹{settled_amount} of ₹{gross_amount}.",
            ))

    def _gen_duplicate_settlements(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id_1 = self._next_set_id()
            set_id_2 = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()
            t_set_1 = t_pay + timedelta(hours=4)
            t_set_2 = t_pay + timedelta(hours=5)

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="CREDIT_CARD",
                payment_timestamp=t_pay.isoformat(),
            ))
            # Settlement 1
            self.settlements.append(SettlementRecord(
                settlement_id=set_id_1,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set_1.isoformat(),
            ))
            # Duplicate Settlement 2
            self.settlements.append(SettlementRecord(
                settlement_id=set_id_2,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set_2.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="DUPLICATE_SETTLEMENT",
                expected_outcome="DUPLICATE_SETTLEMENT",
                expected_settlement_id=f"{set_id_1},{set_id_2}",
                expected_refund_id="NONE",
                notes="Two distinct settlement records submitted for a single payment transaction.",
            ))

    def _gen_full_refunds(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            ref_id = self._next_ref_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = quantize_money(Decimal(self.rng.choice([2000, 4000, 6000])))
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=12)
            t_ref = t_pay + timedelta(hours=36)

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="REFUNDED",
                payment_method="UPI",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.refunds.append(RefundRecord(
                refund_id=ref_id,
                transaction_id=txn_id,
                refund_amount=str(amount),
                refund_status="PROCESSED",
                refund_timestamp=t_ref.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="FULL_REFUND",
                expected_outcome="FULL_REFUND",
                expected_settlement_id=set_id,
                expected_refund_id=ref_id,
                notes="Full refund completed. Complete lifecycle: PAID -> SETTLED -> FULL_REFUND.",
            ))

    def _gen_partial_refunds(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            ref_id = self._next_ref_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            payment_amount = quantize_money(Decimal("5000.00"))
            refund_amount = quantize_money(Decimal("2000.00"))
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=12)
            t_ref = t_pay + timedelta(hours=24)

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(payment_amount),
                currency="INR",
                payment_status="PARTIALLY_REFUNDED",
                payment_method="CREDIT_CARD",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(payment_amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.refunds.append(RefundRecord(
                refund_id=ref_id,
                transaction_id=txn_id,
                refund_amount=str(refund_amount),
                refund_status="PROCESSED",
                refund_timestamp=t_ref.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="PARTIAL_REFUND",
                expected_outcome="PARTIAL_REFUND",
                expected_settlement_id=set_id,
                expected_refund_id=ref_id,
                notes=f"Partial refund of ₹{refund_amount} on original payment of ₹{payment_amount}.",
            ))

    def _gen_rounding_differences(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id = self._next_set_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            pay_amount = quantize_money(Decimal("1000.00"))
            # 1 paisa (0.01) rounding discrepancy
            diff = self.rng.choice([Decimal("0.01"), Decimal("-0.01")])
            set_amount = quantize_money(pay_amount + diff)
            t_pay = self._random_timestamp()
            t_set = t_pay + timedelta(hours=6)

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(pay_amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="UPI",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id,
                transaction_id=txn_id,
                merchant_id=merchant,
                settled_amount=str(set_amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="ROUNDING_DIFFERENCE",
                expected_outcome="AMOUNT_MISMATCH",
                expected_settlement_id=set_id,
                expected_refund_id="NONE",
                notes=f"Small deterministic rounding difference of ₹{diff} (₹{pay_amount} vs ₹{set_amount}).",
            ))

    def _gen_ambiguous_candidates(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            set_id_a = self._next_set_id()
            set_id_b = self._next_set_id()
            merchant = "MER001"  # Shared merchant
            customer = self.rng.choice(self.customers)
            amount = quantize_money(Decimal("5000.00"))  # Identical amounts
            t_pay = self.base_time + timedelta(hours=10)
            t_set_a = t_pay + timedelta(minutes=4)  # 10:04
            t_set_b = t_pay + timedelta(minutes=6)  # 10:06

            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="SUCCESS",
                payment_method="CREDIT_CARD",
                payment_timestamp=t_pay.isoformat(),
            ))
            # Both settlements lack transaction_ids and have identical amounts/merchants
            self.settlements.append(SettlementRecord(
                settlement_id=set_id_a,
                transaction_id="",
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set_a.isoformat(),
            ))
            self.settlements.append(SettlementRecord(
                settlement_id=set_id_b,
                transaction_id="",
                merchant_id=merchant,
                settled_amount=str(amount),
                currency="INR",
                settlement_status="SETTLED",
                settlement_timestamp=t_set_b.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="AMBIGUOUS_CANDIDATES",
                expected_outcome="AMBIGUOUS",
                expected_settlement_id=f"{set_id_a},{set_id_b}",
                expected_refund_id="NONE",
                notes="Two equally plausible settlements exist with identical merchant/amount and proximate timestamps.",
            ))

    def _gen_unresolved_cases(self, count: int) -> None:
        for _ in range(count):
            txn_id = self._next_txn_id()
            merchant = self.rng.choice(self.merchants)
            customer = self.rng.choice(self.customers)
            amount = self._random_base_amount()
            t_pay = self._random_timestamp()

            # Payment marked with inconclusive gateway status
            self.payments.append(PaymentRecord(
                transaction_id=txn_id,
                merchant_id=merchant,
                customer_id=customer,
                amount=str(amount),
                currency="INR",
                payment_status="PENDING_GATEWAY_RESPONSE",
                payment_method="NET_BANKING",
                payment_timestamp=t_pay.isoformat(),
            ))
            self.ground_truth.append(GroundTruthRecord(
                transaction_id=txn_id,
                scenario="UNRESOLVED",
                expected_outcome="UNRESOLVED",
                expected_settlement_id="NONE",
                expected_refund_id="NONE",
                notes="Insufficient terminal status and no matching settlement records exist.",
            ))

    # -------------------------------------------------------------------------
    # Dataset Generation Entry Point
    # -------------------------------------------------------------------------

    def generate(self) -> tuple[list[PaymentRecord], list[SettlementRecord], list[RefundRecord], list[GroundTruthRecord]]:
        """Run all generation routines in deterministic order."""
        self._gen_perfect_matches(self.dist.perfect_match)
        self._gen_fee_discrepancies(self.dist.fee_discrepancy)
        self._gen_missing_transaction_ids(self.dist.missing_transaction_id)
        self._gen_missing_settlements(self.dist.missing_settlement)
        self._gen_orphan_settlements(self.dist.orphan_settlement)
        self._gen_delayed_settlements(self.dist.delayed_settlement)
        self._gen_partial_settlements(self.dist.partial_settlement)
        self._gen_duplicate_settlements(self.dist.duplicate_settlement)
        self._gen_full_refunds(self.dist.full_refund)
        self._gen_partial_refunds(self.dist.partial_refund)
        self._gen_rounding_differences(self.dist.rounding_difference)
        self._gen_ambiguous_candidates(self.dist.ambiguous_candidates)
        self._gen_unresolved_cases(self.dist.unresolved)

        return self.payments, self.settlements, self.refunds, self.ground_truth

    def export_to_csv(self, output_dir: Path) -> dict[str, int]:
        """Generate and save all CSV artifacts to the target directory."""
        output_dir.mkdir(parents=True, exist_ok=True)

        payments, settlements, refunds, ground_truth = self.generate()

        def write_csv(filepath: Path, records: list) -> None:
            if not records:
                return
            with open(filepath, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=asdict(records[0]).keys())
                writer.writeheader()
                for r in records:
                    writer.writerow(asdict(r))

        write_csv(output_dir / "payments.csv", payments)
        write_csv(output_dir / "settlements.csv", settlements)
        write_csv(output_dir / "refunds.csv", refunds)
        write_csv(output_dir / "ground_truth.csv", ground_truth)

        # Count scenarios for summary
        scenario_counts: dict[str, int] = {}
        for gt in ground_truth:
            scenario_counts[gt.scenario] = scenario_counts.get(gt.scenario, 0) + 1

        return {
            "payments": len(payments),
            "settlements": len(settlements),
            "refunds": len(refunds),
            "ground_truth": len(ground_truth),
            **scenario_counts,
        }


def main() -> None:
    # Resolve default output directory: data/sample/
    project_root = Path(__file__).resolve().parent
    output_dir = project_root / "sample"

    generator = SyntheticDataGenerator(seed=42)
    stats = generator.export_to_csv(output_dir)

    print("==================================================")
    print("ReconAI Synthetic Dataset Generated Successfully")
    print("==================================================")
    print(f"Output Directory: {output_dir.resolve()}\n")
    print(f"Payments:      {stats['payments']}")
    print(f"Settlements:   {stats['settlements']}")
    print(f"Refunds:       {stats['refunds']}")
    print(f"Ground Truth:  {stats['ground_truth']}\n")
    print("Scenario Breakdown:")
    print("--------------------------------------------------")
    for key, val in stats.items():
        if key not in ["payments", "settlements", "refunds", "ground_truth"]:
            print(f"{key:<26} {val:>4}")
    print("==================================================")


if __name__ == "__main__":
    main()