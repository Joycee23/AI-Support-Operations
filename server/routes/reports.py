from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import AIAnalysis, AuditEvent, Ticket, User
from ..security import current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.get("/quality")
def quality_report(user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed_tickets = select(Ticket.id).where(Ticket.workspace_id == user.workspace_id)
    if user.role == "manager":
        allowed_tickets = allowed_tickets.where(Ticket.team_id == user.team_id)
    elif user.role == "agent":
        allowed_tickets = allowed_tickets.where((Ticket.team_id == user.team_id) | (Ticket.assignee_id == user.id))
    analyses = list(db.scalars(select(AIAnalysis).where(
        AIAnalysis.workspace_id == user.workspace_id, AIAnalysis.ticket_id.in_(allowed_tickets),
    ).order_by(AIAnalysis.created_at.desc())))
    errors = db.scalar(select(func.count(AuditEvent.id)).where(
        AuditEvent.workspace_id == user.workspace_id, AuditEvent.kind == "ai.error",
        AuditEvent.ticket_id.in_(allowed_tickets),
    )) or 0
    recent_ids = [analysis.ticket_id for analysis in analyses[:30]]
    ticket_codes = dict(db.execute(select(Ticket.id, Ticket.code).where(
        Ticket.workspace_id == user.workspace_id, Ticket.id.in_(recent_ids))).all()) if recent_ids else {}
    missing_knowledge = sum(not analysis.grounded for analysis in analyses)
    return {
        "accepted": sum(analysis.feedback == "accepted" for analysis in analyses),
        "edited": sum(analysis.feedback == "edited" for analysis in analyses),
        "rejected": sum(analysis.feedback == "rejected" for analysis in analyses),
        "missingKnowledge": missing_knowledge,
        "errors": errors,
        "recent": [{"id": analysis.id, "ticketId": analysis.ticket_id, "ticketCode": ticket_codes.get(analysis.ticket_id, "Ticket"), "topic": analysis.topic,
                    "grounded": analysis.grounded, "feedback": analysis.feedback,
                    "createdAt": analysis.created_at.isoformat()} for analysis in analyses[:30]],
    }
