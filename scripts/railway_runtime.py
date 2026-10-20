"""One Railway replica: supervised HTTP process and bounded local operations jobs.

The document dispatcher already lives in server.main. No second worker is needed.
An external uptime monitor is still needed if this whole container stops.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def next_backup(now):
    # 19:00 UTC = 02:00 Asia/Ho_Chi_Minh the following day.
    target = now.replace(hour=19, minute=0, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def main():
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535')
    os.environ.setdefault('BACKUP_MODE', 'direct')
    os.environ.setdefault('OPS_STATE_DIR', '/app/data/ops')
    os.environ.setdefault('UPLOAD_DIR', '/app/data/uploads')
    os.environ['MONITOR_APP_URL'] = f'http://127.0.0.1:{port}'
    # Forwarded IPs are not trusted by default. Never use '*' on a public ingress.
    command = [sys.executable, '-m', 'uvicorn', 'server.main:app', '--host', '0.0.0.0',
               '--port', str(port), '--no-proxy-headers', '--limit-concurrency', '64',
               '--timeout-keep-alive', '5', '--backlog', '128', '--no-access-log']
    stopping = False
    active = None
    web = subprocess.Popen(command, cwd=ROOT)

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if web.poll() is None:
            web.terminate()
        if active is not None and active.poll() is None:
            os.killpg(active.pid, signal.SIGTERM)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    enabled = os.getenv('OPS_ENABLED', 'false').lower() == 'true'
    next_monitor = time.monotonic() + 300
    backup_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    deadline = 0
    try:
        while not stopping and web.poll() is None:
            now = datetime.now(timezone.utc)
            if active is not None:
                result = active.poll()
                if result is not None:
                    print(f'Operations job finished with exit code {result}.', flush=True)
                    active = None
                elif time.monotonic() > deadline:
                    os.killpg(active.pid, signal.SIGKILL); active.wait(); active = None
                    print('Operations job timed out.', flush=True)
            if enabled and active is None:
                job = None
                if now >= backup_at:
                    job = 'backup_cycle.py'; backup_at = next_backup(now)
                elif time.monotonic() >= next_monitor:
                    job = 'monitor.py'; next_monitor = time.monotonic() + 300
                if job:
                    active = subprocess.Popen([sys.executable, str(ROOT/'scripts'/job)], cwd=ROOT, start_new_session=True)
                    deadline = time.monotonic() + (1200 if job == 'backup_cycle.py' else 120)
            time.sleep(1)
    finally:
        for child in (web, active):
            if child is not None and child.poll() is None:
                if child is active: os.killpg(child.pid, signal.SIGTERM)
                else: child.terminate()
                try: child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if child is active: os.killpg(child.pid, signal.SIGKILL)
                    else: child.kill()
                    child.wait()
    return web.returncode if web.returncode is not None and web.returncode >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
