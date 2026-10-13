"""Atomic database counters bound the cost of public authentication endpoints."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.models import AuthRateLimit


def limit_auth(db, request: Request, email: str, *, registration: bool) -> None:
    settings = get_settings()
    if settings.environment != "production":
        return
    # Never trust caller-supplied X-Forwarded-For. The network bucket can cover
    # several users behind Railway/Next.js; edge rate limits can add true-IP controls.
    host = request.client.host if request.client else "unknown"
    kind = "register" if registration else "login"
    window = 3600 if registration else 900
    limit = 30 if registration else 200
    buckets = [(f"{kind}:network:{host}", limit), (f"{kind}:account:{email}", 10)]
    now = datetime.now(timezone.utc)
    for identity, maximum in buckets:
        key = hmac.new(settings.jwt_secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
        expired = AuthRateLimit.expires_at <= now
        query = insert(AuthRateLimit).values(key=key, attempts=1, expires_at=now + timedelta(seconds=window))
        query = query.on_conflict_do_update(index_elements=[AuthRateLimit.key], set_={
            "attempts": case((expired, 1), else_=AuthRateLimit.attempts + 1),
            "expires_at": case((expired, now + timedelta(seconds=window)), else_=AuthRateLimit.expires_at),
        }).returning(AuthRateLimit.attempts)
        count = db.scalar(query)
        db.execute(delete(AuthRateLimit).where(AuthRateLimit.expires_at < now - timedelta(hours=1)))
        db.commit()
        if count > maximum:
            raise HTTPException(429, "Too many authentication attempts. Try again later.",
                                headers={"Retry-After": str(window)})
