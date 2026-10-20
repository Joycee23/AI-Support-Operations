"""Create missing encryption keys without printing/rotating existing keys."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-local-backup-key', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    os.umask(0o077)
    env = root / '.env'
    if not env.exists():
        raise SystemExit('Tạo .env từ .env.example trước.')
    values = dotenv_values(env)
    if not values.get('APP_ENCRYPTION_KEY'):
        set_key(str(env), 'APP_ENCRYPTION_KEY', Fernet.generate_key().decode())
    else:
        Fernet(values['APP_ENCRYPTION_KEY'].encode())
    env.chmod(0o600)
    if args.with_local_backup_key and not values.get('BACKUP_AGE_RECIPIENT'):
        if not shutil.which('age-keygen'):
            raise SystemExit('Đã cấu hình khóa ứng dụng. Cài age để tạo khóa sao lưu.')
        directory = root / '.secrets'
        directory.mkdir(mode=0o700, exist_ok=True)
        identity = directory / 'backup-age-key.txt'
        if not identity.exists():
            subprocess.run(['age-keygen', '-o', str(identity)], check=True, capture_output=True)
        identity.chmod(0o600)
        recipient = subprocess.run(['age-keygen', '-y', str(identity)], check=True, capture_output=True, text=True).stdout.strip()
        set_key(str(env), 'BACKUP_AGE_RECIPIENT', recipient)
    print('Đã kiểm tra/tạo khóa còn thiếu. Không hiển thị hoặc xoay khóa hiện có.')


if __name__ == '__main__':
    main()
