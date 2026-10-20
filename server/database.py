from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase):
    pass

engine = None
SessionLocal = None

def configure_database(url: str):
    global engine, SessionLocal
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True, pool_size=10, max_overflow=10, pool_timeout=5,
                           connect_args={'connect_timeout': 5, 'options': '-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000'})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    if SessionLocal is None:
        raise RuntimeError("Database chưa được cấu hình.")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def scope_workspace(session: Session, workspace_id: str):
    """Trusted server context; never populate this from request headers/body."""
    if not workspace_id or len(workspace_id) > 100:
        raise ValueError('Invalid workspace context')
    session.info['workspace_id'] = workspace_id
    if session.in_transaction():
        session.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {'workspace': workspace_id})


@event.listens_for(Session, 'after_begin')
def apply_workspace_context(session, transaction, connection):
    # SET LOCAL cannot leak through the connection pool; reapply after every commit.
    workspace_id = session.info.get('workspace_id', '')
    connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {'workspace': workspace_id})
