import secrets
import hashlib
import uuid
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..auth_models import Account, AccountMembership, AuthSession, Invitation, InvitationDelivery, AuthRateLimit
from ..database import get_db
from .. import database
from ..models import Team, User, Workspace, utcnow
from ..security import current_user
from ..services.accounts import (COOKIE_NAME, check_password, current_session, get_invitation,
                                hash_password, join_invitation, provision_workspace, start_session, token_hash)
from ..services.invitation_email import invitation_url, send_invitation
from .common import make_event
from ..services.abuse import consume_limits
from ..services.mfa import require_mfa

router = APIRouter(prefix='/api/auth', tags=['accounts'])
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default='', max_length=64)

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, value: str):
        return value.strip().casefold() if isinstance(value, str) else value


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    workspace_name: str = Field(default='', max_length=180)
    invitation_token: str | None = Field(default=None, max_length=100)


class TokenPayload(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class SwitchWorkspace(BaseModel):
    membership_id: str = Field(max_length=100)


class InviteCreate(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role: str = 'agent'
    team_id: str


def throttle(request: Request, *, scope: str | None = None):
    # One database-backed bucket shared by every API worker. Failed logins must
    # consume attempts even when their business transaction is rolled back.
    key = scope or (request.client.host if request.client else 'unknown')
    digest = hashlib.sha256(key.encode()).hexdigest()
    lock_key = int.from_bytes(bytes.fromhex(digest)[:8], 'big', signed=True)
    now = utcnow()
    with database.SessionLocal() as limiter:
        limiter.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
        bucket = limiter.get(AuthRateLimit, digest)
        if bucket is None:
            bucket = AuthRateLimit(key_hash=digest, started_at=now, attempts=0)
            limiter.add(bucket)
        elif bucket.started_at <= now - timedelta(minutes=5):
            bucket.started_at, bucket.attempts = now, 0
        if bucket.attempts >= 20:
            raise HTTPException(429, 'Quá nhiều lần thử. Vui lòng đợi 5 phút rồi thử lại.', headers={'Retry-After': '300'})
        bucket.attempts += 1
        limiter.commit()


@router.post('/register', status_code=201)
def register(payload: Registration, request: Request, response: Response, db: Session = Depends(get_db)):
    throttle(request)
    consume_limits([('register:ip:' + (request.client.host if request.client else 'unknown'), 3, 3600)])
    name = payload.name.strip()
    workspace_name = payload.workspace_name.strip()
    if len(name) < 2 or not payload.invitation_token and len(workspace_name) < 2:
        raise HTTPException(422, 'Vui lòng nhập tên của bạn và tên doanh nghiệp có ít nhất 2 ký tự.')
    if db.scalar(select(Account.id).where(Account.email == payload.email)):
        raise HTTPException(409, 'Email đã có tài khoản. Vui lòng đăng nhập.')
    try:
        account = Account(id=str(uuid.uuid4()), name=name, email=payload.email, password_hash=hash_password(payload.password))
        db.add(account)
        db.flush()
        if payload.invitation_token:
            invitation = get_invitation(db, payload.invitation_token, lock=True)
            user = join_invitation(db, account, invitation)
        else:
            _, user = provision_workspace(db, account, workspace_name)
        make_event(db, user, 'account.registered', 'Tạo tài khoản và tham gia workspace')
        start_session(db, response, account, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Tài khoản hoặc thành viên đã tồn tại. Vui lòng đăng nhập.')
    return {'ok': True}


@router.post('/login')
def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    throttle(request)
    consume_limits([('login:email:' + payload.email, 10, 900)])
    account = db.scalar(select(Account).where(Account.email == payload.email))
    valid = check_password(payload.password, account.password_hash if account else _DUMMY_HASH)
    if not account or not valid:
        raise HTTPException(401, 'Email hoặc mật khẩu không đúng.')
    checked_hash = account.password_hash
    db.refresh(account, with_for_update=True)
    if account.password_hash != checked_hash:
        raise HTTPException(401, 'Thông tin đăng nhập đã thay đổi. Vui lòng thử lại.')
    require_mfa(db, account.id, payload.code)
    if not account.password_hash.startswith('scrypt-v2$'):
        account.password_hash = hash_password(payload.password)
    link = db.scalar(select(AccountMembership).where(AccountMembership.account_id == account.id).order_by(AccountMembership.workspace_id))
    if not link:
        raise HTTPException(403, 'Tài khoản chưa thuộc workspace nào.')
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(old_token)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
    start_session(db, response, account, db.get(User, link.user_id))
    db.commit()
    return {'ok': True}


@router.post('/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'ok': True}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    code: str = Field(default='', max_length=64)


@router.post('/change-password')
def change_password(payload: PasswordChange, request: Request, response: Response, db: Session = Depends(get_db)):
    session = current_session(request, db)
    consume_limits([('password:account:' + session.account_id, 5, 900)])
    account = db.get(Account, session.account_id)
    db.refresh(account, with_for_update=True)
    if not check_password(payload.current_password, account.password_hash):
        raise HTTPException(401, 'Mật khẩu hiện tại không đúng.')
    require_mfa(db, account.id, payload.code)
    if payload.new_password == payload.current_password:
        raise HTTPException(422, 'Mật khẩu mới phải khác mật khẩu hiện tại.')
    user = db.get(User, session.user_id)
    account.password_hash = hash_password(payload.new_password)
    from ..auth_models import AccountToken
    db.execute(delete(AccountToken).where(AccountToken.account_id == account.id))
    db.execute(delete(AuthSession).where(AuthSession.account_id == account.id))
    start_session(db, response, account, user)
    make_event(db, user, 'account.password.changed', 'Đổi mật khẩu và thu hồi các phiên đăng nhập cũ')
    db.commit()
    return {'ok': True}


@router.post('/logout-all')
def logout_all(request: Request, response: Response, db: Session = Depends(get_db)):
    session = current_session(request, db)
    user = db.get(User, session.user_id)
    db.execute(delete(AuthSession).where(AuthSession.account_id == session.account_id))
    make_event(db, user, 'account.sessions.revoked', 'Đăng xuất tất cả thiết bị')
    db.commit()
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'ok': True}


@router.post('/switch-workspace')
def switch_workspace(payload: SwitchWorkspace, request: Request, db: Session = Depends(get_db)):
    session = current_session(request, db)
    link = db.get(AccountMembership, payload.membership_id)
    if not link or link.account_id != session.account_id:
        raise HTTPException(404, 'Bạn không phải thành viên của workspace này.')
    session.user_id = link.user_id
    db.commit()
    return {'ok': True}


@router.post('/invitations/preview')
def preview_invitation(payload: TokenPayload, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    invitation = get_invitation(db, payload.token)
    return {'workspace': db.get(Workspace, invitation.workspace_id).name, 'email': invitation.email,
            'role': invitation.role, 'expiresAt': invitation.expires_at.isoformat()}


@router.post('/invitations/accept')
def accept_invitation(payload: TokenPayload, request: Request, db: Session = Depends(get_db)):
    session = current_session(request, db)
    invitation = get_invitation(db, payload.token, lock=True)
    try:
        user = join_invitation(db, db.get(Account, session.account_id), invitation)
        session.user_id = user.id
        make_event(db, user, 'member.joined', 'Tham gia workspace bằng lời mời')
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Bạn đã tham gia workspace này. Hãy tải lại trang.')
    return {'ok': True}


@router.post('/invitations', status_code=201)
def invite_member(payload: InviteCreate, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ('admin', 'manager'):
        raise HTTPException(403, 'Bạn không có quyền mời thành viên.')
    if payload.role not in ('manager', 'agent') or user.role == 'manager' and (payload.role != 'agent' or payload.team_id != user.team_id):
        raise HTTPException(403, 'Vai trò hoặc nhóm được mời vượt quá quyền của bạn.')
    team = db.scalar(select(Team).where(Team.id == payload.team_id, Team.workspace_id == user.workspace_id))
    if not team:
        raise HTTPException(422, 'Nhóm không thuộc workspace hiện tại.')
    throttle(request, scope="invite:" + user.workspace_id)
    email = payload.email.strip().casefold()
    if db.scalar(select(User.id).where(User.workspace_id == user.workspace_id, User.email == email)):
        raise HTTPException(409, 'Email đã là thành viên của workspace.')
    db.execute(delete(Invitation).where(Invitation.workspace_id == user.workspace_id, Invitation.email == email,
                                       Invitation.team_id == team.id, Invitation.accepted_at.is_(None)))
    token = secrets.token_urlsafe(32)
    invitation = Invitation(token_hash=token_hash(token), workspace_id=user.workspace_id, team_id=team.id,
                            email=email, role=payload.role, created_by=user.id, expires_at=utcnow() + timedelta(days=7))
    db.add(invitation)
    db.flush()
    delivery = InvitationDelivery(invitation_id=invitation.token_hash, status='pending',
                                  message='Chưa có xác nhận từ máy chủ email.')
    db.add(delivery)
    workspace_name = db.get(Workspace, user.workspace_id).name
    make_event(db, user, 'member.invited', 'Tạo lời mời tham gia workspace')
    # Persist the usable invitation before attempting the external SMTP operation.
    db.commit()
    result = send_invitation(recipient=email, token=token, workspace=workspace_name,
                             inviter=user.name, team=team.name, role=payload.role, expires_at=invitation.expires_at)
    # A concurrent revocation/replacement may have deleted the delivery row.
    db.execute(update(InvitationDelivery).where(InvitationDelivery.invitation_id == invitation.token_hash)
               .values(status=result.status, message=result.message, updated_at=utcnow()))
    db.commit()
    return {'token': token, 'url': invitation_url(token), 'email': email, 'expiresAt': invitation.expires_at.isoformat(),
            'emailDelivery': {'status': result.status, 'message': result.message}}


@router.get('/invitations')
def list_invitations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in ('admin', 'manager'):
        raise HTTPException(403, 'Bạn không có quyền xem lời mời.')
    query = select(Invitation).where(Invitation.workspace_id == user.workspace_id, Invitation.accepted_at.is_(None))
    if user.role == 'manager':
        query = query.where(Invitation.team_id == user.team_id)
    rows = db.execute(query.add_columns(InvitationDelivery).outerjoin(
        InvitationDelivery, InvitationDelivery.invitation_id == Invitation.token_hash)
        .order_by(Invitation.expires_at.desc())).all()
    return [{'id': item.token_hash, 'email': item.email, 'role': item.role, 'teamId': item.team_id,
             'expiresAt': item.expires_at.isoformat(), 'emailDelivery': {
                 'status': delivery.status if delivery else 'not_attempted',
                 'message': delivery.message if delivery else 'Lời mời này chỉ được chia sẻ bằng link.'}}
            for item, delivery in rows]


@router.delete('/invitations/{invitation_id}')
def revoke_invitation(invitation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Invitation, invitation_id)
    if not item or item.workspace_id != user.workspace_id:
        raise HTTPException(404, 'Không tìm thấy lời mời.')
    if user.role != 'admin' and not (user.role == 'manager' and item.team_id == user.team_id):
        raise HTTPException(403, 'Bạn không có quyền thu hồi lời mời này.')
    db.delete(item)
    make_event(db, user, 'member.invitation_revoked', 'Thu hồi lời mời tham gia workspace')
    db.commit()
    return {'ok': True}
