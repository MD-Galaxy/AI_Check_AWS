"""Local-development login bypass — never enable outside a personal sandbox.

Guarded by ``DEV_BYPASS_LOGIN=true`` in ``.env`` (``Settings.dev_bypass_login``,
default ``False`` — see :mod:`src.config`). When enabled, ``GET
/dev/login-john-carter`` skips the login/registration wizard entirely: it
upserts one fixed "John Carter" user, opens a real session for it exactly
like :func:`src.auth.routes.login_submit` does, and redirects straight to
``/send``. With the flag off (the default), the route 404s, so it is not
reachable at all unless a developer opts in for local use — see
``make john-carter`` in the Makefile.
"""

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.auth.security import hash_password
from src.auth.sessions import create_session_for_user, set_session_cookie
from src.config import BASE_PATH
from src.db.repository import DuplicateSendingEmailError, Repository

router = APIRouter()

_JOHN_CARTER_FIRST_NAME = "John"
_JOHN_CARTER_LAST_NAME = "Carter"
_JOHN_CARTER_PERSONAL_EMAIL = "john.carter@local.dev"
_JOHN_CARTER_LOCAL_PART = "john.carter"
_FALLBACK_DOMAIN = "local.dev"


async def _get_or_create_john_carter(repo: Repository, inbound_domain: str) -> dict:
    """Return the fixed John Carter user, creating and activating it if needed."""
    user = await repo.get_user_auth_by_personal_email(_JOHN_CARTER_PERSONAL_EMAIL)
    if user is None:
        user = await repo.create_pending_user(
            _JOHN_CARTER_FIRST_NAME,
            _JOHN_CARTER_LAST_NAME,
            _JOHN_CARTER_PERSONAL_EMAIL,
            hash_password(secrets.token_urlsafe(32)),
        )

    if user["status"] != "active":
        sending_email = f"{_JOHN_CARTER_LOCAL_PART}@{inbound_domain or _FALLBACK_DOMAIN}"
        try:
            user = await repo.assign_sending_email(user["id"], sending_email)
        except DuplicateSendingEmailError:
            # Someone else already holds that address — re-fetch; the user
            # row itself is still fine even if it's stuck at status=pending.
            user = await repo.get_user_auth_by_personal_email(_JOHN_CARTER_PERSONAL_EMAIL)

    return user


@router.get("/dev/login-john-carter")
async def login_as_john_carter(request: Request):
    """Log in as John Carter and redirect to the Send RFQ page.

    Raises:
        HTTPException: 404 if ``DEV_BYPASS_LOGIN`` is not enabled.
    """
    settings = request.app.state.settings
    if not settings.dev_bypass_login:
        raise HTTPException(status_code=404)

    repo: Repository = request.app.state.db
    user = await _get_or_create_john_carter(repo, settings.inbound_domain)

    token = await create_session_for_user(repo, user, request, settings)
    response = RedirectResponse(f"{BASE_PATH}/send", status_code=303)
    set_session_cookie(response, token, settings)
    return response
