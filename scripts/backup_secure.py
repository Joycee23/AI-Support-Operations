"""Stream PostgreSQL or uploaded documents directly into age encryption.

No plaintext dump is written to disk. Requires the official age CLI.
Private identity keys must be stored separately from the server/backups.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['database', 'files', 'application'], default='database')
    parser.add_argument('--release-stream', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'backups')
    args = parser.parse_args()
    if args.release_stream:
        # Explicit allowlist: never archive .env, identity keys, data, logs,
        # dependencies, browser artifacts or source-control credentials.
        roots = ['server', 'src', 'public', 'dist', 'migrations', 'scripts', 'deploy',
                 'requirements.txt', 'requirements-ops.txt', 'package.json',
                 'package-lock.json', 'Dockerfile', 'docker-compose.yml',
                 'alembic.ini', 'index.html', 'vite.config.ts', 'tsconfig.json',
                 '.env.example', 'README.md', 'OPERATIONS.md', 'SECURITY.md', 'RAILWAY_DEPLOY.md', 'railway.json']
        with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
            for name in roots:
                source = ROOT / name
                paths = sorted(source.rglob('*')) if source.is_dir() else [source]
                for path in paths:
                    if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts or path.suffix == '.pyc':
                        continue
                    archive.add(path, arcname='application/' + str(path.relative_to(ROOT)), recursive=False)
        return
    recipient = os.getenv('BACKUP_AGE_RECIPIENT', '')
    if not recipient.startswith('age1') or not shutil.which('age'):
        raise SystemExit('Cần age CLI và BACKUP_AGE_RECIPIENT. Xem SECURITY.md.')
    os.umask(0o077)
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output_dir / f'{args.kind}-{stamp}.age'
    partial = output.with_suffix('.partial')
    command = ['docker', 'compose', 'exec', '-T']
    if args.kind == 'database':
        command += ['db', 'pg_dump', '-U', os.getenv('POSTGRES_USER', 'support'), '-d', os.getenv('POSTGRES_DB', 'support_ops'),
                    '--format=custom', '--no-owner', '--no-acl', '--exclude-schema=test_*']
    elif args.kind == 'files':
        command += ['app', 'tar', '-czf', '-', '-C', '/app/data', 'uploads']
    else:
        command = [sys.executable, str(Path(__file__).resolve()), '--release-stream']
    environment = None
    if os.getenv('BACKUP_MODE', 'compose') == 'direct':
        if args.kind == 'database':
            from sqlalchemy.engine import make_url
            url = make_url(os.environ['BACKUP_DATABASE_URL'])
            # Credentials travel in the child environment, never argv/logs.
            environment = {**os.environ, 'PGHOST': url.host or '', 'PGPORT': str(url.port or 5432),
                'PGUSER': url.username or '', 'PGPASSWORD': url.password or '', 'PGDATABASE': url.database or '',
                'PGCONNECT_TIMEOUT': '10', 'PGSSLMODE': str(url.query.get('sslmode', 'prefer'))}
            command = ['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--exclude-schema=test_*']
        elif args.kind == 'files':
            uploads = Path(os.environ['UPLOAD_DIR']).resolve()
            command = ['tar', '-czf', '-', '-C', str(uploads.parent), uploads.name]
    producer = None
    try:
        with tempfile.TemporaryFile() as errors:
            producer = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=errors, env=environment)
            encrypted = subprocess.run(['age', '--encrypt', '--recipient', recipient, '--output', str(partial)],
                                       stdin=producer.stdout, stderr=errors, timeout=300)
            producer.stdout.close()
            status = producer.wait(timeout=30)
            if status or encrypted.returncode:
                raise RuntimeError('Backup không hoàn thành; không tạo tệp thành công giả.')
        partial.chmod(0o600)
        partial.rename(output)
        print(output)
    finally:
        if producer and producer.poll() is None:
            producer.kill(); producer.wait()
        partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
