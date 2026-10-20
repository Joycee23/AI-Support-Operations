"""Restore an encrypted backup into a NEW restore_* database, never overwrite live data."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--target-db', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'restore_[a-z0-9_]{1,50}', args.target_db):
        raise SystemExit('Chỉ cho phép tên database mới bắt đầu bằng restore_.')
    user = os.getenv('POSTGRES_USER', 'support')
    base = ['docker', 'compose', 'exec', '-T', 'db']
    # createdb fails if the target already exists. Existing databases are never
    # cleaned or overwritten, even if a restore was interrupted.
    subprocess.run(base + ['createdb', '-U', user, args.target_db], cwd=ROOT, check=True, capture_output=True)
    decrypt = None
    try:
        with tempfile.TemporaryFile() as errors:
            decrypt = subprocess.Popen(['age', '--decrypt', '--identity', str(args.identity), str(args.backup)],
                                       stdout=subprocess.PIPE, stderr=errors)
            restore = subprocess.run(base + ['pg_restore', '-U', user, '--dbname', args.target_db,
                '--no-owner', '--no-acl', '--single-transaction', '--exit-on-error'], stdin=decrypt.stdout,
                stderr=errors, stdout=subprocess.DEVNULL, cwd=ROOT, timeout=300)
            decrypt.stdout.close()
            status = decrypt.wait(timeout=30)
            if status or restore.returncode:
                raise RuntimeError('Kiểm tra phục hồi thất bại. Database đích được giữ để kiểm tra; dữ liệu đang chạy không thay đổi.')
        print('Restored successfully into ' + args.target_db)
    finally:
        if decrypt and decrypt.poll() is None:
            decrypt.kill(); decrypt.wait()


if __name__ == '__main__':
    main()
