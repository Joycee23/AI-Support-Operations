"""Exercise real Alembic upgrades/RLS using a disposable database and restricted role."""
import json, os, secrets, sys, uuid
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.database import scope_workspace
from sqlalchemy.orm import Session


def main():
    url=make_url(os.getenv('TEST_DATABASE_URL') or os.getenv('DATABASE_MIGRATION_URL') or dotenv_values(ROOT/'.env').get('DATABASE_MIGRATION_URL') or dotenv_values(ROOT/'.env')['DATABASE_URL'])
    suffix=uuid.uuid4().hex[:12]
    name='test_migrations_'+suffix
    role='test_runtime_'+suffix
    password=secrets.token_urlsafe(32)
    admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT',hide_parameters=True)
    engine=None
    runtime=None
    try:
        with admin.connect() as db:
            db.exec_driver_sql(f'CREATE DATABASE {name}')
            db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
        engine=create_engine(url.set(database=name),hide_parameters=True)
        config=Config(str(ROOT/'alembic.ini'))
        os.environ['DATABASE_MIGRATION_URL']=url.set(database=name).render_as_string(hide_password=False)
        command.upgrade(config,'head')
        command.upgrade(config,'head')
        with engine.begin() as db:
            db.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO {role}')
            db.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role}')
            db.exec_driver_sql("INSERT INTO workspaces VALUES ('ws-a','QA A'),('ws-b','QA B')")
            db.exec_driver_sql("INSERT INTO teams (id,workspace_id,name,color) VALUES ('ta','ws-a','A','blue'),('tb','ws-b','B','blue')")
            db.exec_driver_sql("INSERT INTO tickets (id,workspace_id,team_id,code,customer_name,customer_email,subject,body,channel,status,priority,topic,created_at,updated_at) VALUES ('a','ws-a','ta','A','QA','qa@example.com','A','Private A','Chat','Mới','Cao','QA',now(),now()),('b','ws-b','tb','B','QA','qa@example.com','B','Private B','Chat','Mới','Cao','QA',now(),now())")
        runtime=create_engine(url.set(database=name,username=role,password=password),pool_size=1,max_overflow=0,hide_parameters=True)
        report={}
        with Session(runtime) as db:
            report['missing_context_denied']=db.scalar(text('SELECT count(*) FROM tickets'))==0
            scope_workspace(db,'ws-a')
            report['unfiltered_select_isolated']=db.execute(text('SELECT id FROM tickets')).scalars().all()==['a']
            report['cross_tenant_update_denied']=db.execute(text("UPDATE tickets SET body='attack' WHERE id='b'")).rowcount==0
            db.commit()
            report['context_survives_commit']=db.execute(text('SELECT id FROM tickets')).scalars().all()==['a']
            db.rollback()
            try:
                db.execute(text("INSERT INTO audit_events(id,workspace_id,actor_id,kind,detail) VALUES ('evil','ws-b','missing','attack','QA')"))
                report['cross_tenant_insert_denied']=False
            except Exception:
                db.rollback();report['cross_tenant_insert_denied']=True
        with Session(runtime) as db:
            report['pooled_context_does_not_leak']=db.scalar(text('SELECT count(*) FROM tickets'))==0
            scope_workspace(db,'ws-b')
            report['next_tenant_reads_own_rows']=db.execute(text('SELECT id FROM tickets')).scalars().all()==['b']
        with engine.connect() as db:
            report['revision_at_head']=db.scalar(text('SELECT version_num FROM alembic_version'))=='0003_operational_signals'
            report['forced_rls_tables']=db.scalar(text("SELECT count(*) FROM pg_class WHERE relname IN ('tickets','ticket_messages','knowledge_items','knowledge_versions','knowledge_chunks','ai_analyses','audit_events') AND relrowsecurity AND relforcerowsecurity"))==7
        report['passed']=all(report.values())
        (ROOT/'artifacts').mkdir(exist_ok=True)
        (ROOT/'artifacts/acceptance-migrations-rls.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        return not report['passed']
    finally:
        if runtime:runtime.dispose()
        if engine:engine.dispose()
        with admin.connect() as db:
            db.exec_driver_sql(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
            db.exec_driver_sql(f'DROP ROLE IF EXISTS {role}')
        admin.dispose()
if __name__=='__main__':raise SystemExit(main())
