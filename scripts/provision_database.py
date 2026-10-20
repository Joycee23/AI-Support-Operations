"""Provision production schema with a migration role, grant a restricted app role.

Run on a trusted administration host, NOT inside the runtime app container.
Requires DATABASE_MIGRATION_URL and DOCKER_DATABASE_URL in its environment/.env.
"""
import os
from pathlib import Path
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.database import Base
from server import models, auth_models, billing_models


def main():
    load_dotenv(ROOT / '.env')
    migration = os.getenv('DATABASE_MIGRATION_URL', '')
    runtime = os.getenv('RUNTIME_DATABASE_URL') or os.getenv('DOCKER_DATABASE_URL', '')
    if not migration or not runtime:
        raise SystemExit('Cần DATABASE_MIGRATION_URL và DOCKER_DATABASE_URL riêng. Xem SECURITY.md.')
    admin, app = make_url(migration), make_url(runtime)
    if not app.username or not app.password or len(app.password) < 24 or admin.username == app.username or admin.database != app.database:
        raise SystemExit('Migration/runtime phải khác user, cùng database; runtime password ít nhất 24 ký tự.')
    engine = create_engine(migration, hide_parameters=True)
    role = engine.dialect.identifier_preparer.quote(app.username)
    try:
        with engine.begin() as db:
            db.execute(text('SELECT pg_advisory_xact_lock(7020202601)'))
            existing = db.execute(text('SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=:name'), {'name':app.username}).first()
            if existing and any(existing):
                raise RuntimeError('Runtime role đang có quyền quản trị; dùng role mới hoặc thu hồi quyền trước.')
            if not existing:
                password = db.scalar(text('SELECT quote_literal(:password)'), {'password':app.password})
                db.exec_driver_sql(f'CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {password}')
            backup_url = os.getenv('BACKUP_DATABASE_URL', '')
            if backup_url:
                backup = make_url(backup_url)
                if (not backup.username or not backup.password or len(backup.password)<24
                    or backup.username in {admin.username, app.username} or backup.database!=admin.database
                    or backup.host!=admin.host or backup.port!=admin.port):
                    raise RuntimeError('Backup reader must be separate, on the same database, with a strong password')
                backup_role = engine.dialect.identifier_preparer.quote(backup.username)
                flags = db.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=:name'), {'name':backup.username}).first()
                if flags and any(flags):
                    raise RuntimeError('Backup reader cannot hold administration rights')
                if not flags:
                    quoted = db.scalar(text('SELECT quote_literal(:password)'), {'password':backup.password})
                    db.exec_driver_sql(f'CREATE ROLE {backup_role} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS PASSWORD {quoted}')
                else:
                    db.exec_driver_sql(f'ALTER ROLE {backup_role} BYPASSRLS INHERIT')
                db.exec_driver_sql(f'GRANT pg_read_all_data TO {backup_role}')
                db.exec_driver_sql(f'ALTER ROLE {backup_role} SET default_transaction_read_only=on')
            db.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            db.execute(text('REVOKE CREATE ON SCHEMA public FROM PUBLIC'))
            db.execute(text('REVOKE CREATE, TEMPORARY ON DATABASE ' + engine.dialect.identifier_preparer.quote(app.database) + ' FROM PUBLIC'))
            # Versioned migration must run as the trusted migration role.
            from alembic import command
            from alembic.config import Config
            config = Config(str(ROOT / 'alembic.ini'))
            config.attributes['connection'] = db
            command.upgrade(config, 'head')
            db.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO {role}')
            db.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}')
            db.exec_driver_sql(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}')
            db.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}')
            db.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}')
            db.exec_driver_sql(f'REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {role}')
        print('Schema đã chuẩn bị; runtime role chỉ được đọc/ghi dữ liệu, không giữ quyền quản trị.')
    except Exception:
        # Never include password-bearing CREATE ROLE SQL in a traceback.
        raise SystemExit('Provisioning thất bại. Kiểm tra quyền migration/database và cấu hình role; thông tin bí mật đã được che.') from None
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
