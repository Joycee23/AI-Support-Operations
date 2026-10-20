"""Shared PostgreSQL limits: survive worker restarts and never trust client IDs."""
import hashlib
import math
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from starlette.concurrency import run_in_threadpool

from .. import database
from ..auth_models import AuthRateLimit, ResourceLease
from ..models import utcnow


def limit_setting(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise RuntimeError(f'{name} phải lớn hơn 0.')
    return value


def _lock(db, key: str):
    digest = hashlib.sha256(key.encode()).digest()
    db.execute(text("SET LOCAL lock_timeout = '2s'"))
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
               {'key': int.from_bytes(digest[:8], 'big', signed=True)})


def consume_limits(rules: list[tuple[str, int, int]], *, amount: int = 1):
    """Atomically charge all limits or none; rejected requests never call providers."""
    now = utcnow()
    with database.SessionLocal() as db:
        for key, maximum, seconds in sorted(rules):
            _lock(db, key)
            digest = hashlib.sha256(key.encode()).hexdigest()
            bucket = db.get(AuthRateLimit, digest)
            if bucket is None:
                bucket = AuthRateLimit(key_hash=digest, started_at=now, attempts=0)
                db.add(bucket)
            elif bucket.started_at <= now - timedelta(seconds=seconds):
                bucket.started_at, bucket.attempts = now, 0
            if bucket.attempts + amount > maximum:
                retry = max(1, math.ceil((bucket.started_at + timedelta(seconds=seconds) - now).total_seconds()))
                raise HTTPException(429, 'Đã đạt hạn mức yêu cầu. Vui lòng thử lại sau.',
                                    headers={'Retry-After': str(retry)})
            bucket.attempts += amount
        # Keep at most a little over one day's inactive buckets, including IPs.
        if secrets.randbelow(100) == 0:
            db.execute(delete(AuthRateLimit).where(AuthRateLimit.started_at < now - timedelta(days=2)))
        db.commit()


def _acquire(workspace_id: str, user_id: str, resource: str, ttl: int) -> str:
    now = utcnow()
    with database.SessionLocal() as db:
        # Lock in one consistent order across every process/server.
        _lock(db, 'lease:' + resource)
        db.execute(delete(ResourceLease).where(ResourceLease.expires_at <= now))
        rows = list(db.scalars(select(ResourceLease).where(ResourceLease.resource == resource)))
        global_max = limit_setting('AI_GLOBAL_CONCURRENCY', 12) if resource == 'generation' else limit_setting('INGEST_GLOBAL_CONCURRENCY', 3)
        workspace_max = limit_setting('AI_WORKSPACE_CONCURRENCY', 3) if resource == 'generation' else 1
        user_max = limit_setting('AI_USER_CONCURRENCY', 1) if resource == 'generation' else 1
        if len(rows) >= global_max or sum(r.workspace_id == workspace_id for r in rows) >= workspace_max or sum(r.user_id == user_id for r in rows) >= user_max:
            raise HTTPException(429, 'Hệ thống đang xử lý tác vụ khác. Vui lòng thử lại sau.', headers={'Retry-After': '10'})
        token = secrets.token_hex(24)
        db.add(ResourceLease(id=token, resource=resource, workspace_id=workspace_id,
                             user_id=user_id, expires_at=now + timedelta(seconds=ttl)))
        db.commit()
        return token


def _release(token: str):
    with database.SessionLocal() as db:
        db.execute(delete(ResourceLease).where(ResourceLease.id == token))
        db.commit()


@asynccontextmanager
async def resource_slot(workspace_id: str, user_id: str, resource: str = 'generation'):
    token = await run_in_threadpool(_acquire, workspace_id, user_id, resource, 150 if resource == 'generation' else 360)
    from .model_pool import attempt_budget
    budget = attempt_budget.set([limit_setting('AI_MAX_PROVIDER_ATTEMPTS', 4)]) if resource == 'generation' else None
    try:
        yield
    finally:
        if budget is not None:
            attempt_budget.reset(budget)
        await run_in_threadpool(_release, token)


async def charge_generation(user):
    await run_in_threadpool(consume_limits, [
        ('ai:user:' + user.id, limit_setting('AI_USER_PER_MINUTE', 5), 60),
        ('ai:workspace:' + user.workspace_id, limit_setting('AI_WORKSPACE_PER_MINUTE', 20), 60),
        ('ai:daily:' + user.workspace_id, limit_setting('AI_WORKSPACE_PER_DAY', 300), 86400),
        ('ai:global:daily', limit_setting('AI_GLOBAL_PER_DAY', 5000), 86400),
    ])
