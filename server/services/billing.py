"""Calendar-month subscriptions; SePay configuration never leaves the server."""
import calendar
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from ..billing_models import Subscription
from ..models import Workspace, utcnow

BUSINESS_ZONE = ZoneInfo('Asia/Ho_Chi_Minh')


def add_month(value: datetime) -> datetime:
    local = value.astimezone(BUSINESS_ZONE)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.replace(year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1])).astimezone(timezone.utc)


def initialize_subscription(db: Session, workspace_id: str, now: datetime | None = None):
    now = now or utcnow()
    db.execute(insert(Subscription).values(workspace_id=workspace_id, trial_started_at=now,
               trial_ends_at=add_month(now)).on_conflict_do_nothing(index_elements=['workspace_id']))


def backfill_subscriptions(db: Session):
    # A one-time persisted trial for pre-billing workspaces, safe across restarts/workers.
    for workspace_id in db.scalars(select(Workspace.id)):
        initialize_subscription(db, workspace_id)
    db.commit()


def subscription_state(db: Session, workspace_id: str) -> dict:
    row = db.get(Subscription, workspace_id)
    if row is None:
        raise RuntimeError('Workspace chưa được cấp subscription.')
    now = utcnow()
    access_until = max(row.trial_ends_at, row.paid_until or row.trial_ends_at)
    status = 'expired' if now >= access_until else 'trialing' if now < row.trial_ends_at else 'active'
    config = payment_config()
    return {'status': status, 'trialEndsAt': row.trial_ends_at.isoformat(),
            'accessUntil': access_until.isoformat(), 'paidUntil': row.paid_until.isoformat() if row.paid_until else None,
            'canWrite': now < access_until, 'monthlyPrice': config.price,
            'currency': 'VND', 'paymentConfigured': config.ready}


@dataclass(frozen=True)
class PaymentConfig:
    price: int
    bank: str
    account: str
    name: str
    secret: str

    @property
    def ready(self) -> bool:
        return self.price > 0 and all((self.bank, self.account, self.name, len(self.secret) >= 32))


def payment_config() -> PaymentConfig:
    return PaymentConfig(price=int(os.getenv('SUBSCRIPTION_MONTHLY_PRICE_VND', '499000')),
                         bank=os.getenv('SEPAY_BANK_CODE', '').strip(),
                         account=os.getenv('SEPAY_ACCOUNT_NUMBER', '').strip(),
                         name=os.getenv('SEPAY_ACCOUNT_NAME', '').strip(),
                         secret=os.getenv('SEPAY_WEBHOOK_API_KEY', '').strip())
