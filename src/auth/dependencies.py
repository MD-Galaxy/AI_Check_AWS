"""FastAPI dependencies for reading and requiring the logged-in user.

Mirrors MIGRATION_PLAN.md §3.1: ``get_current_user`` is the soft check (used
by public-but-personalized pages, if any); ``require_login`` is the hard
gate every authenticated route below depends on.
"""

from fastapi import HTTPException, Request

from src.auth.sessions import get_current_user as _get_current_user
from src.config import BASE_PATH


async def get_current_user(request: Request) -> dict | None:
    return await _get_current_user(request)


async def require_login(request: Request) -> dict:
    """Return the logged-in user, or redirect to ``/login``.

    Raises:
        HTTPException: 303 redirect to ``/login`` if there is no valid
            session. Browsers follow the ``Location`` header on a 303
            regardless of the response being routed through FastAPI's
            HTTPException machinery.
    """
    user = await _get_current_user(request)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": f"{BASE_PATH}/login"})
    return user
