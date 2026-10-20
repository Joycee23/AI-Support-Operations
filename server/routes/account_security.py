import json
from datetime import timedelta
from urllib.parse import quote, urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ..auth_models import Account, AccountMFA, AuthSession, AccountEmailVerification
from ..database import get_db
from ..services.accounts import current_session, check_password
from ..services.abuse import consume_limits
from ..services.mfa import new_setup, recovery_codes, verify, require_mfa
from ..models import User, utcnow
from .common import make_event

router = APIRouter(prefix='/api/auth/security', tags=['account security'])


class Reauthenticate(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default='', max_length=64)


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=64)


def identity(request, db):
    session = current_session(request, db)
    consume_limits([('security:account:' + session.account_id, 10, 900)])
    return session, db.get(Account, session.account_id)


def revoke_others(db, session):
    db.execute(delete(AuthSession).where(AuthSession.account_id == session.account_id, AuthSession.token_hash != session.token_hash))


@router.get('')
def status(request: Request, db: Session = Depends(get_db)):
    session = current_session(request, db)
    record = db.get(AccountMFA, session.account_id)
    return {'mfaEnabled': bool(record and record.enabled),
            'emailVerified': db.get(AccountEmailVerification, session.account_id) is not None,
            'recoveryCodesRemaining': len(json.loads(record.recovery_hashes)) if record and record.enabled else 0}


@router.post('/mfa/setup')
def setup(payload: Reauthenticate, request: Request, db: Session = Depends(get_db)):
    session, account = identity(request, db)
    # Serialize concurrent setup/enable operations for this account.
    db.scalar(select(Account).where(Account.id == account.id).with_for_update())
    db.refresh(account)
    if not check_password(payload.password, account.password_hash):
        raise HTTPException(401, 'Mật khẩu hiện tại không đúng.')
    record = db.get(AccountMFA, account.id)
    if record and record.enabled:
        raise HTTPException(409, 'Xác thực hai bước đã được bật.')
    secret, encrypted = new_setup()
    if not record:
        record = AccountMFA(account_id=account.id)
        db.add(record)
    record.secret_encrypted, record.enabled, record.last_counter = encrypted, False, -1
    record.recovery_hashes = '[]'
    record.setup_expires_at = utcnow() + timedelta(minutes=10)
    db.commit()
    uri = 'otpauth://totp/' + quote('AI Support Operations:' + account.email, safe='') + '?' + urlencode({'secret': secret, 'issuer': 'AI Support Operations', 'algorithm': 'SHA1', 'digits': 6, 'period': 30})
    return {'secret': secret, 'uri': uri}


@router.post('/mfa/enable')
def enable(payload: Code, request: Request, db: Session = Depends(get_db)):
    session, account = identity(request, db)
    record = db.scalar(select(AccountMFA).where(AccountMFA.account_id == account.id).with_for_update())
    if not record or record.enabled or not record.setup_expires_at or record.setup_expires_at <= utcnow() or not verify(record, payload.code, recovery=False):
        raise HTTPException(422, 'Thiết lập hoặc mã xác thực không hợp lệ. Hãy thử lại.')
    record.enabled = True
    codes = recovery_codes(record)
    revoke_others(db, session)
    make_event(db, db.get(User, session.user_id), 'account.mfa.enabled', 'Bật xác thực hai bước và thu hồi các phiên khác')
    db.commit()
    return {'recoveryCodes': codes}


@router.post('/mfa/disable')
def disable(payload: Reauthenticate, request: Request, db: Session = Depends(get_db)):
    session, account = identity(request, db)
    if not check_password(payload.password, account.password_hash):
        raise HTTPException(401, 'Mật khẩu hiện tại không đúng.')
    require_mfa(db, account.id, payload.code)
    record = db.get(AccountMFA, account.id)
    if record:
        db.delete(record)
    revoke_others(db, session)
    make_event(db, db.get(User, session.user_id), 'account.mfa.disabled', 'Tắt xác thực hai bước và thu hồi các phiên khác')
    db.commit()
    return {'ok': True}
