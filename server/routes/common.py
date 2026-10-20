from datetime import datetime
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import AuditEvent, Team, User

def make_event(db: Session, user: User, kind: str, detail: str, ticket_id: str | None = None):
    db.add(AuditEvent(
        id=str(uuid.uuid4()), workspace_id=user.workspace_id, actor_id=user.id,
        ticket_id=ticket_id, kind=kind, detail=detail,
    ))

def serialize_ticket(ticket, db, teams=None, people=None):
    team = teams.get(ticket.team_id) if teams is not None else db.get(Team, ticket.team_id)
    assignee = (people.get(ticket.assignee_id) if people is not None else db.get(User, ticket.assignee_id)) if ticket.assignee_id else None
    return {
        "id": ticket.id, "code": ticket.code, "customer": ticket.customer_name,
        "customerEmail": ticket.customer_email, "subject": ticket.subject, "body": ticket.body,
        "channel": ticket.channel, "status": ticket.status, "priority": ticket.priority,
        "topic": ticket.topic, "teamId": ticket.team_id, "team": team.name if team else "Chưa phân nhóm",
        "teamColor": team.color if team else "blue", "assigneeId": ticket.assignee_id,
        "assignee": assignee.name if assignee else "Chưa phân công",
        "createdAt": ticket.created_at.isoformat(), "updatedAt": ticket.updated_at.isoformat(),
    }

def iso(value: datetime | None):
    return value.isoformat() if value else None


def serialize_tickets(tickets, db):
    """Keep lists constant-query even when SQLAlchemy releases weak identity references."""
    rows = list(tickets)
    if not rows:
        return []
    teams = {row.id: row for row in db.scalars(select(Team).where(Team.id.in_({ticket.team_id for ticket in rows})))}
    people_ids = {ticket.assignee_id for ticket in rows if ticket.assignee_id}
    people = {row.id: row for row in db.scalars(select(User).where(User.id.in_(people_ids)))} if people_ids else {}
    return [serialize_ticket(ticket, db, teams, people) for ticket in rows]
