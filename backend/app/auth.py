from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Membership, User, Workspace

password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash("not-a-real-account-password")
Db = Annotated[Session, Depends(get_db)]


def set_session(response: Response, user_id: str) -> None:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    token = jwt.encode({"sub": user_id, "exp": expires, "iat": datetime.now(timezone.utc),
                        "iss": "marketmind", "aud": "marketmind-web"}, settings.jwt_secret, algorithm="HS256")
    response.set_cookie("marketmind_session", token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=settings.session_hours * 3600, path="/")


def current_user(db: Db, marketmind_session: Annotated[str | None, Cookie()] = None) -> User:
    if not marketmind_session:
        raise HTTPException(401, "Sign in to continue")
    try:
        claims = jwt.decode(marketmind_session, get_settings().jwt_secret, algorithms=["HS256"],
                            issuer="marketmind", audience="marketmind-web", options={"require": ["sub", "exp", "iat"]})
        user = db.get(User, claims["sub"])
    except (jwt.PyJWTError, TypeError):
        raise HTTPException(401, "Session expired or invalid") from None
    if user is None:
        raise HTTPException(401, "Session expired or invalid")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def current_workspace(db: Db, user: CurrentUser,
                      x_workspace_id: Annotated[str | None, Header()] = None) -> Workspace:
    query = select(Workspace).join(Membership).where(Membership.user_id == user.id)
    if x_workspace_id:
        query = query.where(Workspace.id == x_workspace_id)
    workspace = db.scalars(query.order_by(Workspace.id)).first()
    if workspace is None:
        raise HTTPException(403, "Workspace access denied")
    return workspace


Tenant = Annotated[Workspace, Depends(current_workspace)]


def enforce_origin(request: Request) -> None:
    # SameSite cookies plus explicit Origin checking protect browser writes.
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in get_settings().allowed_origins:
        raise HTTPException(403, "Origin not allowed")
