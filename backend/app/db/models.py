from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Payment(Base):
    """
    Source model for internal payment records (e.g., recorded by checkout service).
    """

    __tablename__ = "payments"

    # Domain natural key: transaction_id
    transaction_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        index=True,
        doc="Unique transaction identifier from the internal payment gateway or order system.",
    )
    merchant_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Identifier of the merchant receiving the payment.",
    )
    customer_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Identifier of the customer making the payment.",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        doc="Gross payment amount in fixed-point decimal.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        doc="ISO 4217 3-letter currency code (e.g., USD, EUR, INR).",
    )
    payment_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Status of the payment (e.g., SUCCESS, FAILED, PENDING).",
    )
    payment_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Payment channel or instrument (e.g., CREDIT_CARD, UPI, BANK_TRANSFER).",
    )
    payment_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="UTC timestamp when the payment occurred.",
    )


class Settlement(Base):
    """
    Source model for external settlement reports (e.g., received from acquiring banks or Stripe).
    """

    __tablename__ = "settlements"

    settlement_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        index=True,
        doc="Unique identifier assigned by the payment processor or bank in settlement batch files.",
    )
    # MUST be nullable: Banking/processor reports may lack internal transaction_ids or arrive as bulk payouts
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Internal transaction ID if provided by the processor. Nullable when omitted by bank/batch.",
    )
    merchant_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Merchant identifier assigned by processor.",
    )
    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        doc="Net or gross amount credited/settled by the bank/processor.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        doc="ISO 4217 3-letter currency code.",
    )
    settlement_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Status of settlement (e.g., SETTLED, PENDING, REVERSED).",
    )
    settlement_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="UTC timestamp when funds were settled.",
    )


class Refund(Base):
    """
    Source model for refund/reversal records.
    """

    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        index=True,
        doc="Unique identifier for the refund event.",
    )
    transaction_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Associated payment transaction ID being refunded.",
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        doc="Amount refunded in fixed-point decimal.",
    )
    refund_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Status of the refund (e.g., PROCESSED, FAILED, PENDING).",
    )
    refund_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="UTC timestamp when the refund was initiated/completed.",
    )


# Indexes for multi-column candidate lookup efficiency during reconciliation
Index("ix_payments_recon_lookup", Payment.merchant_id, Payment.currency, Payment.amount)
Index("ix_settlements_recon_lookup", Settlement.merchant_id, Settlement.currency, Settlement.settled_amount)