from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import SecurityRateLimit
from app.settings import settings


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int
    block_seconds: int

    def normalized(self) -> "RateLimitPolicy":
        return RateLimitPolicy(
            limit=max(1, int(self.limit)),
            window_seconds=max(1, int(self.window_seconds)),
            block_seconds=max(1, int(self.block_seconds)),
        )


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    remaining: int = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _subject_hash(scope: str, subject: str) -> str:
    normalized_scope = str(scope or "").strip().lower()
    normalized_subject = str(subject or "unknown").strip().lower() or "unknown"
    secret = str(settings.JWT_SECRET or "").encode("utf-8")
    message = f"{normalized_scope}|{normalized_subject}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _advisory_lock_id(scope: str, subject_hash: str) -> int:
    digest = hashlib.sha256(f"{scope}|{subject_hash}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _lock_subject(db: Session, *, scope: str, subject_hash: str) -> None:
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(_advisory_lock_id(scope, subject_hash))))


def _load_bucket(db: Session, *, scope: str, subject_hash: str) -> SecurityRateLimit | None:
    return db.execute(
        select(SecurityRateLimit).where(
            SecurityRateLimit.scope == scope,
            SecurityRateLimit.subject_hash == subject_hash,
        )
    ).scalar_one_or_none()


def _retry_after(blocked_until: datetime | None, *, now: datetime) -> int:
    blocked = _as_utc(blocked_until)
    if blocked is None or blocked <= now:
        return 0
    return max(1, int(math.ceil((blocked - now).total_seconds())))


def _prepare_bucket(
    db: Session,
    *,
    scope: str,
    subject: str,
    policy: RateLimitPolicy,
    now: datetime,
) -> tuple[SecurityRateLimit | None, str, RateLimitPolicy]:
    normalized_scope = str(scope or "").strip().lower()
    normalized_policy = policy.normalized()
    subject_hash = _subject_hash(normalized_scope, subject)
    _lock_subject(db, scope=normalized_scope, subject_hash=subject_hash)
    bucket = _load_bucket(db, scope=normalized_scope, subject_hash=subject_hash)
    if bucket is not None:
        blocked_until = _as_utc(bucket.blocked_until)
        window_started = _as_utc(bucket.window_started_at) or now
        if blocked_until is not None and blocked_until <= now:
            bucket.blocked_until = None
        if window_started + timedelta(seconds=normalized_policy.window_seconds) <= now:
            bucket.window_started_at = now
            bucket.attempt_count = 0
            bucket.blocked_until = None
    return bucket, subject_hash, normalized_policy


def check_rate_limit(
    db: Session,
    *,
    scope: str,
    subject: str,
    policy: RateLimitPolicy,
    now: datetime | None = None,
) -> RateLimitDecision:
    current = _as_utc(now) or utcnow()
    bucket, _, normalized_policy = _prepare_bucket(
        db,
        scope=scope,
        subject=subject,
        policy=policy,
        now=current,
    )
    if bucket is None:
        return RateLimitDecision(allowed=True, remaining=normalized_policy.limit)
    retry_after = _retry_after(bucket.blocked_until, now=current)
    if retry_after:
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after, remaining=0)
    return RateLimitDecision(
        allowed=True,
        remaining=max(0, normalized_policy.limit - int(bucket.attempt_count or 0)),
    )


def register_rate_limit_failure(
    db: Session,
    *,
    scope: str,
    subject: str,
    policy: RateLimitPolicy,
    now: datetime | None = None,
) -> RateLimitDecision:
    current = _as_utc(now) or utcnow()
    bucket, subject_hash, normalized_policy = _prepare_bucket(
        db,
        scope=scope,
        subject=subject,
        policy=policy,
        now=current,
    )
    if bucket is None:
        bucket = SecurityRateLimit(
            scope=str(scope or "").strip().lower(),
            subject_hash=subject_hash,
            window_started_at=current,
            attempt_count=0,
        )
        db.add(bucket)
    retry_after = _retry_after(bucket.blocked_until, now=current)
    if retry_after:
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after, remaining=0)

    bucket.attempt_count = int(bucket.attempt_count or 0) + 1
    bucket.updated_at = current
    if bucket.attempt_count >= normalized_policy.limit:
        bucket.blocked_until = current + timedelta(seconds=normalized_policy.block_seconds)
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=normalized_policy.block_seconds,
            remaining=0,
        )
    return RateLimitDecision(
        allowed=True,
        remaining=max(0, normalized_policy.limit - bucket.attempt_count),
    )


def consume_rate_limit(
    db: Session,
    *,
    scope: str,
    subject: str,
    policy: RateLimitPolicy,
    now: datetime | None = None,
) -> RateLimitDecision:
    current = _as_utc(now) or utcnow()
    bucket, subject_hash, normalized_policy = _prepare_bucket(
        db,
        scope=scope,
        subject=subject,
        policy=policy,
        now=current,
    )
    if bucket is None:
        bucket = SecurityRateLimit(
            scope=str(scope or "").strip().lower(),
            subject_hash=subject_hash,
            window_started_at=current,
            attempt_count=0,
        )
        db.add(bucket)
    retry_after = _retry_after(bucket.blocked_until, now=current)
    if retry_after:
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after, remaining=0)
    if int(bucket.attempt_count or 0) >= normalized_policy.limit:
        bucket.blocked_until = current + timedelta(seconds=normalized_policy.block_seconds)
        bucket.updated_at = current
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=normalized_policy.block_seconds,
            remaining=0,
        )

    bucket.attempt_count = int(bucket.attempt_count or 0) + 1
    bucket.updated_at = current
    return RateLimitDecision(
        allowed=True,
        remaining=max(0, normalized_policy.limit - bucket.attempt_count),
    )


def reset_rate_limit(db: Session, *, scope: str, subject: str) -> None:
    normalized_scope = str(scope or "").strip().lower()
    subject_hash = _subject_hash(normalized_scope, subject)
    _lock_subject(db, scope=normalized_scope, subject_hash=subject_hash)
    db.execute(
        delete(SecurityRateLimit).where(
            SecurityRateLimit.scope == normalized_scope,
            SecurityRateLimit.subject_hash == subject_hash,
        )
    )
