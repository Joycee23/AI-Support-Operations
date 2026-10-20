"""Account credentials, session cookies, and workspace provisioning."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import timedelta
from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..auth_models import Account, AccountMembership, AuthSession, Invitation
from ..models import Team, User, Workspace, utcnow

COOKIE_NAME = 'support_session'
SESSION_SECONDS = 14 * 86400


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64*1024*1024).hex()
    return f'scrypt-v2${salt}${digest}'


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split('$')
        if algorithm not in ('scrypt', 'scrypt-v2') or len(salt) != 32 or len(expected) != 128:
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768 if algorithm == 'scrypt-v2' else 16384,
                                r=8, p=1, maxmem=64*1024*1024).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def current_session(request: Request, db: Session) -> AuthSession:
    token = request.cookies.get(COOKIE_NAME, '')
    session = db.get(AuthSession, token_hash(token)) if token and len(token) <= 128 else None
    if not session or session.expires_at <= utcnow():
        raise HTTPException(401, 'Vui lòng đăng nhập để tiếp tục.')
    link = db.get(AccountMembership, session.user_id)
    if not link or link.account_id != session.account_id:
        raise HTTPException(401, 'Phiên đăng nhập không còn hợp lệ.')
    expected = request.headers.get('x-workspace-membership')
    if expected and expected != session.user_id:
        raise HTTPException(409, 'Workspace đã thay đổi ở phiên khác. Hãy tải lại trang trước khi tiếp tục.')
    from ..database import scope_workspace
    scope_workspace(db, link.workspace_id)
    return session


def start_session(db: Session, response: Response, account: Account, user: User):
    # A stolen account cannot create an unbounded number of persistent sessions.
    sessions = list(db.scalars(select(AuthSession).where(AuthSession.account_id == account.id).order_by(AuthSession.expires_at.desc())))
    for old in sessions[9:]:
        db.delete(old)
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(token), account_id=account.id, user_id=user.id,
                       expires_at=utcnow() + timedelta(seconds=SESSION_SECONDS)))
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
                        samesite='lax', path='/')


def provision_workspace(db: Session, account: Account, name: str) -> tuple[Workspace, User]:
    workspace = Workspace(id='ws-' + uuid.uuid4().hex, name=name)
    from ..database import scope_workspace
    scope_workspace(db, workspace.id)
    db.add(workspace)
    db.flush()
    team = Team(id='team-' + uuid.uuid4().hex, workspace_id=workspace.id, name='Hỗ trợ khách hàng', color='blue')
    db.add(team)
    db.flush()
    user = User(id='u-' + uuid.uuid4().hex, workspace_id=workspace.id, team_id=team.id,
                name=account.name, email=account.email, role='admin')
    db.add(user)
    db.flush()
    db.add(AccountMembership(account_id=account.id, user_id=user.id, workspace_id=workspace.id))
    db.flush()
    from .billing import initialize_subscription
    initialize_subscription(db, workspace.id)
    return workspace, user


def get_invitation(db: Session, token: str, *, lock: bool = False) -> Invitation:
    query = select(Invitation).where(Invitation.token_hash == token_hash(token))
    invitation = db.scalar(query.with_for_update() if lock else query)
    if not invitation or invitation.accepted_at or invitation.expires_at <= utcnow():
        raise HTTPException(410, 'Lời mời đã hết hạn, đã được sử dụng hoặc đã bị thu hồi.')
    return invitation


def join_invitation(db: Session, account: Account, invitation: Invitation) -> User:
    if account.email != invitation.email:
        raise HTTPException(403, 'Hãy đăng nhập bằng đúng email được mời.')
    existing = db.scalar(select(AccountMembership).where(AccountMembership.account_id == account.id,
                                                        AccountMembership.workspace_id == invitation.workspace_id))
    if existing:
        invitation.accepted_at = utcnow()
        return db.get(User, existing.user_id)
    user = User(id='u-' + uuid.uuid4().hex, workspace_id=invitation.workspace_id, team_id=invitation.team_id,
                name=account.name, email=account.email, role=invitation.role)
    db.add(user)
    db.flush()
    db.add(AccountMembership(account_id=account.id, user_id=user.id, workspace_id=invitation.workspace_id))
    invitation.accepted_at = utcnow()
    db.flush()
    return user
