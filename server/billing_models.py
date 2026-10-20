"""Persisted workspace entitlements and immutable bank transfer orders."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Subscription(Base):
    __tablename__ = 'subscriptions'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    trial_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentOrder(Base):
    __tablename__ = 'payment_orders'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    transfer_code: Mapped[str] = mapped_column(String(32), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    bank: Mapped[str] = mapped_column(String(100))
    account_number: Mapped[str] = mapped_column(String(100))
    account_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentReceipt(Base):
    __tablename__ = 'payment_receipts'
    transaction_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('payment_orders.id'), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(200))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(40))
