import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Ticket, TicketMessage, Team, User, utcnow
from ..schemas import TicketCreate, TicketUpdate
from ..security import current_user, can_access_ticket, ticket_or_404
from .common import make_event, serialize_ticket, serialize_tickets

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
VALID_STATUSES = {"Mới", "Đang xử lý", "Chờ khách", "Chờ xử lý", "Đã giải quyết"}
VALID_PRIORITIES = {"Khẩn cấp", "Cao", "Bình thường", "Thấp"}

@router.post("", status_code=201)
def create_ticket(payload: TicketCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    team = db.scalar(select(Team).where(Team.id == payload.team_id, Team.workspace_id == user.workspace_id))
    if not team or user.role != 'admin' and team.id != user.team_id:
        raise HTTPException(403, 'Bạn không thể tạo ticket trong nhóm này.')
    if len(payload.subject.strip()) < 3 or len(payload.body.strip()) < 3 or len(payload.customer_name.strip()) < 2:
        raise HTTPException(422, 'Vui lòng điền đầy đủ nội dung ticket.')
    ticket = Ticket(id='ticket-' + uuid.uuid4().hex, code='T-' + uuid.uuid4().hex[:10].upper(),
                    workspace_id=user.workspace_id, team_id=team.id, assignee_id=user.id if user.team_id == team.id else None,
                    customer_name=payload.customer_name.strip(), customer_email=payload.customer_email.strip(),
                    subject=payload.subject.strip(), body=payload.body.strip(), channel=payload.channel,
                    status='Mới', priority='Bình thường', topic='Chưa phân loại')
    db.add(ticket)
    db.flush()
    make_event(db, user, 'ticket.created', 'Tạo ticket hỗ trợ', ticket.id)
    db.commit()
    return serialize_ticket(ticket, db)

@router.get("")
def list_tickets(
    status: str | None = None, team_id: str | None = None, priority: str | None = None,
    topic: str | None = None, assignee_id: str | None = None, search: str | None = None,
    updated_after: datetime | None = None, updated_before: datetime | None = None,
    scope: str = "allowed", user: User = Depends(current_user), db: Session = Depends(get_db),
):
    query = select(Ticket).where(Ticket.workspace_id == user.workspace_id)
    if user.role == "manager":
        query = query.where(Ticket.team_id == user.team_id)
    elif user.role == "agent":
        query = query.where((Ticket.team_id == user.team_id) | (Ticket.assignee_id == user.id))
    if scope == "mine":
        query = query.where(Ticket.assignee_id == user.id)
    if status:
        query = query.where(Ticket.status == status)
    if team_id:
        query = query.where(Ticket.team_id == team_id)
    if priority:
        query = query.where(Ticket.priority == priority)
    if topic:
        query = query.where(Ticket.topic == topic)
    if assignee_id:
        query = query.where(Ticket.assignee_id == assignee_id)
    if updated_after:
        query = query.where(Ticket.updated_at >= updated_after)
    if updated_before:
        query = query.where(Ticket.updated_at <= updated_before)
    if search:
        needle = f"%{search.strip()}%"
        query = query.where(Ticket.subject.ilike(needle) | Ticket.body.ilike(needle) | Ticket.customer_name.ilike(needle) | Ticket.code.ilike(needle))
    return serialize_tickets(db.scalars(query.order_by(Ticket.updated_at.desc()).limit(250)), db)

@router.get("/{ticket_id}")
def ticket_detail(ticket_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ticket = ticket_or_404(db, user, ticket_id)
    messages = list(db.scalars(select(TicketMessage).where(
        TicketMessage.ticket_id == ticket.id, TicketMessage.workspace_id == user.workspace_id,
    ).order_by(TicketMessage.created_at)))
    return {"ticket": serialize_ticket(ticket, db), "messages": [
        {"author": message.author_name, "body": message.body, "internal": message.internal, "createdAt": message.created_at.isoformat()}
        for message in messages
    ]}

@router.patch("/{ticket_id}")
def update_ticket(ticket_id: str, payload: TicketUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ticket = ticket_or_404(db, user, ticket_id)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] not in VALID_STATUSES:
            raise HTTPException(422, "Trạng thái ticket không hợp lệ.")
        ticket.status = changes["status"]
        make_event(db, user, "ticket.status", f"Đổi trạng thái thành {ticket.status}", ticket.id)
    if "priority" in changes:
        if changes["priority"] not in VALID_PRIORITIES:
            raise HTTPException(422, "Mức ưu tiên không hợp lệ.")
        ticket.priority = changes["priority"]
        make_event(db, user, "ticket.priority", f"Đổi mức ưu tiên thành {ticket.priority}", ticket.id)
    if "topic" in changes and changes["topic"]:
        ticket.topic = changes["topic"]
        make_event(db, user, "ticket.topic", "Cập nhật chủ đề ticket", ticket.id)
    if "team_id" in changes or "assignee_id" in changes:
        if user.role not in ("admin", "manager"):
            raise HTTPException(403, "Bạn không có quyền phân công ticket.")
        new_team_id = changes.get("team_id", ticket.team_id)
        new_assignee_id = changes.get("assignee_id", ticket.assignee_id)
        if user.role == "manager" and (ticket.team_id != user.team_id or new_team_id != user.team_id):
            raise HTTPException(403, "Quản lý chỉ phân công ticket trong nhóm của mình.")
        team = db.scalar(select(Team).where(Team.id == new_team_id, Team.workspace_id == user.workspace_id))
        if not team:
            raise HTTPException(422, "Nhóm không thuộc workspace hiện tại.")
        if new_assignee_id:
            assignee = db.scalar(select(User).where(User.id == new_assignee_id, User.workspace_id == user.workspace_id))
            if not assignee or assignee.team_id != new_team_id:
                raise HTTPException(422, "Người phụ trách phải thuộc nhóm được chọn trong workspace.")
        ticket.team_id = new_team_id
        ticket.assignee_id = new_assignee_id
        make_event(db, user, "ticket.assignment", "Cập nhật nhóm hoặc người phụ trách", ticket.id)
    if changes.get("note"):
        db.add(TicketMessage(id=str(uuid.uuid4()), workspace_id=user.workspace_id, ticket_id=ticket.id,
            author_id=user.id, author_name=user.name, body=changes["note"], internal=True))
        make_event(db, user, "ticket.note", "Thêm ghi chú nội bộ", ticket.id)
    if changes.get("reply"):
        db.add(TicketMessage(id=str(uuid.uuid4()), workspace_id=user.workspace_id, ticket_id=ticket.id,
            author_id=user.id, author_name=user.name, body=changes["reply"], internal=False))
        make_event(db, user, "ticket.reply.saved", "Đã lưu phản hồi sau xác nhận của nhân viên", ticket.id)
    ticket.updated_at = utcnow()
    db.commit()
    return serialize_ticket(ticket, db)
