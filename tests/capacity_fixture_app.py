"""Isolated capacity fixture; real HTTP/DB/RLS, synthetic external model latency."""
import asyncio, logging, os
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server import database
from server.http_security import SecurityMiddleware
from server.main import protect_browser_requests
from server.routes import auth, workspace, tickets, ai, knowledge, reports, billing, account_recovery, account_security
from server.services.generation import SuggestionPayload

class SyntheticModel:
    async def generate_suggestion(self,prompt):
        await asyncio.sleep(1)
        return SuggestionPayload(topic='QA',priority='Bình thường',suggested_team_id=None,reason='Synthetic capacity measurement',draft='',citations=[],grounded=False,handoff_reason='Synthetic fixture; no external AI called')

class SyntheticEmbedding:
    async def embed_query(self,text):return [1.0]+[0.0]*767
    async def embed_document(self,text):return [1.0]+[0.0]*767


def create_app():
    schema=os.environ['SUPPORT_QA_SCHEMA']
    if not schema.startswith('test_capacity_'):raise RuntimeError('Disposable schema required')
    engine=create_engine(os.environ['CAPACITY_DATABASE_URL'],hide_parameters=True,
        execution_options={'schema_translate_map':{None:schema}},pool_size=10,max_overflow=10,pool_timeout=5,pool_pre_ping=True)
    database.engine=engine
    database.SessionLocal=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
    # PostgreSQL advisory locks are database-wide, unlike schema-local tables.
    # Separate disposable fixtures must not contend on the same generator IP
    # or lease key. Workers in this fixture still share every admission lock.
    from server.services import abuse
    original_lock = abuse._lock
    def fixture_lock(db, key):
        return original_lock(db, schema + ':' + key)
    abuse._lock = fixture_lock
    app=FastAPI()
    app.add_middleware(SecurityMiddleware);app.middleware('http')(protect_browser_requests)
    for router in (auth.router,workspace.router,tickets.router,ai.router,knowledge.router,reports.router,billing.router,account_recovery.router,account_security.router):app.include_router(router)
    app.state.gemini=SyntheticModel();app.state.embedding=SyntheticEmbedding();app.state.logger=logging.getLogger('capacity')
    @app.get('/_qa/worker')
    def worker():return {'pid':os.getpid()}
    return app
