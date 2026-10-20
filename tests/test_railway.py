"""Railway packaging/operations contracts; no cloud, SMTP or real provider calls."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class RailwayDeploymentTests(unittest.TestCase):
    def test_backup_schedule_is_two_am_vietnam(self):
        module=script('railway_runtime')
        now=datetime(2026,10,20,18,0,tzinfo=timezone.utc)
        self.assertEqual(module.next_backup(now),now.replace(hour=19))
        self.assertEqual(module.next_backup(now.replace(hour=19)).day,21)

    def test_config_uses_ready_and_separate_jobs(self):
        config=json.loads((ROOT/'railway.json').read_text())
        self.assertEqual(config['deploy']['healthcheckPath'],'/api/ready')
        self.assertTrue((ROOT/config['build']['dockerfilePath']).is_file())
        for name in ('migrate','backup'):
            job=json.loads((ROOT/'deploy/railway'/f'{name}.json').read_text())
            self.assertNotIn('healthcheckPath',job['deploy'])
            self.assertEqual(job['deploy']['restartPolicyType'],'NEVER')

    def test_generated_environment_separates_database_privileges(self):
        module=script('prepare_railway_env')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            settings={key:'synthetic-value' for key in ['APP_ENCRYPTION_KEY','GEMINI_API_KEY',
                'SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM_EMAIL','MONITOR_ALERT_EMAIL',
                'BACKUP_AGE_RECIPIENT','BACKUP_S3_ENDPOINT','BACKUP_S3_BUCKET',
                'BACKUP_S3_ACCESS_KEY_ID','BACKUP_S3_SECRET_ACCESS_KEY']}
            settings.update(AI_PROVIDER='gemini',DATABASE_URL='local-db-not-exported',
                            DATABASE_MIGRATION_URL='local-admin-not-exported')
            (root/'.env.example').write_text('\n'.join(k+'=' for k in settings))
            (root/'.env').write_text('\n'.join(k+'='+v for k,v in settings.items()))
            with patch.object(module,'ROOT',root),patch.object(module.getpass,'getpass',return_value='postgresql://postgres:synthetic-private-password@postgres.railway.internal:5432/support_ops'),patch('builtins.input',return_value='test.up.railway.app'):
                module.main()
                with self.assertRaises(SystemExit):module.main()
            app=dotenv_values(root/'.secrets/railway-app.env')
            migration=dotenv_values(root/'.secrets/railway-migrate.env')
            backup=dotenv_values(root/'.secrets/railway-backup.env')
            self.assertNotIn('DATABASE_MIGRATION_URL',app)
            self.assertNotIn('BACKUP_DATABASE_URL',app)
            self.assertEqual(app['DATABASE_URL'],migration['RUNTIME_DATABASE_URL'])
            self.assertEqual(backup['BACKUP_DATABASE_URL'],migration['BACKUP_DATABASE_URL'])
            self.assertNotIn('APP_ENCRYPTION_KEY',backup)
            self.assertNotIn('GEMINI_API_KEY',migration)
            self.assertEqual(app['BACKUP_KINDS'],'files,application')
            self.assertEqual(backup['BACKUP_KINDS'],'database')
            for path in (root/'.secrets').iterdir():self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_direct_monitor_does_not_call_docker(self):
        module=script('monitor')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
            'BACKUP_MODE':'direct','OPS_STATE_DIR':folder,'UPLOAD_DIR':folder,
            'DATABASE_URL':'postgresql+psycopg://synthetic@localhost/test','MONITOR_MIN_FREE_BYTES':'1'}),patch.object(module.httpx,'get') as http,patch.object(module,'create_engine') as engine,patch.object(module.subprocess,'run') as run,patch.object(module.shutil,'disk_usage',return_value=SimpleNamespace(free=9000,used=1000,total=10000)):
            http.return_value.status_code=200;http.return_value.json.return_value={'ok':True}
            engine.return_value.connect.return_value.__enter__.return_value.execute.return_value=[]
            backups=Path(folder)/'backups';backups.mkdir()
            (backups/'status.json').write_text(json.dumps({'createdAt':datetime.now(timezone.utc).isoformat(),'offsiteVerified':True}))
            self.assertEqual(module.inspect_health(),[])
            run.assert_not_called()


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Disposable PostgreSQL test connection required')
class RailwayDatabaseRolesTests(unittest.TestCase):
    def test_provision_runtime_and_read_only_backup(self):
        import secrets
        import subprocess
        import sys
        import uuid
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        suffix=uuid.uuid4().hex[:12]
        name='test_railway_'+suffix
        runtime_name='qa_app_'+suffix
        backup_name='qa_backup_'+suffix
        source=make_url(os.environ['TEST_DATABASE_URL'])
        admin=create_engine(source.set(database='postgres'),isolation_level='AUTOCOMMIT',hide_parameters=True)
        engines=[]
        try:
            with admin.connect() as db:db.exec_driver_sql('CREATE DATABASE '+name)
            base=source.set(database=name)
            runtime=base.set(username=runtime_name,password=secrets.token_urlsafe(32))
            reader=base.set(username=backup_name,password=secrets.token_urlsafe(32))
            env={**os.environ,'DATABASE_MIGRATION_URL':base.render_as_string(hide_password=False),
                 'RUNTIME_DATABASE_URL':runtime.render_as_string(hide_password=False),
                 'BACKUP_DATABASE_URL':reader.render_as_string(hide_password=False)}
            for _ in range(2):
                result=subprocess.run([sys.executable,str(ROOT/'scripts/provision_database.py')],env=env,cwd=ROOT,capture_output=True,timeout=60)
                self.assertEqual(result.returncode,0,'Provision script failed; credential-bearing output suppressed')
            app=create_engine(runtime,hide_parameters=True);engines.append(app)
            backup=create_engine(reader,hide_parameters=True);engines.append(backup)
            with app.connect() as db:
                flags=db.execute(text('SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')).first()
                self.assertFalse(any(flags))
                self.assertFalse(db.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')")))
                self.assertFalse(db.scalar(text("SELECT has_table_privilege(current_user,'alembic_version','UPDATE')")))
                self.assertEqual(db.scalar(text('SELECT count(*) FROM tickets')),0)
            with backup.connect() as db:
                self.assertTrue(db.scalar(text('SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user')))
                self.assertEqual(db.scalar(text('SHOW default_transaction_read_only')),'on')
                self.assertTrue(db.scalar(text("SELECT has_table_privilege(current_user,'tickets','SELECT')")))
                self.assertFalse(db.scalar(text("SELECT has_table_privilege(current_user,'tickets','INSERT')")))
        finally:
            for engine in engines:engine.dispose()
            with admin.connect() as db:
                db.exec_driver_sql('DROP DATABASE IF EXISTS '+name+' WITH (FORCE)')
                db.exec_driver_sql('DROP ROLE IF EXISTS '+runtime_name)
                db.exec_driver_sql('DROP ROLE IF EXISTS '+backup_name)
            admin.dispose()
