"""Disposable multi-worker fixture. Only launched by scripts/check_concurrency.py."""
import os
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server import database
from server.database import get_db
from server.main import protect_browser_requests
from server.http_security import SecurityMiddleware
from server.routes import auth, workspace, tickets, ai, knowledge, reports


def create_app():
    schema=os.environ['SUPPORT_QA_SCHEMA']
    if not schema.startswith('test_concurrency_'):
        raise RuntimeError('Isolated QA schema required')
    engine=create_engine(os.environ['TEST_DATABASE_URL'],execution_options={'schema_translate_map':{None:schema}},pool_pre_ping=True)
    database.SessionLocal=sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
    database.engine=engine
    app=FastAPI()
    app.add_middleware(SecurityMiddleware)
    app.middleware('http')(protect_browser_requests)
    for router in (auth.router,workspace.router,tickets.router,ai.router,knowledge.router,reports.router): app.include_router(router)
    @app.get('/_qa/worker')
    def worker(): return {'pid':os.getpid()}
    return app
