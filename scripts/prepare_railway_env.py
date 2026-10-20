"""Prepare private Railway variable files without displaying any credentials.

Run locally. The existing .env stays unchanged. Never commit the generated files.
"""
import getpass
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
from dotenv import dotenv_values, set_key
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


def main():
    local = dotenv_values(ROOT/'.env')
    url = make_url(getpass.getpass('Railway PRIVATE database URL (hidden input): ').strip())
    if url.drivername not in {'postgresql', 'postgres', 'postgresql+psycopg'} or not url.host or not url.password:
        raise SystemExit('Use the PostgreSQL private URL, including password and database.')
    domain = input('Public app hostname, without https://: ').strip().lower()
    parsed = urlsplit('https://'+domain)
    if not domain or parsed.hostname != domain or '/' in domain or ':' in domain or '.' not in domain:
        raise SystemExit('Use only the public hostname.')
    url = url.set(drivername='postgresql+psycopg')
    runtime = url.set(username='support_app', password=secrets.token_urlsafe(36))
    reader = url.set(username='support_backup', password=secrets.token_urlsafe(36))
    app = {k: str(v) for k,v in local.items() if v is not None and k in dotenv_values(ROOT/'.env.example')}
    for key in list(app):
        if ('DATABASE' in key or key.startswith('POSTGRES_') or key.startswith('DOCKER_')
            or key in {'APP_DOMAIN','PORT','VITE_API_URL'}): app.pop(key)
    app.update(APP_ENV='production', COOKIE_SECURE='true', APP_PUBLIC_URL='https://'+domain,
               CORS_ORIGINS='https://'+domain,
               ALLOWED_HOSTS=domain+',healthcheck.railway.app,localhost,127.0.0.1',
               DATABASE_URL=runtime.render_as_string(hide_password=False), PORT='8000',
               UPLOAD_DIR='/app/data/uploads', OPS_STATE_DIR='/app/data/ops',
               BACKUP_MODE='direct', BACKUP_KINDS='files,application', OPS_ENABLED='true',
               RAILWAY_RUN_UID='0')
    required = ['APP_ENCRYPTION_KEY','GEMINI_API_KEY','SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD',
                'SMTP_FROM_EMAIL','MONITOR_ALERT_EMAIL','BACKUP_AGE_RECIPIENT','BACKUP_S3_ENDPOINT',
                'BACKUP_S3_BUCKET','BACKUP_S3_ACCESS_KEY_ID','BACKUP_S3_SECRET_ACCESS_KEY']
    missing = [key for key in required if not app.get(key)]
    if missing:
        raise SystemExit('Fill required local configuration first: '+', '.join(missing))
    if app.get('AI_PROVIDER')=='9router':
        router=urlsplit(app.get('NINEROUTER_BASE_URL',''))
        if router.scheme!='https' or router.hostname in {'localhost','127.0.0.1','host.docker.internal'}:
            raise SystemExit('9router needs a reachable HTTPS endpoint. Configure it in .env, or explicitly select Gemini before retrying.')
    app.pop('NINEROUTER_DOCKER_BASE_URL',None)
    migration = {'DATABASE_MIGRATION_URL':url.render_as_string(hide_password=False),
                 'RUNTIME_DATABASE_URL':runtime.render_as_string(hide_password=False),
                 'BACKUP_DATABASE_URL':reader.render_as_string(hide_password=False)}
    backup = {k:v for k,v in app.items() if k.startswith('BACKUP_S3_') or k=='BACKUP_AGE_RECIPIENT'}
    backup.update(BACKUP_DATABASE_URL=reader.render_as_string(hide_password=False),
                  BACKUP_MODE='direct', BACKUP_KINDS='database',
                  OPS_STATE_DIR='/app/data/ops', RAILWAY_RUN_UID='0')
    outputs={'railway-app.env':app,'railway-migrate.env':migration,'railway-backup.env':backup}
    folder=ROOT/'.secrets';folder.mkdir(mode=0o700,exist_ok=True)
    if any((folder/name).exists() for name in outputs):
        raise SystemExit('Railway files already exist. Reuse them; do not regenerate database passwords for existing roles.')
    os.umask(0o077)
    for name,values in outputs.items():
        path=folder/name
        path.touch(mode=0o600)
        for key,value in values.items():set_key(path,key,value,quote_mode='always')
        path.chmod(0o600)
    print('Created .secrets/railway-app.env, railway-migrate.env, railway-backup.env (0600).')
    print('Import each file only into its matching Railway service. No credentials displayed; local .env unchanged.')


if __name__=='__main__':
    try:main()
    except (ValueError, KeyError):raise SystemExit('Invalid configuration; no credential values displayed.') from None
