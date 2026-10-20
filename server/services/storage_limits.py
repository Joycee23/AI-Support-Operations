"""Serialize document admission and enforce tenant storage/disk headroom."""
import shutil
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import func, select
from ..models import KnowledgeItem
from .abuse import _lock, limit_setting


def admit_document(db, workspace_id: str, upload_root: Path, added_bytes: int = 0):
    _lock(db, 'document-storage:' + workspace_id)
    count = db.scalar(select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.workspace_id == workspace_id))
    if count >= limit_setting('KNOWLEDGE_WORKSPACE_MAX_ITEMS', 1000):
        raise HTTPException(409, 'Workspace đã đạt hạn mức tài liệu. Liên hệ đơn vị vận hành để nâng hạn mức.')
    if not added_bytes:
        return
    folder = upload_root / workspace_id
    used = sum(path.stat().st_size for path in folder.glob('*') if path.is_file()) if folder.is_dir() else 0
    for stored in db.scalars(select(KnowledgeItem.source_file).where(KnowledgeItem.workspace_id == workspace_id, KnowledgeItem.source_file.is_not(None))):
        path = Path(stored).resolve()
        # Legacy uploads were flat. New files are grouped per workspace and all
        # versions count toward storage even after an item switches to text.
        if path.parent == upload_root and path.is_file():
            used += path.stat().st_size
    if used + added_bytes > limit_setting('UPLOAD_WORKSPACE_BYTES', 256 * 1024 * 1024):
        raise HTTPException(413, 'Workspace đã đạt hạn mức lưu trữ tài liệu tải lên.')
    if shutil.disk_usage(upload_root).free - added_bytes < limit_setting('UPLOAD_MIN_FREE_BYTES', 1024 * 1024 * 1024):
        raise HTTPException(503, 'Kho tài liệu đang đầy. Vui lòng liên hệ đơn vị vận hành.')
