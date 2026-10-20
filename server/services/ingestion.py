import logging
import asyncio
import sys
import re
import uuid
from datetime import timedelta
from pathlib import Path
from sqlalchemy import delete, select
from .. import database
from ..database import scope_workspace
from ..models import KnowledgeChunk, KnowledgeItem, KnowledgeVersion, KnowledgeJob, utcnow
from .embeddings import EmbeddingProvider
from .abuse import consume_limits, limit_setting, resource_slot
from starlette.concurrency import run_in_threadpool

log = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}

def extract_text(path: Path) -> str:
    from .document_worker import extract_bounded
    return extract_bounded(path)


async def extract_isolated(path: Path) -> str:
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'server.services.document_worker', str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 15)
        if process.returncode or len(output) > 400000:
            raise ValueError('Không thể đọc tài liệu trong giới hạn an toàn.')
        return output.decode('utf-8')
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

def split_chunks(text: str, size: int = 1200, overlap: int = 160) -> list[str]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Kích thước đoạn phải dương và overlap nhỏ hơn kích thước đoạn.")
    clean = re.sub(r"\s+", " ", text).strip()
    chunks, start = [], 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            boundary = clean.rfind(" ", start + size // 2, end)
            end = boundary if boundary > start else end
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks

async def ingest_item(item_id: str, embeddings: EmbeddingProvider, workspace_id: str | None = None):
    from fastapi import HTTPException
    with database.SessionLocal() as db:
        if workspace_id is None:
            job = db.get(KnowledgeJob, item_id)
            workspace_id = job.workspace_id if job else None
        if workspace_id:
            scope_workspace(db, workspace_id)
        item = db.get(KnowledgeItem, item_id)
        if not item or item.processing_status == 'ready':
            return
        workspace_id, user_id = item.workspace_id, item.created_by
    try:
        async with resource_slot(workspace_id, user_id, 'ingestion'), asyncio.timeout(300):
            await _ingest_item(item_id, embeddings, workspace_id)
    except HTTPException:
        # Remain queued; the bounded recovery loop retries when capacity frees.
        return
    except TimeoutError:
        with database.SessionLocal() as db:
            if workspace_id:
                scope_workspace(db, workspace_id)
            item = db.get(KnowledgeItem, item_id)
            if item and item.processing_status == 'processing':
                item.processing_status = 'failed'
                db.execute(delete(KnowledgeJob).where(KnowledgeJob.item_id == item_id))
                db.commit()


async def _ingest_item(item_id: str, embeddings: EmbeddingProvider, workspace_id: str | None = None):
    # Snapshot first, release the database transaction before network calls, then
    # lock and verify the version before publishing vectors. Old workers cannot
    # mark a newer edit ready or overwrite its content/chunks.
    with database.SessionLocal() as db:
        if workspace_id:
            scope_workspace(db, workspace_id)
        item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.id == item_id).with_for_update())
        if not item or item.processing_status == 'ready':
            db.execute(delete(KnowledgeJob).where(KnowledgeJob.item_id == item_id))
            db.commit()
            return
        if item.processing_status == 'processing' and item.updated_at > utcnow() - timedelta(minutes=10):
            return
        job = db.get(KnowledgeJob, item_id)
        if job:
            job.queued_at = utcnow() + timedelta(minutes=10)
        version = item.version
        source_file = item.source_file
        content = item.content or ""
        item.processing_status = "processing"
        item.updated_at = utcnow()
        db.commit()
    try:
        if source_file:
            content = await extract_isolated(Path(source_file))
        chunks = split_chunks(content)
        if not chunks or len(chunks) > 100:
            raise ValueError("Tài liệu không có nội dung văn bản.")
        await run_in_threadpool(consume_limits, [
            ('embedding:daily:' + item.workspace_id, limit_setting('EMBEDDING_WORKSPACE_CHUNKS_PER_DAY', 2000), 86400),
            ('embedding:global:daily', limit_setting('EMBEDDING_GLOBAL_CHUNKS_PER_DAY', 20000), 86400),
        ], amount=len(chunks))
        vectors = [await embeddings.embed_document(chunk) for chunk in chunks]
        with database.SessionLocal() as db:
            if workspace_id:
                scope_workspace(db, workspace_id)
            item = db.scalar(select(KnowledgeItem).where(KnowledgeItem.id == item_id).with_for_update())
            if not item or item.version != version or item.source_file != source_file:
                return
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == item.id))
            for index, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
                db.add(KnowledgeChunk(id=str(uuid.uuid4()), workspace_id=item.workspace_id, team_id=item.team_id,
                    knowledge_id=item.id, chunk_index=index, content=chunk_text, embedding=vector))
            if not db.scalar(select(KnowledgeVersion.id).where(KnowledgeVersion.knowledge_id == item.id,
                                                             KnowledgeVersion.version == version)):
                db.add(KnowledgeVersion(id=str(uuid.uuid4()), workspace_id=item.workspace_id, knowledge_id=item.id,
                    version=version, title=item.title, category=item.category, content=content,
                    changed_by=item.created_by, change_note="Nhập tài liệu"))
            item.content = content
            db.execute(delete(KnowledgeJob).where(KnowledgeJob.item_id == item_id))
            item.processing_status = "ready"
            db.commit()
    except Exception as exc:
        with database.SessionLocal() as db:
            if workspace_id:
                scope_workspace(db, workspace_id)
            current = db.scalar(select(KnowledgeItem).where(KnowledgeItem.id == item_id).with_for_update())
            if current and current.version == version and current.processing_status == "processing":
                db.execute(delete(KnowledgeJob).where(KnowledgeJob.item_id == item_id))
                current.processing_status = "failed"
                db.commit()
        log.warning("Ingestion failed for knowledge item %s (%s)", item_id, type(exc).__name__)

async def retry_ingestion(item_id: str, embeddings: EmbeddingProvider):
    await ingest_item(item_id, embeddings)
