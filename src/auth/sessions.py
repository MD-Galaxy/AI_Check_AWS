"""Session cookie lifecycle: mint, set, read, and clear (MIGRATION_PLAN.md §3.1).

Session tokens are opaque random strings (never stored raw — only their
sha256 hash lives in ``user_sessions.token_hash``, per the plan). The
"pending registration" cookie is a separate, short-lived, HMAC-signed value
carrying a user id across the registration wizard's steps (§3.2) — it is
*not* a login session.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

from src.auth.security import sign_value, unsign_value
from src.config import BASE_PATH, Settings
from src.db.repository import Repository

SESSION_COOKIE_NAME = "session_id"
PENDING_COOKIE_NAME = "pending_registration"
PENDING_COOKIE_PATH = f"{BASE_PATH}/register"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session_for_user(
    repo: Repository, user: dict, request: Request, settings: Settings
) -> str:
    """Create a DB session row for ``user`` and return the raw cookie token."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    await repo.create_session(
        user_id=user["id"],
        token_hash=_hash_token(token),
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


async def get_current_user(request: Request) -> dict | None:
    """Resolve the logged-in user from the session cookie, if any and valid."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    repo: Repository = request.app.state.db
    return await repo.get_session_user(_hash_token(token))


async def revoke_current_session(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return
    repo: Repository = request.app.state.db
    await repo.delete_session(_hash_token(token))


def set_pending_cookie(response: Response, pending_user_id: str, settings: Settings) -> None:
    response.set_cookie(
        PENDING_COOKIE_NAME,
        sign_value(pending_user_id, settings.secret_key),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path=PENDING_COOKIE_PATH,
    )


def get_pending_user_id(request: Request, settings: Settings) -> str | None:
    token = request.cookies.get(PENDING_COOKIE_NAME)
    if not token:
        return None
    return unsign_value(token, settings.secret_key)


def clear_pending_cookie(response: Response) -> None:
    response.delete_cookie(PENDING_COOKIE_NAME, path=PENDING_COOKIE_PATH)
