import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .http_security import SecurityMiddleware, allowed_hosts, production, validate_production
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .config import get_settings, browser_origins
from . import database
from .database import Base, configure_database, get_db
from .models import KnowledgeItem, KnowledgeJob, utcnow
from datetime import timedelta
from .services.generation_factory import create_generation_service
from .services.embeddings import GeminiEmbeddingProvider
from .services.ingestion import ingest_item
from .routes import ai, auth, billing, knowledge, reports, tickets, workspace, account_security, account_recovery

logger = logging.getLogger("support_operations")
logging.basicConfig(level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production()
    settings = get_settings()
    configure_database(settings.database_url)
    app.state.logger = logger
    # Keep the existing state attribute for API compatibility; the service is provider-neutral.
    app.state.gemini = create_generation_service(settings)
    app.state.embedding = GeminiEmbeddingProvider(settings.gemini_api_key, settings.embedding_model)
    try:
        with database.engine.begin() as connection:
            if production():
                role = connection.execute(text('SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')).first()
                can_create = connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')"))
                if not role or any(role) or can_create:
                    raise RuntimeError('Production yêu cầu runtime database role không có quyền quản trị/CREATE. Chạy provision_database.py bằng migration role trước.')
            else:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text("SELECT 1"))
        with database.engine.connect() as db:
            if db.scalar(text('SELECT version_num FROM alembic_version')) != '0003_operational_signals':
                raise RuntimeError('Database migration is required before startup.')
        from .services.billing import backfill_subscriptions
        with database.SessionLocal() as db:
            backfill_subscriptions(db)
        await app.state.gemini.validate()
        await app.state.embedding.validate()
    except Exception as exc:
        close = getattr(app.state.gemini, "aclose", None)
        if close:
            await close()
        raise RuntimeError(
            "Không thể khởi động: kiểm tra DATABASE_URL, PostgreSQL/pgvector, GEMINI_API_KEY "
            "và cấu hình AI_PROVIDER/9router nếu bật (Gemini vẫn dùng cho embedding). Không có chế độ giả lập AI."
        ) from exc

    async def recover_ingestion():
        while True:
            try:
                with database.SessionLocal() as db:
                    jobs = list(db.query(KnowledgeJob).filter(KnowledgeJob.queued_at <= utcnow()).order_by(KnowledgeJob.queued_at).limit(30))
                    queued = [(job.item_id, job.workspace_id) for job in jobs]
                await asyncio.gather(*(ingest_item(item_id, app.state.embedding, workspace_id) for item_id, workspace_id in queued))
            except Exception as exc:
                logger.warning('Ingestion dispatcher unavailable type=%s', type(exc).__name__)
            await asyncio.sleep(5)
    tasks = [asyncio.create_task(recover_ingestion())]
    app.state.ingestion_tasks = tasks
    app.state.settings = settings
    try:
        yield
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        close = getattr(app.state.gemini, "aclose", None)
        if close:
            await close()

app = FastAPI(title="AI Support Operations API", version="1.0.0", lifespan=lifespan,
              docs_url=None if production() else '/docs', redoc_url=None if production() else '/redoc',
              openapi_url=None if production() else '/openapi.json')
app.add_middleware(CORSMiddleware, allow_origins=browser_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
app.add_middleware(SecurityMiddleware)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's default response echoes input (including passwords and tokens).
    return JSONResponse({'detail': [{k: e[k] for k in ('loc', 'msg', 'type')} for e in exc.errors()]}, status_code=422)

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logger.warning('Database operation unavailable type=%s', type(exc).__name__)
    return JSONResponse({'detail': 'Hệ thống đang bận. Vui lòng thử lại sau.'}, status_code=503,
                        headers={'Retry-After': '5'})
@app.middleware("http")
async def protect_browser_requests(request, call_next):
    if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        allowed = {str(request.base_url).rstrip('/'), *browser_origins()}
        if origin and origin.rstrip('/') not in allowed or not origin and request.cookies.get('support_session'):
            return JSONResponse({'detail': 'Nguồn yêu cầu không hợp lệ. Hãy tải lại ứng dụng.'}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

app.include_router(auth.router)
app.include_router(account_security.router)
app.include_router(account_recovery.router)
app.include_router(billing.router)
app.include_router(workspace.router)
app.include_router(tickets.router)
app.include_router(knowledge.router)
app.include_router(ai.router)
app.include_router(reports.router)

@app.get("/api/health")
def health():
    return {"ok": True, "ai": "required", "vectorStore": "postgresql-pgvector"}

@app.get('/api/ready')
def ready(db = Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except SQLAlchemyError:
        return JSONResponse({'ok': False}, status_code=503)
    return {'ok': True}

@app.get("/")
def web_index():
    from pathlib import Path
    index = Path(__file__).resolve().parent.parent / "dist" / "index.html"
    if not index.exists():
        raise HTTPException(404, "Web client chưa build. Chạy npm run build.")
    return FileResponse(index)

from pathlib import Path
asset_dir = Path(__file__).resolve().parent.parent / "dist" / "assets"
if asset_dir.exists():
    app.mount("/assets", StaticFiles(directory=asset_dir), name="assets")
