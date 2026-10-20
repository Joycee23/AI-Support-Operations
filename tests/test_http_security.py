import asyncio
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from server.http_security import SecurityMiddleware, validate_production
from server.services.accounts import check_password, hash_password
from server.services.document_worker import extract_bounded
from server.services.mfa import totp
from server.schemas import DraftFAQRequest
from pydantic import ValidationError


class SecurityUnitTests(unittest.TestCase):
    def app(self):
        app = FastAPI()
        app.add_middleware(SecurityMiddleware)
        @app.post('/api/echo')
        async def echo(request: Request):
            return {'bytes': len(await request.body())}
        @app.get('/api/health')
        def health(): return {'ok': True}
        return app

    def test_security_headers(self):
        r = TestClient(self.app()).get('/api/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['x-frame-options'], 'DENY')
        self.assertEqual(r.headers['cross-origin-resource-policy'], 'same-origin')
        self.assertIn("frame-ancestors 'none'", r.headers['content-security-policy'])
        self.assertIn("script-src 'self'", r.headers['content-security-policy'])
        self.assertEqual(r.headers['cache-control'], 'no-store')
        self.assertEqual(len(r.headers['x-request-id']), 32)

    @patch('server.http_security._admit')
    def test_readiness_requires_admission_but_liveness_does_not(self, admit):
        client = TestClient(self.app())
        client.get('/api/health')
        admit.assert_not_called()
        client.get('/api/ready')
        admit.assert_called_once()

    def test_size_and_encoding_rejected_before_parsing(self):
        client = TestClient(self.app())
        self.assertEqual(client.post('/api/echo', content=b'x' * 131073).status_code, 413)
        self.assertEqual(client.post('/api/echo', content=b'x', headers={'Content-Encoding': 'gzip'}).status_code, 415)
        self.assertEqual(client.post('/api/echo', content=b'x', headers={'Content-Length': 'oops'}).status_code, 400)

    @patch('server.http_security._admit')
    def test_chunked_body_cannot_bypass_size_limit(self, admit):
        app = self.app()
        async def run(size):
            messages = [{'type':'http.request', 'body':b'x' * size, 'more_body':False}]
            sent = []
            async def receive(): return messages.pop(0) if messages else {'type':'http.disconnect'}
            async def send(message): sent.append(message)
            await app({'type':'http','method':'POST','path':'/api/echo','raw_path':b'/api/echo','query_string':b'',
                       'headers':[], 'server':('localhost',80),'client':('127.0.0.1',1),'scheme':'http','http_version':'1.1'}, receive, send)
            return next(m['status'] for m in sent if m['type'] == 'http.response.start')
        self.assertEqual(asyncio.run(run(131073)), 413)
        self.assertEqual(asyncio.run(run(50)), 200)

    def test_rfc_totp_vector(self):
        self.assertEqual(totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 1), '287082')

    def test_password_legacy_compatibility_and_new_hash(self):
        salt = 'ab' * 16
        digest = hashlib.scrypt(b'test-password', salt=bytes.fromhex(salt), n=16384,r=8,p=1).hex()
        self.assertTrue(check_password('test-password', f'scrypt${salt}${digest}'))
        value = hash_password('new-test-password')
        self.assertTrue(value.startswith('scrypt-v2$'))
        self.assertTrue(check_password('new-test-password', value))
        self.assertFalse(check_password('wrong', value))
        self.assertFalse(check_password('anything', 'unknown$bad$bad'))

    def test_faq_payload_is_bounded(self):
        with self.assertRaises(ValidationError): DraftFAQRequest(subject='Test', answers={'a':'x'*4001})
        with self.assertRaises(ValidationError): DraftFAQRequest(subject='Test', answers={str(i):'x' for i in range(21)})

    @patch('server.http_security._admit')
    def test_validation_errors_do_not_echo_passwords(self, admit):
        from server.main import validation_error
        from server.routes.auth import Registration
        from fastapi.exceptions import RequestValidationError
        app = self.app()
        app.add_exception_handler(RequestValidationError, validation_error)
        @app.post('/api/registration-test')
        def register(payload: Registration): return {'ok':True}
        secret = 'shortsecret'
        r = TestClient(app).post('/api/registration-test', json={'email':'bad','password':secret})
        self.assertEqual(r.status_code,422)
        self.assertNotIn(secret,r.text)
        self.assertNotIn('input',r.json()['detail'][0])

    def test_host_header_rejected(self):
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app=self.app()
        app.add_middleware(TrustedHostMiddleware,allowed_hosts=['testserver'])
        self.assertEqual(TestClient(app).get('/api/health',headers={'Host':'evil.example'}).status_code,400)

    def test_generation_attempt_budget_spans_model_pools(self):
        from server.services.model_pool import GenerationModelPool, attempt_budget, ModelsUnavailable, GenerationProviderError
        from unittest.mock import AsyncMock
        async def run():
            token=attempt_budget.set([3])
            operation=AsyncMock(side_effect=GenerationProviderError(503))
            try:
                for pool in [GenerationModelPool('a',['b']),GenerationModelPool('c',['d','e'])]:
                    with self.assertRaises(ModelsUnavailable): await pool.call(operation)
                self.assertEqual(operation.await_count,3)
            finally: attempt_budget.reset(token)
        asyncio.run(run())

    @patch.dict(os.environ, {'APP_ENV':'production','APP_PUBLIC_URL':'http://example.com','COOKIE_SECURE':'false'})
    def test_production_rejects_insecure_configuration(self):
        with self.assertRaises(RuntimeError): validate_production()

    @patch.dict(os.environ, {'APP_ENV':'production','APP_PUBLIC_URL':'https://example.com','COOKIE_SECURE':'true',
                            'DATABASE_URL':'postgresql+psycopg://app:random-long-test-password-only@db/app','ALLOWED_HOSTS':'example.com','CORS_ORIGINS':'https://example.com',
                            'SMTP_HOST':'smtp.example.com','SMTP_USERNAME':'test','SMTP_PASSWORD':'test-only','SMTP_FROM_EMAIL':'test@example.com','SMTP_SECURITY':'starttls'})
    def test_production_accepts_valid_configuration(self):
        with patch.dict(os.environ, {'APP_ENCRYPTION_KEY':Fernet.generate_key().decode()}): validate_production()
