"""VietQR checkout and authenticated, idempotent SePay bank webhooks."""
import hmac
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from ..billing_models import PaymentOrder, PaymentReceipt, Subscription
from ..database import get_db
from ..models import User, utcnow
from ..security import current_user, require_admin
from ..services.billing import add_month, payment_config, subscription_state

router = APIRouter(prefix='/api/billing', tags=['billing'])


def serialize_order(order: PaymentOrder):
    expired = order.expires_at <= utcnow() and not order.paid_at
    query = urlencode({'acc': order.account_number, 'bank': order.bank, 'amount': order.amount,
                       'des': order.transfer_code, 'template': 'compact'})
    return {'id': order.id, 'amount': order.amount, 'currency': 'VND', 'transferCode': order.transfer_code,
            'bank': order.bank, 'accountNumber': order.account_number, 'accountName': order.account_name,
            'status': 'paid' if order.paid_at else 'expired' if expired else 'pending',
            'createdAt': order.created_at.isoformat(), 'expiresAt': order.expires_at.isoformat(),
            'paidAt': order.paid_at.isoformat() if order.paid_at else None,
            'qrUrl': None if expired or order.paid_at else 'https://vietqr.app/img?' + query}


@router.get('')
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    orders = []
    if user.role == 'admin':
        orders = [serialize_order(row) for row in db.scalars(select(PaymentOrder).where(
            PaymentOrder.workspace_id == user.workspace_id).order_by(PaymentOrder.created_at.desc()).limit(20))]
    return {'subscription': subscription_state(db, user.workspace_id), 'orders': orders}


@router.post('/orders', status_code=201)
def create_order(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    config = payment_config()
    if not config.ready:
        raise HTTPException(503, 'Thanh toán chưa được cấu hình. Liên hệ đơn vị cung cấp để thiết lập SePay.')
    # Serialize creation per workspace, reusing its current unpaid order.
    db.scalar(select(Subscription).where(Subscription.workspace_id == user.workspace_id).with_for_update())
    now = utcnow()
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.workspace_id == user.workspace_id,
                      PaymentOrder.paid_at.is_(None), PaymentOrder.expires_at > now).order_by(PaymentOrder.created_at.desc()))
    if not order:
        order = PaymentOrder(id=uuid.uuid4().hex, workspace_id=user.workspace_id,
                             transfer_code='ASO' + uuid.uuid4().hex[:20].upper(), amount=config.price,
                             bank=config.bank, account_number=config.account, account_name=config.name,
                             created_at=now, expires_at=now + timedelta(minutes=30))
        db.add(order)
    db.commit()
    return serialize_order(order)


@router.get('/orders/{order_id}')
def get_order(order_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.workspace_id == user.workspace_id))
    if not order:
        raise HTTPException(404, 'Không tìm thấy yêu cầu thanh toán.')
    return serialize_order(order)


class SePayEvent(BaseModel):
    id: int = Field(gt=0)
    accountNumber: str = Field(max_length=100)
    transferType: str = Field(max_length=10)
    transferAmount: Decimal = Field(ge=0, le=2_000_000_000, decimal_places=0)
    content: str = Field(default='', max_length=10000)
    code: str | None = Field(default=None, max_length=200)
    referenceCode: str | None = Field(default=None, max_length=200)


@router.post('/sepay/webhook')
def webhook(payload: SePayEvent, request: Request, db: Session = Depends(get_db)):
    config = payment_config()
    if len(config.secret) < 32:
        raise HTTPException(503, 'Webhook chưa được cấu hình.')
    if not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Apikey ' + config.secret).encode()):
        raise HTTPException(401, 'Webhook không hợp lệ.')
    # Unique provider transaction ID handles concurrent deliveries and provider retries.
    inserted = db.scalar(insert(PaymentReceipt).values(transaction_id=str(payload.id), amount=int(payload.transferAmount),
        reference=payload.referenceCode or '', received_at=utcnow(), outcome='unmatched').on_conflict_do_nothing(
        index_elements=['transaction_id']).returning(PaymentReceipt.transaction_id))
    if not inserted:
        db.commit()
        return {'success': True}
    receipt = db.get(PaymentReceipt, str(payload.id))
    codes = set(re.findall(r'(?<![A-Z0-9])ASO[A-F0-9]{20}(?![A-Z0-9])', payload.content.upper()))
    if payload.code and re.fullmatch(r'ASO[A-F0-9]{20}', payload.code.upper()):
        codes.add(payload.code.upper())
    if payload.transferType != 'in' or len(codes) != 1:
        receipt.outcome = 'ignored'
        db.commit()
        return {'success': True}
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.transfer_code == next(iter(codes))).with_for_update())
    if order:
        receipt.order_id = order.id
        if payload.accountNumber != order.account_number or int(payload.transferAmount) != order.amount:
            receipt.outcome = 'mismatch'
        elif order.paid_at:
            receipt.outcome = 'duplicate_payment'
        else:
            sub = db.scalar(select(Subscription).where(Subscription.workspace_id == order.workspace_id).with_for_update())
            now = utcnow()
            sub.paid_until = add_month(max(now, sub.trial_ends_at, sub.paid_until or sub.trial_ends_at))
            order.paid_at = now
            # Honor late bank settlements against immutable amount/account/code snapshots.
            receipt.outcome = 'paid'
    db.commit()
    return {'success': True}
