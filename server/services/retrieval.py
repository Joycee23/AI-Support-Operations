from sqlalchemy import select
from sqlalchemy.orm import Session
from .embeddings import EmbeddingProvider
from ..models import KnowledgeChunk, KnowledgeItem, Ticket

async def retrieve_approved_context(db: Session, user, ticket: Ticket, embeddings: EmbeddingProvider, limit: int = 5):
    query_text = f"{ticket.subject}\n{ticket.body}\nChủ đề: {ticket.topic}"
    query_vector = await embeddings.embed_query(query_text)
    scope = []
    if user.role != "admin":
        scope.append(KnowledgeChunk.team_id.is_(None) | (KnowledgeChunk.team_id == user.team_id))
    statement = (
        select(KnowledgeChunk, KnowledgeItem)
        .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.knowledge_id)
        .where(
            KnowledgeChunk.workspace_id == user.workspace_id,
            KnowledgeItem.workspace_id == user.workspace_id,
            KnowledgeItem.status == "approved",
            KnowledgeItem.processing_status == "ready",
            *scope,
        )
        .order_by(KnowledgeChunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    rows = db.execute(statement).all()
    return [{"chunk_id": chunk.id, "knowledge_id": item.id, "title": item.title, "content": chunk.content} for chunk, item in rows]
