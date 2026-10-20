import asyncio
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..database import get_db
from ..models import KnowledgeItem, KnowledgeVersion, KnowledgeChunk, KnowledgeJob, Team, User, utcnow
from ..schemas import KnowledgeCreate, KnowledgeUpdate, DraftFAQRequest
from ..security import current_user, require_knowledge_access, require_knowledge_manager
from ..services.ingestion import MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS, ingest_item
from .common import make_event
from ..services.abuse import resource_slot, charge_generation
from ..services.storage_limits import admit_document

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

def ensure_team_access(db: Session, user: User, team_id: str | None):
    if user.role == "manager" and team_id != user.team_id:
        raise HTTPException(403, "Quản lý chỉ tạo kiến thức trong phạm vi nhóm của mình.")
    if team_id and not db.scalar(select(Team).where(Team.id == team_id, Team.workspace_id == user.workspace_id)):
        raise HTTPException(422, "Nhóm kiến thức không thuộc workspace hiện tại.")

def ensure_item_manage_access(user: User, item: KnowledgeItem):
    if user.role == "manager" and item.team_id != user.team_id:
        raise HTTPException(403, "Quản lý chỉ sửa và duyệt kiến thức trong nhóm của mình.")

@router.get("")
def list_knowledge(user: User = Depends(current_user), db: Session = Depends(get_db), status: str | None = None, search: str | None = None):
    query = select(KnowledgeItem).where(KnowledgeItem.workspace_id == user.workspace_id)
    if user.role != "admin":
        query = query.where(KnowledgeItem.team_id.is_(None) | (KnowledgeItem.team_id == user.team_id))
    if status:
        query = query.where(KnowledgeItem.status == status)
    items = list(db.scalars(query.order_by(KnowledgeItem.updated_at.desc())))
    if search:
        needle = search.casefold()
        items = [item for item in items if needle in item.title.casefold() or needle in item.category.casefold() or needle in (item.content or "").casefold()]
    return [{"id": item.id, "title": item.title, "category": item.category, "content": item.content or "", "status": item.status, "processingStatus": item.processing_status, "version": item.version, "teamId": item.team_id, "createdBy": db.get(User, item.created_by).name, "approvedBy": db.get(User, item.approved_by).name if item.approved_by else None, "updatedAt": item.updated_at.isoformat()} for item in items]

@router.post("", status_code=201)
def create_knowledge(payload: KnowledgeCreate, background: BackgroundTasks, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "agent":
        raise HTTPException(403, "Chỉ quản trị viên hoặc quản lý được tạo kiến thức.")
    ensure_team_access(db, user, payload.team_id)
    admit_document(db, user.workspace_id, Path(get_settings().upload_dir).resolve())
    item = KnowledgeItem(id="kb-" + uuid.uuid4().hex[:12], workspace_id=user.workspace_id,
        team_id=payload.team_id, created_by=user.id, title=payload.title.strip(), category=payload.category.strip(),
        content=payload.content.strip(), status="pending", processing_status="queued", version=1)
    db.add(item)
    db.flush()
    db.merge(KnowledgeJob(item_id=item.id, workspace_id=item.workspace_id, queued_at=utcnow()))
    db.flush()
    db.add(KnowledgeVersion(id=str(uuid.uuid4()), workspace_id=user.workspace_id, knowledge_id=item.id,
        version=1, title=item.title, category=item.category, content=item.content, changed_by=user.id, change_note="Tạo bản nháp"))
    make_event(db, user, "knowledge.created", f"Tạo bản nháp kiến thức: {item.title}")
    db.commit()
    background.add_task(ingest_item, item.id, request.app.state.embedding, user.workspace_id)
    return {"id": item.id, "status": item.status, "processingStatus": item.processing_status}

@router.post("/upload", status_code=202)
async def upload_knowledge(
    background: BackgroundTasks, request: Request, title: str, category: str, team_id: str | None = None,
    file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db),
):
    if user.role == "agent":
        raise HTTPException(403, "Chỉ quản trị viên hoặc quản lý được tải tài liệu lên.")
    ensure_team_access(db, user, team_id)
    title, category = title.strip(), category.strip()
    if not 3 <= len(title) <= 240 or not 2 <= len(category) <= 100:
        raise HTTPException(422, "Tên tài liệu cần 3–240 ký tự và danh mục cần 2–100 ký tự, không chỉ chứa khoảng trắng.")
    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, "Định dạng được hỗ trợ: PDF, TXT, MD.")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Tệp vượt quá giới hạn 10 MB.")
    if not contents:
        raise HTTPException(422, 'Tệp không có nội dung.')
    if extension == '.pdf' and not contents.startswith(b'%PDF-'):
        raise HTTPException(415, 'Nội dung tệp không phải PDF hợp lệ.')
    if extension in {'.txt', '.md'}:
        try:
            decoded = contents.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(415, 'Tệp văn bản phải dùng mã hóa UTF-8.')
        if '\x00' in decoded or len(decoded) > 100000 or not decoded.strip():
            raise HTTPException(422, 'Tệp văn bản rỗng, chứa dữ liệu nhị phân hoặc vượt 100.000 ký tự.')
    settings = get_settings()
    upload_dir = Path(settings.upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    admit_document(db, user.workspace_id, upload_dir, len(contents))
    workspace_dir = upload_dir / user.workspace_id
    workspace_dir.mkdir(mode=0o700, exist_ok=True)
    stored_path = workspace_dir / f"{uuid.uuid4().hex}{extension}"
    try:
        with stored_path.open('xb') as handle:
            stored_path.chmod(0o600)
            handle.write(contents)
    except OSError:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(503, 'Không thể lưu tài liệu. Vui lòng thử lại sau.')
    item = KnowledgeItem(id="kb-" + uuid.uuid4().hex[:12], workspace_id=user.workspace_id, team_id=team_id,
        created_by=user.id, title=title.strip(), category=category.strip(), content=None, source_file=str(stored_path),
        source_filename=Path((file.filename or '').replace('\\', '/')).name[:240],
        status="pending", processing_status="queued", version=1)
    db.add(item)
    db.flush()
    db.merge(KnowledgeJob(item_id=item.id, workspace_id=item.workspace_id, queued_at=utcnow()))
    make_event(db, user, "knowledge.uploaded", f"Tải lên tài liệu: {item.title}")
    try:
        db.commit()
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    background.add_task(ingest_item, item.id, request.app.state.embedding, user.workspace_id)
    return {"id": item.id, "status": item.status, "processingStatus": item.processing_status}

@router.put("/{item_id}")
def update_knowledge(item_id: str, payload: KnowledgeUpdate, request: Request, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_knowledge_manager(user)
    item = require_knowledge_access(db, user, item_id)
    db.refresh(item, with_for_update=True)
    ensure_item_manage_access(user, item)
    ensure_team_access(db, user, payload.team_id)
    # Preserve the actual previous metadata while holding the edit lock.
    if not db.scalar(select(KnowledgeVersion.id).where(KnowledgeVersion.knowledge_id == item.id,
                                                       KnowledgeVersion.version == item.version)):
        db.add(KnowledgeVersion(id=str(uuid.uuid4()), workspace_id=user.workspace_id, knowledge_id=item.id,
            version=item.version, title=item.title, category=item.category, content=item.content or "",
            changed_by=user.id, change_note="Lưu phiên bản trước khi cập nhật"))
    db.merge(KnowledgeJob(item_id=item.id, workspace_id=item.workspace_id, queued_at=utcnow()))
    item.version += 1
    item.title = payload.title.strip()
    item.category = payload.category.strip()
    item.content = payload.content.strip()
    item.team_id = payload.team_id
    item.status = "pending"
    item.approved_by = None
    item.processing_status = "queued"
    item.source_file = None
    item.updated_at = utcnow()
    db.add(KnowledgeVersion(id=str(uuid.uuid4()), workspace_id=user.workspace_id, knowledge_id=item.id,
        version=item.version, title=item.title, category=item.category, content=item.content,
        changed_by=user.id, change_note=payload.change_note))
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == item.id))
    make_event(db, user, "knowledge.updated", f"Cập nhật kiến thức: {item.title}")
    db.commit()
    background.add_task(ingest_item, item.id, request.app.state.embedding, user.workspace_id)
    return {"id": item.id, "version": item.version, "status": item.status, "processingStatus": item.processing_status}

@router.post('/{item_id}/retry', status_code=202)
def retry_knowledge(item_id: str, background: BackgroundTasks, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_knowledge_manager(user)
    item = require_knowledge_access(db, user, item_id)
    db.refresh(item, with_for_update=True)
    ensure_item_manage_access(user, item)
    if item.status == 'archived' or item.processing_status != 'failed':
        raise HTTPException(409, 'Chỉ thử lại tài liệu đang lỗi xử lý và chưa lưu trữ.')
    from ..services.abuse import consume_limits
    consume_limits([('knowledge:retry:' + item.id, 3, 3600)])
    item.processing_status = 'queued'
    item.updated_at = utcnow()
    db.merge(KnowledgeJob(item_id=item.id, workspace_id=user.workspace_id, queued_at=utcnow()))
    make_event(db, user, 'knowledge.retry', 'Yêu cầu xử lý lại tài liệu')
    db.commit()
    background.add_task(ingest_item, item.id, request.app.state.embedding, user.workspace_id)
    return {'id': item.id, 'processingStatus': item.processing_status}

@router.post("/{item_id}/approve")
def approve_knowledge(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_knowledge_manager(user)
    item = require_knowledge_access(db, user, item_id)
    db.refresh(item, with_for_update=True)
    ensure_item_manage_access(user, item)
    if item.processing_status != "ready":
        raise HTTPException(409, "Tài liệu chưa xử lý xong. Chỉ có thể duyệt khi trạng thái xử lý là sẵn sàng.")
    item.status = "approved"
    item.approved_by = user.id
    make_event(db, user, "knowledge.approved", f"Duyệt kiến thức: {item.title}")
    db.commit()
    return {"ok": True, "status": item.status}

@router.post("/{item_id}/archive")
def archive_knowledge(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_knowledge_manager(user)
    item = require_knowledge_access(db, user, item_id)
    db.refresh(item, with_for_update=True)
    ensure_item_manage_access(user, item)
    item.status = "archived"
    item.approved_by = None
    make_event(db, user, "knowledge.archived", f"Lưu trữ kiến thức: {item.title}")
    db.commit()
    return {"ok": True, "status": item.status}

@router.get("/{item_id}/versions")
def knowledge_history(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = require_knowledge_access(db, user, item_id)
    versions = list(db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.workspace_id == user.workspace_id,
        KnowledgeVersion.knowledge_id == item.id).order_by(KnowledgeVersion.version.desc())))
    return [{"version": version.version, "title": version.title, "category": version.category, "content": version.content,
        "changedBy": db.get(User, version.changed_by).name, "changeNote": version.change_note, "createdAt": version.created_at.isoformat()} for version in versions]

@router.post("/draft-faq")
async def draft_faq(payload: DraftFAQRequest, request: Request, user: User = Depends(current_user)):
    if user.role == "agent":
        raise HTTPException(403, "Chỉ quản trị viên hoặc quản lý được soạn bản nháp kiến thức.")
    try:
        async with resource_slot(user.workspace_id, user.id), asyncio.timeout(110):
            await charge_generation(user)
            draft = await request.app.state.gemini.draft_knowledge(payload.subject, payload.answers)
        return {**draft, "status": "pending_review"}
    except HTTPException:
        raise
    except Exception as exc:
        request.app.state.logger.warning("FAQ draft request failed (%s)", type(exc).__name__)
        raise HTTPException(502, "AI không thể soạn bản nháp lúc này. Kiểm tra dịch vụ và thử lại.")
