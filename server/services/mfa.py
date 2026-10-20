"""RFC 6238 TOTP, encrypted at rest, replay protection and one-use recovery codes."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select

from ..auth_models import AccountMFA


def cipher() -> Fernet:
    try:
        return Fernet(os.environ['APP_ENCRYPTION_KEY'].encode())
    except (KeyError, ValueError):
        raise HTTPException(503, 'Chưa cấu hình khóa mã hóa tài khoản trên máy chủ.') from None


def totp(secret: str, counter: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff
    return f'{number % 1000000:06d}'


def new_setup() -> tuple[str, str]:
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    return secret, cipher().encrypt(secret.encode()).decode()


def verify(record: AccountMFA, code: str, *, recovery: bool = True) -> bool:
    normalized = code.strip().replace('-', '').replace(' ', '').upper()
    if len(normalized) == 6 and normalized.isascii() and normalized.isdigit():
        try:
            secret = cipher().decrypt(record.secret_encrypted.encode()).decode()
        except InvalidToken:
            raise HTTPException(503, 'Không thể đọc khóa xác thực. Liên hệ quản trị hệ thống.') from None
        current = int(time.time()) // 30
        for counter in (current, current-1, current+1):
            if counter > record.last_counter and hmac.compare_digest(totp(secret, counter), normalized):
                record.last_counter = counter
                return True
    elif recovery and len(normalized) == 20:
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        values = json.loads(record.recovery_hashes)
        for value in values:
            if hmac.compare_digest(digest, value):
                values.remove(value)
                record.recovery_hashes = json.dumps(values)
                return True
    return False


def recovery_codes(record: AccountMFA) -> list[str]:
    codes = [secrets.token_hex(10).upper() for _ in range(8)]
    record.recovery_hashes = json.dumps([hashlib.sha256(code.encode()).hexdigest() for code in codes])
    return ['-'.join(code[i:i+5] for i in range(0, 20, 5)) for code in codes]


def require_mfa(db, account_id: str, code: str):
    record = db.scalar(select(AccountMFA).where(AccountMFA.account_id == account_id).with_for_update())
    if record and record.enabled and not verify(record, code):
        raise HTTPException(401, 'Mã xác thực không hợp lệ, đã dùng hoặc đã hết hạn.')
