"""Hashed, expiring, single-use email verification and password recovery tokens."""
import secrets
from datetime import timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ..auth_models import Account, AuthSession, AccountToken, AccountEmailVerification
from ..database import get_db
from ..models import utcnow
from ..services.accounts import current_session, hash_password, token_hash
from ..services.abuse import consume_limits
from ..services.mfa import require_mfa
from ..services.invitation_email import send_account_link

router = APIRouter(prefix='/api/auth', tags=['account recovery'])


class Email(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

    @field_validator('email', mode='before')
    @classmethod
    def normalize(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value


class Token(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class Reset(Token):
    password: str = Field(min_length=12, max_length=128)
    code: str = Field(default='', max_length=64)


def issue(db, account, purpose, background):
    consume_limits([('email:action:' + account.id + ':' + purpose, 3, 3600)])
    db.scalar(select(Account).where(Account.id == account.id).with_for_update())
    db.execute(delete(AccountToken).where(AccountToken.account_id == account.id, AccountToken.purpose == purpose))
    db.execute(delete(AccountToken).where(AccountToken.expires_at < utcnow()))
    raw = secrets.token_urlsafe(32)
    db.add(AccountToken(token_hash=token_hash(raw), account_id=account.id, purpose=purpose,
                        expires_at=utcnow() + timedelta(minutes=30)))
    db.commit()
    background.add_task(send_account_link, recipient=account.email, token=raw, purpose=purpose)


def consume_token(db, raw, purpose):
    row = db.scalar(select(AccountToken).where(AccountToken.token_hash == token_hash(raw), AccountToken.purpose == purpose).with_for_update())
    if not row or row.expires_at <= utcnow():
        raise HTTPException(410, 'Link đã hết hạn hoặc đã được sử dụng. Hãy yêu cầu link mới.')
    return row


@router.post('/request-verification')
def request_verification(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    session = current_session(request, db)
    if not db.get(AccountEmailVerification, session.account_id):
        issue(db, db.get(Account, session.account_id), 'verify', background)
    return {'ok': True, 'message': 'Đã tiếp nhận yêu cầu. Kiểm tra email và thư rác; link có hiệu lực 30 phút.'}


@router.post('/verify-email')
def verify_email(payload: Token, request: Request, db: Session = Depends(get_db)):
    consume_limits([('verify:ip:' + (request.client.host if request.client else 'unknown'), 20, 300)])
    row = consume_token(db, payload.token, 'verify')
    if not db.get(AccountEmailVerification, row.account_id):
        db.add(AccountEmailVerification(account_id=row.account_id))
    db.delete(row)
    db.commit()
    return {'ok': True}


@router.post('/forgot-password')
def forgot(payload: Email, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    consume_limits([('recovery:ip:' + (request.client.host if request.client else 'unknown'), 5, 3600)])
    account = db.scalar(select(Account).where(Account.email == payload.email))
    if account:
        try:
            issue(db, account, 'reset', background)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
    # Never reveal whether the account exists or its email has been throttled.
    return {'ok': True, 'message': 'Nếu email đã đăng ký, bạn sẽ nhận được link đặt lại mật khẩu có hiệu lực 30 phút. Kiểm tra cả thư rác.'}


@router.post('/reset-password')
def reset(payload: Reset, request: Request, db: Session = Depends(get_db)):
    consume_limits([('reset:ip:' + (request.client.host if request.client else 'unknown'), 10, 900)])
    hint = db.get(AccountToken, token_hash(payload.token))
    if not hint or hint.purpose != 'reset':
        raise HTTPException(410, 'Link đã hết hạn hoặc đã được sử dụng. Hãy yêu cầu link mới.')
    account = db.scalar(select(Account).where(Account.id == hint.account_id).with_for_update())
    row = consume_token(db, payload.token, 'reset')
    require_mfa(db, account.id, payload.code)
    account.password_hash = hash_password(payload.password)
    db.execute(delete(AuthSession).where(AuthSession.account_id == account.id))
    db.execute(delete(AccountToken).where(AccountToken.account_id == account.id))
    db.commit()
    return {'ok': True}
