import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Workspace, Team, User, Ticket, KnowledgeItem, AIAnalysis, AuditEvent
from ..security import current_user, require_admin
from ..schemas import TeamCreate, WorkspaceCreate
from ..auth_models import Account, AccountMembership
from ..services.accounts import current_session, provision_workspace
from ..services.billing import subscription_state
from .common import make_event, serialize_ticket

router = APIRouter(prefix="/api", tags=["workspace"])

@router.get("/bootstrap")
def bootstrap(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ticket_query = select(Ticket).where(Ticket.workspace_id == user.workspace_id).order_by(Ticket.updated_at.desc())
    if user.role == "manager":
        ticket_query = ticket_query.where(Ticket.team_id == user.team_id)
    elif user.role == "agent":
        ticket_query = ticket_query.where((Ticket.team_id == user.team_id) | (Ticket.assignee_id == user.id))
    tickets = list(db.scalars(ticket_query))
    teams = list(db.scalars(select(Team).where(Team.workspace_id == user.workspace_id)))
    people_query = select(User).where(User.workspace_id == user.workspace_id)
    if user.role != "admin":
        people_query = people_query.where(User.team_id == user.team_id)
    users = list(db.scalars(people_query))
    docs_query = select(KnowledgeItem).where(KnowledgeItem.workspace_id == user.workspace_id)
    if user.role != "admin":
        docs_query = docs_query.where(KnowledgeItem.team_id.is_(None) | (KnowledgeItem.team_id == user.team_id))
    docs = list(db.scalars(docs_query.order_by(KnowledgeItem.updated_at.desc())))
    event_query = select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id).order_by(AuditEvent.created_at.desc()).limit(30)
    analysis_query = select(AIAnalysis).where(AIAnalysis.workspace_id == user.workspace_id)
    if user.role != "admin":
        allowed_ids = [ticket.id for ticket in tickets]
        event_query = event_query.where(AuditEvent.ticket_id.in_(allowed_ids)) if allowed_ids else event_query.where(AuditEvent.id.is_(None))
        analysis_query = analysis_query.where(AIAnalysis.ticket_id.in_(allowed_ids)) if allowed_ids else analysis_query.where(AIAnalysis.ticket_id.is_(None))
    events = list(db.scalars(event_query))
    analyses = list(db.scalars(analysis_query))
    people = {person.id: person for person in users}
    ticket_by_id = {ticket.id: ticket for ticket in tickets}
    session = current_session(request, db)
    memberships = db.execute(select(AccountMembership, Workspace).join(Workspace, Workspace.id == AccountMembership.workspace_id)
                             .where(AccountMembership.account_id == session.account_id).order_by(Workspace.name)).all()
    return {
        "workspaceId": user.workspace_id,
        "subscription": subscription_state(db, user.workspace_id),
        "memberships": [{"id": link.user_id, "workspaceId": workspace.id, "name": workspace.name} for link, workspace in memberships],
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "teamId": user.team_id},
        "workspace": db.get(Workspace, user.workspace_id).name,
        "tickets": [serialize_ticket(ticket, db) for ticket in tickets],
        "teams": [{"id": team.id, "name": team.name, "color": team.color, "count": sum(ticket.team_id == team.id for ticket in tickets)} for team in teams],
        "users": [{"id": person.id, "name": person.name, "email": person.email, "role": person.role, "teamId": person.team_id} for person in users],
        "knowledge": [{"id": doc.id, "title": doc.title, "category": doc.category, "content": doc.content or "", "status": doc.status, "processingStatus": doc.processing_status, "version": doc.version, "updatedAt": doc.updated_at.isoformat(), "teamId": doc.team_id} for doc in docs],
        "events": [{"id": event.id, "actor": people.get(event.actor_id).name if people.get(event.actor_id) else "Người dùng", "kind": event.kind, "detail": event.detail, "createdAt": event.created_at.isoformat(), "ticketCode": ticket_by_id.get(event.ticket_id).code if ticket_by_id.get(event.ticket_id) else None} for event in events],
        "feedback": {"accepted": sum(item.feedback == "accepted" for item in analyses), "edited": sum(item.feedback == "edited" for item in analyses), "rejected": sum(item.feedback == "rejected" for item in analyses), "ungrounded": sum(not item.grounded for item in analyses)},
    }

@router.get("/teams")
def list_teams(user: User = Depends(current_user), db: Session = Depends(get_db)):
    teams = list(db.scalars(select(Team).where(Team.workspace_id == user.workspace_id)))
    return [{"id": team.id, "name": team.name, "color": team.color} for team in teams]

@router.post("/admin/teams", status_code=201)
def create_team(payload: TeamCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Tên nhóm cần ít nhất 2 ký tự.")
    if db.scalar(select(Team.id).where(Team.workspace_id == user.workspace_id, func.lower(Team.name) == name.casefold())):
        raise HTTPException(409, "Tên nhóm đã được sử dụng trong workspace.")
    team = Team(id="team-" + uuid.uuid4().hex[:10], workspace_id=user.workspace_id, name=name, color=payload.color)
    db.add(team)
    make_event(db, user, "team.created", f"Tạo nhóm hỗ trợ: {team.name}")
    db.commit()
    return {"id": team.id, "name": team.name, "color": team.color}

@router.post("/admin/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, request: Request, db: Session = Depends(get_db)):
    session = current_session(request, db)
    from ..services.abuse import consume_limits
    from ..http_security import production
    from ..auth_models import AccountEmailVerification, AccountMembership, AccountMFA
    from sqlalchemy import func
    consume_limits([('workspace:create:' + session.account_id, 3, 3600)])
    if production() and not db.get(AccountEmailVerification, session.account_id):
        raise HTTPException(403, 'Vui lòng xác minh email trong Cấu hình trước khi tạo workspace.')
    if production():
        mfa = db.get(AccountMFA, session.account_id)
        if not mfa or not mfa.enabled:
            raise HTTPException(403, 'Vui lòng bật xác thực hai bước trước khi tạo workspace mới.')
    db.scalar(select(Account).where(Account.id == session.account_id).with_for_update())
    if db.scalar(select(func.count()).select_from(AccountMembership).where(AccountMembership.account_id == session.account_id)) >= 20:
        raise HTTPException(409, 'Tài khoản đã đạt giới hạn 20 workspace. Liên hệ đơn vị vận hành.')
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, 'Tên workspace cần ít nhất 2 ký tự.')
    account = db.get(Account, session.account_id)
    workspace, user = provision_workspace(db, account, name)
    session.user_id = user.id
    make_event(db, user, 'workspace.created', 'Tạo workspace')
    db.commit()
    return {'workspaceId': workspace.id, 'workspace': workspace.name, 'adminUserId': user.id}

@router.get("/audit")
def audit(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id).order_by(AuditEvent.created_at.desc()).limit(100)
    if user.role != "admin":
        allowed_ids = select(Ticket.id).where(Ticket.workspace_id == user.workspace_id, Ticket.team_id == user.team_id)
        if user.role == "agent":
            allowed_ids = select(Ticket.id).where(Ticket.workspace_id == user.workspace_id, (Ticket.team_id == user.team_id) | (Ticket.assignee_id == user.id))
        query = query.where(AuditEvent.ticket_id.in_(allowed_ids))
    events = list(db.scalars(query))
    return [{"id": event.id, "actor": db.get(User, event.actor_id).name, "ticketId": event.ticket_id, "kind": event.kind, "detail": event.detail, "createdAt": event.created_at.isoformat()} for event in events]

@router.patch('/admin/workspace')
def rename_workspace(payload: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, 'Tên doanh nghiệp cần ít nhất 2 ký tự.')
    workspace = db.get(Workspace, user.workspace_id)
    workspace.name = name
    make_event(db, user, 'workspace.updated', 'Đổi tên workspace')
    db.commit()
    return {'workspace': workspace.name}
