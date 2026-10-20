"""Download encrypted R2/S3 backups and boot the full app against an isolated restore.

Never overwrite live databases/files or print credentials. Requires local Docker,
age identity and application configuration. Restores all uploads into a temporary
directory, checks byte hashes, verifies database/RLS, and probes authenticated APIs.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import importlib.util
from unittest.mock import patch

import boto3
from botocore.config import Config
from dotenv import dotenv_values
import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.auth_models import AccountMembership, AuthSession
from server.models import utcnow
from server.services.accounts import token_hash


def run():
    os.umask(0o077)
    settings = {k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}
    client = boto3.client('s3', endpoint_url=settings['BACKUP_S3_ENDPOINT'],
        aws_access_key_id=settings['BACKUP_S3_ACCESS_KEY_ID'],
        aws_secret_access_key=settings['BACKUP_S3_SECRET_ACCESS_KEY'],
        region_name=settings.get('BACKUP_S3_REGION', 'auto'),
        config=Config(connect_timeout=10, read_timeout=60, retries={'max_attempts': 3}))
    bucket = settings['BACKUP_S3_BUCKET']
    prefix = settings.get('BACKUP_S3_PREFIX', 'support-ops/').strip('/') + '/'
    rows = [r for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix)
            for r in page.get('Contents', [])]
    target = 'restore_dr_' + uuid.uuid4().hex[:16]
    role = 'qa_restore_' + uuid.uuid4().hex[:16]
    password = secrets.token_urlsafe(32)
    url = make_url(settings['DATABASE_MIGRATION_URL'])
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT', hide_parameters=True)
    restored = None
    process = None
    role_created = False
    database_created = False
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'liveDataOverwritten': False}
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='support-disaster-recovery-') as temporary:
            folder = Path(temporary)
            backups = {}
            for kind in ('database', 'files', 'application'):
                row = max((r for r in rows if Path(r['Key']).name.startswith(kind + '-') and r['Key'].endswith('.age')),
                          key=lambda r: r['LastModified'])
                path = folder / Path(row['Key']).name
                client.download_file(bucket, row['Key'], str(path))
                with path.open('rb') as handle:
                    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                if digest != client.head_object(Bucket=bucket, Key=row['Key']).get('Metadata', {}).get('sha256'):
                    raise RuntimeError('Remote backup integrity failure')
                backups[kind] = path
            report['remoteHashesMatch'] = True
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/restore_verify.py'), str(backups['database']),
                '--identity', str(ROOT / '.secrets/backup-age-key.txt'), '--target-db', target],
                cwd=ROOT, capture_output=True, timeout=360)
            # createdb precedes pg_restore: clean up this disposable name even if
            # pg_restore fails; restore_verify never overwrites an existing name.
            with admin.connect() as db:
                database_created = bool(db.scalar(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': target}))
            if result.returncode:
                raise RuntimeError('Database restore failed')
            report['databaseRestored'] = True
            archive_path = folder / 'uploads.tar.gz'
            with archive_path.open('wb') as output:
                result = subprocess.run(['age', '--decrypt', '--identity', str(ROOT / '.secrets/backup-age-key.txt'), str(backups['files'])],
                    stdout=output, stderr=subprocess.PIPE, timeout=120)
            if result.returncode:
                raise RuntimeError('Upload archive decryption failed')
            manifest = {}
            with tarfile.open(archive_path, 'r:gz') as archive:
                for member in archive:
                    parts = Path(member.name).parts
                    if not parts or parts[0] != 'uploads' or '..' in parts or Path(member.name).is_absolute():
                        raise RuntimeError('Unsafe archive path')
                    if member.isdir():
                        (folder / member.name).mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        destination = folder / member.name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(member)
                        digest = hashlib.sha256()
                        with destination.open('wb') as output:
                            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                                output.write(chunk); digest.update(chunk)
                        with destination.open('rb') as handle:
                            if hashlib.file_digest(handle, 'sha256').hexdigest() != digest.hexdigest():
                                raise RuntimeError('Restored upload mismatch')
                        manifest[member.name] = digest.hexdigest()
                    else:
                        raise RuntimeError('Unsupported archive member type')
            report['uploadFilesRestoredAndHashed'] = len(manifest)
            release_archive = folder / 'application.tar.gz'
            with release_archive.open('wb') as output:
                result = subprocess.run(['age', '--decrypt', '--identity', str(ROOT / '.secrets/backup-age-key.txt'), str(backups['application'])],
                    stdout=output, stderr=subprocess.PIPE, timeout=120)
            if result.returncode:
                raise RuntimeError('Application archive decryption failed')
            with tarfile.open(release_archive, 'r:gz') as archive:
                for member in archive:
                    parts = Path(member.name).parts
                    if not parts or parts[0] != 'application' or '..' in parts or Path(member.name).is_absolute() or not member.isfile():
                        raise RuntimeError('Unsafe application archive member')
                    destination = folder / member.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open('wb') as output:
                        source = archive.extractfile(member)
                        for chunk in iter(lambda: source.read(1024 * 1024), b''):
                            output.write(chunk)
            recovered_source = folder / 'application'
            if not (recovered_source / 'server/main.py').is_file() or not (recovered_source / 'dist/index.html').is_file():
                raise RuntimeError('Application source or built frontend missing')
            if (recovered_source / '.env').exists() or (recovered_source / '.secrets').exists():
                raise RuntimeError('Release archive unexpectedly includes credentials')
            report['applicationSourceRestoredFromR2'] = True
            restored = create_engine(url.set(database=target), hide_parameters=True)
            with admin.connect() as db:
                db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
                role_created = True
            with restored.begin() as db:
                db.exec_driver_sql(f'GRANT CONNECT ON DATABASE {target} TO {role}')
                db.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO {role}')
                db.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role}')
                db.exec_driver_sql(f'REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM {role}')
                report['migrationRevision'] = db.scalar(text('SELECT version_num FROM alembic_version'))
                report['forcedRlsTables'] = db.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relrowsecurity AND c.relforcerowsecurity"))
                table_names = list(db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")))
                report['restoredTableCount'] = len(table_names)
                # Restore-only file paths can still point at the old host. Rebase
                # exclusively in this disposable DB to the restored upload root.
                paths = db.execute(text('SELECT id,source_file FROM knowledge_items WHERE source_file IS NOT NULL')).all()
                for item_id, old_path in paths:
                    if not old_path:
                        continue
                    marker = '/uploads/'
                    if marker not in old_path:
                        raise RuntimeError('Unrecognized uploaded document path')
                    relative = Path('uploads') / old_path.split(marker, 1)[1]
                    if '..' in relative.parts or not (folder / relative).is_file():
                        raise RuntimeError('Uploaded document missing from recovered backup')
                    db.execute(text('UPDATE knowledge_items SET source_file=:path WHERE id=:id'), {'path': str(folder / relative), 'id': item_id})
                # Freeze background jobs during this read-only drill; do not call
                # providers for queued ingestion or deliver recovered notifications.
                db.execute(text('UPDATE knowledge_jobs SET queued_at=now()+interval \'1 day\''))
            with Session(restored) as db:
                memberships = list(db.scalars(select(AccountMembership).limit(3)))
                probes = []
                for member in memberships:
                    token = secrets.token_urlsafe(32)
                    db.add(AuthSession(token_hash=token_hash(token), account_id=member.account_id,
                        user_id=member.user_id, expires_at=utcnow() + timedelta(minutes=15)))
                    probes.append(token)
                db.commit()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            env = {**os.environ, **settings, 'DATABASE_URL': url.set(database=target, username=role, password=password).render_as_string(hide_password=False),
                   'APP_ENV': 'test', 'UPLOAD_DIR': str(folder / 'uploads'), 'COOKIE_SECURE': 'false'}
            env['NINEROUTER_BASE_URL'] = env.get('NINEROUTER_BASE_URL', '').replace('host.docker.internal', 'localhost')
            with (ROOT / 'artifacts/acceptance-recovery-server.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=recovered_source, env=env, stdout=log, stderr=log)
                base = f'http://127.0.0.1:{port}'
                with httpx.Client(base_url=base, timeout=15) as http:
                    for _ in range(120):
                        if process.poll() is not None:
                            raise RuntimeError('Recovered app failed startup')
                        try:
                            if http.get('/api/health').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.5)
                    else:
                        raise RuntimeError('Recovered app startup timed out')
                    statuses = {'web': http.get('/').status_code, 'ready': http.get('/api/ready').status_code}
                    if not probes:
                        raise RuntimeError('No restored memberships to probe')
                    for index, token in enumerate(probes):
                        for route in ('bootstrap', 'tickets', 'knowledge', 'billing'):
                            statuses[f'member{index}:{route}'] = http.get('/api/' + route, headers={'Cookie': 'support_session=' + token}).status_code
                    if any(status != 200 for status in statuses.values()):
                        raise RuntimeError('Recovered app HTTP probe failed')
                    report['fullApplicationHttpChecks'] = statuses
                    report['restrictedRuntimeRole'] = True
                    # Exercise real outages exclusively in the disposable restore.
                    # Disk exhaustion remains synthetic: never fill a user's disk.
                    spec = importlib.util.spec_from_file_location('recovery_monitor', ROOT / 'scripts/monitor.py')
                    monitor = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(monitor)
                    faults = {}
                    with patch.dict(os.environ, {'DATABASE_URL': env['DATABASE_URL'], 'MONITOR_APP_URL': base}):
                        with admin.connect() as db:
                            db.exec_driver_sql(f'ALTER DATABASE {target} ALLOW_CONNECTIONS false')
                            db.execute(text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()'), {'name': target})
                        try:
                            problems = monitor.inspect_health()
                            faults['actualDatabaseOutageDetected'] = any('Không kết nối được database' in p for p in problems)
                        finally:
                            with admin.connect() as db:
                                db.exec_driver_sql(f'ALTER DATABASE {target} ALLOW_CONNECTIONS true')
                        faults['databaseReadinessRecovers'] = http.get('/api/ready').status_code == 200
                        for signal in ('ai', 'email'):
                            with restored.begin() as db:
                                db.execute(text("INSERT INTO operational_signals(name,consecutive_failures,last_failure) VALUES (:name,4,now()-interval '2 days') ON CONFLICT(name) DO UPDATE SET consecutive_failures=4,last_failure=now()-interval '2 days'"), {'name': signal})
                            faults[signal + 'PersistentFailureDetected'] = any(f'Dịch vụ {signal} lỗi liên tiếp' in p for p in monitor.inspect_health())
                            with restored.begin() as db:
                                db.execute(text('UPDATE operational_signals SET consecutive_failures=0,last_success=now() WHERE name=:name'), {'name': signal})
                            faults[signal + 'RecoveryDetected'] = not any(f'Dịch vụ {signal} lỗi liên tiếp' in p for p in monitor.inspect_health())
                        process.terminate(); process.wait(timeout=15)
                        faults['actualAppStopDetected'] = any('Không kết nối được ứng dụng' in p for p in monitor.inspect_health())
                        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=recovered_source, env=env, stdout=log, stderr=log)
                        for _ in range(120):
                            try:
                                if http.get('/api/ready').status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(.5)
                        faults['actualAppRestartRecovers'] = not any('ứng dụng' in p.lower() for p in monitor.inspect_health())
                    report['isolatedOperationalFaultDrill'] = faults
                    if not all(faults.values()):
                        raise RuntimeError('Operational fault drill failed')
            report['durationSeconds'] = round(time.monotonic() - started, 2)
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        if restored:
            restored.dispose()
        with admin.connect() as db:
            if database_created:
                db.execute(text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()'), {'name': target})
                db.exec_driver_sql(f'DROP DATABASE {target}')
            if role_created:
                db.exec_driver_sql(f'DROP ROLE {role}')
        report['temporaryResourcesRemoved'] = True
        admin.dispose()
        (ROOT / 'artifacts/acceptance-disaster-recovery.json').write_text(json.dumps(report, indent=2))
    print('Full application recovery drill passed; report contains no credentials.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('Recovery drill failed (' + type(exc).__name__ + '); inspect sanitized reports.', file=sys.stderr)
        raise SystemExit(1) from None
