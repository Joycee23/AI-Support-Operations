"""Request admission limits before multipart parsing and security headers."""
import logging
import asyncio
import os
import tempfile
import uuid
import time
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import database
from .auth_models import AccountMembership, AuthSession
from .models import utcnow
from .services.abuse import consume_limits, limit_setting, resource_slot
from .services.accounts import COOKIE_NAME, token_hash

log = logging.getLogger(__name__)


def production() -> bool:
    value = os.getenv('APP_ENV', 'development').lower()
    if value not in {'development', 'production', 'test'}:
        raise RuntimeError('APP_ENV phải là development, test hoặc production.')
    return value == 'production'


def validate_production():
    if not production():
        return
    public = urlsplit(os.getenv('APP_PUBLIC_URL', ''))
    if public.scheme != 'https' or not public.hostname or public.username or public.password or public.query or public.fragment:
        raise RuntimeError('Production yêu cầu APP_PUBLIC_URL là URL HTTPS hợp lệ.')
    if os.getenv('COOKIE_SECURE', '').lower() != 'true':
        raise RuntimeError('Production yêu cầu COOKIE_SECURE=true.')
    try:
        from cryptography.fernet import Fernet
        Fernet(os.environ['APP_ENCRYPTION_KEY'].encode())
    except (KeyError, ValueError):
        raise RuntimeError('Production yêu cầu APP_ENCRYPTION_KEY là khóa Fernet hợp lệ.') from None
    if '*' in os.getenv('CORS_ORIGINS', '') or '*' in os.getenv('ALLOWED_HOSTS', ''):
        raise RuntimeError('Production không cho phép wildcard CORS/Host.')
    from .services.invitation_email import MailConfig
    mail = MailConfig.from_env()
    if not all((mail.host, mail.username, mail.password, mail.sender)) or mail.security not in ('starttls', 'ssl'):
        raise RuntimeError('Production yêu cầu SMTP TLS để xác minh email và khôi phục tài khoản.')
    from sqlalchemy.engine import make_url
    password = make_url(os.getenv('DATABASE_URL', '')).password or ''
    if len(password) < 24 or password.lower() in ('support', 'password'):
        raise RuntimeError('Production yêu cầu mật khẩu cơ sở dữ liệu riêng, ít nhất 24 ký tự.')


def allowed_hosts() -> list[str]:
    hosts = {h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if h.strip()}
    public = urlsplit(os.getenv('APP_PUBLIC_URL', '')).hostname
    if public:
        hosts.add(public)
    return sorted(hosts)


def _admit(request: Request):
    ip = request.client.host if request.client else 'unknown'
    path = request.url.path
    rules = [('http:ip:' + ip, limit_setting('API_IP_PER_MINUTE', 600), 60)]
    identity = None
    token = request.cookies.get(COOKIE_NAME, '')
    # Session IDs and tenant IDs are resolved server-side. Invalid cookies never
    # grant a different bucket or bypass the IP limit.
    if token and len(token) <= 128:
        with database.SessionLocal() as db:
            session = db.get(AuthSession, token_hash(token))
            if session and session.expires_at > utcnow():
                link = db.get(AccountMembership, session.user_id)
                if link and link.account_id == session.account_id:
                    identity = (link.workspace_id, session.user_id)
                    rules.append(('http:account:' + session.account_id, limit_setting('API_USER_PER_MINUTE', 180), 60))
                    rules.append(('http:workspace:' + link.workspace_id, limit_setting('API_WORKSPACE_PER_MINUTE', 1800), 60))
                    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                        rules.append(('http:write:' + session.account_id, limit_setting('API_WRITES_PER_MINUTE', 40), 60))
                    if path == '/api/knowledge/upload':
                        rules.append(('upload:' + link.workspace_id, limit_setting('UPLOADS_PER_HOUR', 20), 3600))
    consume_limits(rules)
    return identity


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = request.url.path
        api = path.startswith('/api/')
        request_id = uuid.uuid4().hex
        started = time.monotonic()

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                category = path.split('/')[2] if api and len(path.split('/')) > 2 else 'web'
                if category not in {'auth', 'ai', 'billing', 'knowledge', 'tickets', 'bootstrap', 'audit', 'reports', 'admin', 'health', 'web'}:
                    category = 'other'
                log.info('http_request request_id=%s category=%s method=%s status=%s duration_ms=%d',
                         request_id, category, request.method, message['status'], int((time.monotonic()-started)*1000))
                if (path.startswith('/api/ai/tickets/') and path.endswith('/suggest')) or path == '/api/knowledge/draft-faq':
                    if message['status'] >= 500 or 200 <= message['status'] < 300:
                        from .services.operational import record_signal
                        await run_in_threadpool(record_signal, 'ai', message['status'] < 300)
                headers = list(message.get('headers', []))
                headers.extend([
                    (b'x-request-id', request_id.encode()),
                    (b'x-content-type-options', b'nosniff'),
                    (b'cross-origin-resource-policy', b'same-origin'),
                    (b'x-frame-options', b'DENY'),
                    (b'referrer-policy', b'no-referrer'),
                    (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=(), usb=()'),
                    (b'content-security-policy', b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://vietqr.app; connect-src 'self'; frame-src 'none'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"),
                ])
                if production():
                    headers.append((b'strict-transport-security', b'max-age=31536000'))
                if api:
                    headers.append((b'cache-control', b'no-store'))
                message = {**message, 'headers': headers}
            await send(message)

        async def error(status, detail, headers=None):
            await JSONResponse({'detail': detail}, status_code=status, headers=headers)(scope, receive, secure_send)

        identity = None
        if len(scope.get('query_string', b'')) > 8192 or len(path) > 2048:
            return await error(414, 'Đường dẫn yêu cầu quá dài.')
        max_bytes = 11 * 1024 * 1024 if path == '/api/knowledge/upload' else 128 * 1024
        if api:
            if request.headers.get('content-encoding', 'identity').lower() != 'identity':
                return await error(415, 'Không hỗ trợ nội dung yêu cầu được nén.')
            length = request.headers.get('content-length')
            try:
                if length is not None and (int(length) < 0 or int(length) > max_bytes):
                    return await error(413, 'Nội dung yêu cầu vượt giới hạn cho phép.')
            except ValueError:
                return await error(400, 'Content-Length không hợp lệ.')
            # Only liveness is free of SQL. Readiness uses the normal admission
            # limits so a public probe cannot create unlimited database traffic.
            if path != '/api/health' and request.method != 'OPTIONS':
                try:
                    identity = await run_in_threadpool(_admit, request)
                except HTTPException as exc:
                    return await error(exc.status_code, exc.detail, exc.headers)
                except SQLAlchemyError as exc:
                    log.warning('Request admission unavailable request_id=%s type=%s', request_id, type(exc).__name__)
                    return await error(503, 'Hệ thống đang bận. Vui lòng thử lại sau.', {'Retry-After': '5'})
        async def dispatch_body():
            if not api or request.method in ('GET', 'HEAD', 'OPTIONS'):
                return await self.app(scope, receive, secure_send)
            # Bound chunked bodies too, before FastAPI's JSON/multipart parsers run.
            # Spill uploads to an unnamed temporary file rather than retaining 11MB
            # per slow client in memory. The file is closed on every exit path.
            with tempfile.SpooledTemporaryFile(max_size=256 * 1024) as body:
                received = 0
                try:
                    async with asyncio.timeout(30):
                        while True:
                            message = await receive()
                            if message['type'] == 'http.disconnect':
                                return
                            chunk = message.get('body', b'')
                            received += len(chunk)
                            if received > max_bytes:
                                return await error(413, 'Nội dung yêu cầu vượt giới hạn cho phép.')
                            await run_in_threadpool(body.write, chunk)
                            if not message.get('more_body', False):
                                break
                except TimeoutError:
                    return await error(408, 'Hết thời gian nhận nội dung yêu cầu.')
                body.seek(0)
                replay_done = False

                async def replay():
                    nonlocal replay_done
                    if replay_done:
                        return await receive()
                    chunk = await run_in_threadpool(body.read, 64 * 1024)
                    more = body.tell() < received
                    replay_done = not more
                    return {'type': 'http.request', 'body': chunk, 'more_body': more}

                await self.app(scope, replay, secure_send)

        if path == '/api/knowledge/upload' and request.method == 'POST':
            if not identity:
                return await error(401, 'Vui lòng đăng nhập để tải tài liệu.')
            try:
                async with resource_slot(identity[0], identity[1], 'upload'):
                    return await dispatch_body()
            except HTTPException as exc:
                return await error(exc.status_code, exc.detail, exc.headers)
        return await dispatch_body()
