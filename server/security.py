from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db, scope_workspace
from .models import User, Ticket, KnowledgeItem
from .services.accounts import current_session

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = current_session(request, db)
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, 'Tài khoản không còn thuộc workspace này.')
    scope_workspace(db, user.workspace_id)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not request.url.path.startswith('/api/billing/'):
        from .http_security import production
        from .auth_models import AccountEmailVerification, AccountMFA
        if production() and not db.get(AccountEmailVerification, session.account_id):
            raise HTTPException(403, 'Vui lòng xác minh email trong Cấu hình → Bảo mật tài khoản trước khi thực hiện thao tác.')
        if production() and user.role in ('admin', 'manager'):
            mfa = db.get(AccountMFA, session.account_id)
            if not mfa or not mfa.enabled:
                raise HTTPException(403, 'Quản trị viên và quản lý cần bật xác thực hai bước trong Cấu hình → Bảo mật tài khoản.')
        from .services.billing import subscription_state
        if not subscription_state(db, user.workspace_id)['canWrite']:
            raise HTTPException(402, 'Workspace đã hết hạn. Quản trị viên vui lòng gia hạn trong Cấu hình workspace để tiếp tục sử dụng.')
    # Do not pin an idle DB transaction while an AI provider is running.
    db.commit()
    return user

def require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên workspace được thực hiện thao tác này.")

def require_knowledge_manager(user: User):
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Bạn không có quyền quản lý hoặc duyệt kiến thức.")

def can_access_ticket(user: User, ticket: Ticket) -> bool:
    if ticket.workspace_id != user.workspace_id:
        return False
    if user.role == "admin":
        return True
    if user.role == "manager":
        return ticket.team_id == user.team_id
    return ticket.team_id == user.team_id or ticket.assignee_id == user.id

def ticket_or_404(db: Session, user: User, ticket_id: str) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.workspace_id == user.workspace_id))
    if not ticket or not can_access_ticket(user, ticket):
        raise HTTPException(status_code=404, detail="Không tìm thấy ticket trong phạm vi được phép.")
    return ticket

def can_access_knowledge(user: User, item: KnowledgeItem) -> bool:
    if item.workspace_id != user.workspace_id:
        return False
    if user.role == "admin":
        return True
    return item.team_id is None or item.team_id == user.team_id

def require_knowledge_access(db: Session, user: User, item_id: str) -> KnowledgeItem:
    item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.id == item_id, KnowledgeItem.workspace_id == user.workspace_id))
    if not item or not can_access_knowledge(user, item):
        raise HTTPException(status_code=404, detail="Không tìm thấy mục kiến thức trong phạm vi được phép.")
    return item
