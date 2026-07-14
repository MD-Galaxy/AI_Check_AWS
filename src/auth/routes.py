"""Login / registration-wizard / logout routes (MIGRATION_PLAN.md §3.2, §3.3).

All rendering follows the same thin-handler style as :mod:`src.route`: read
input, delegate to :class:`~src.db.repository.Repository`, render a template
or redirect. No business logic lives in :mod:`src.services`, since none of
it is conversation-related.
"""

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from src.auth.security import hash_password, verify_password
from src.auth.sessions import (
    clear_pending_cookie,
    clear_session_cookie,
    create_session_for_user,
    get_pending_user_id,
    revoke_current_session,
    set_pending_cookie,
    set_session_cookie,
)
from src.config import BASE_PATH
from src.db.repository import (
    DuplicatePersonalEmailError,
    DuplicateSendingEmailError,
    Repository,
)

router = APIRouter()

_MIN_PASSWORD_LENGTH = 8


def _local_part(email: str) -> str:
    return email.split("@", 1)[0]


def _normalized_email(raw: str) -> str | None:
    """Validate + normalize an email address, or ``None`` if invalid."""
    try:
        return validate_email(raw, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


# ── Login / logout ──────────────────────────────────────────────────────

@router.get("/login")
async def login_page(request: Request, error: str = "", registered: str = ""):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "login.html", {
        "error": error,
        "registered": registered,
    })


@router.post("/login")
async def login_submit(
    request: Request,
    personal_email: str = Form(...),
    password: str = Form(...),
):
    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    templates = request.app.state.templates

    normalized_email = _normalized_email(personal_email) or personal_email.strip()
    user = await repo.get_user_auth_by_personal_email(normalized_email)
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid email or password.",
            "personal_email": personal_email,
        }, status_code=401)

    if user["status"] == "pending":
        # They created an account but never finished the wizard — resume it
        # instead of dead-ending on a login failure.
        response = RedirectResponse(f"{BASE_PATH}/register/confirm-name", status_code=303)
        set_pending_cookie(response, user["id"], settings)
        return response

    token = await create_session_for_user(repo, user, request, settings)
    response = RedirectResponse(f"{BASE_PATH}/tracking", status_code=303)
    set_session_cookie(response, token, settings)
    return response


@router.post("/logout")
async def logout(request: Request):
    await revoke_current_session(request)
    response = RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    clear_session_cookie(response)
    return response


# ── Registration wizard ──────────────────────────────────────────────────

@router.get("/register")
async def register_step1(request: Request, error: str = ""):
    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    templates = request.app.state.templates

    prefill = {}
    pending_id = get_pending_user_id(request, settings)
    if pending_id:
        pending = await repo.get_user_auth_by_id(pending_id)
        if pending and pending["status"] == "pending":
            prefill = {
                "first_name": pending["first_name"],
                "last_name": pending["last_name"],
                "personal_email": pending["personal_email"],
            }

    return templates.TemplateResponse(request, "register_step1.html", {
        "error": error,
        **prefill,
    })


@router.post("/register")
async def register_step1_submit(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    personal_email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    templates = request.app.state.templates

    form_values = {
        "first_name": first_name,
        "last_name": last_name,
        "personal_email": personal_email,
    }

    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(request, "register_step1.html", {
            "error": message,
            **form_values,
        }, status_code=status_code)

    if not first_name.strip() or not last_name.strip():
        return error("First and last name are required.")
    normalized_email = _normalized_email(personal_email)
    if not normalized_email:
        return error("Please enter a valid email address.")
    if password != confirm_password:
        return error("Passwords do not match.")
    if len(password) < _MIN_PASSWORD_LENGTH:
        return error(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.")

    password_hash = hash_password(password)
    pending_id = get_pending_user_id(request, settings)
    try:
        if pending_id and (existing := await repo.get_user_auth_by_id(pending_id)) \
                and existing["status"] == "pending":
            user = await repo.update_pending_user(
                pending_id, first_name.strip(), last_name.strip(),
                normalized_email, password_hash,
            )
        else:
            user = await repo.create_pending_user(
                first_name.strip(), last_name.strip(), normalized_email, password_hash,
            )
    except DuplicatePersonalEmailError:
        return error("An account with this email already exists.")

    response = RedirectResponse(f"{BASE_PATH}/register/confirm-name", status_code=303)
    set_pending_cookie(response, user["id"], settings)
    return response


async def _load_pending_user(request: Request) -> dict | None:
    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    pending_id = get_pending_user_id(request, settings)
    if not pending_id:
        return None
    user = await repo.get_user_auth_by_id(pending_id)
    return user if user and user["status"] == "pending" else None


@router.get("/register/confirm-name")
async def register_step2(request: Request):
    user = await _load_pending_user(request)
    if not user:
        return RedirectResponse(f"{BASE_PATH}/register", status_code=303)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "register_step2.html", {"user": user})


@router.post("/register/confirm-name")
async def register_step2_submit(request: Request):
    user = await _load_pending_user(request)
    if not user:
        return RedirectResponse(f"{BASE_PATH}/register", status_code=303)
    return RedirectResponse(f"{BASE_PATH}/register/assign-email", status_code=303)


@router.get("/register/assign-email")
async def register_step3(request: Request):
    user = await _load_pending_user(request)
    if not user:
        return RedirectResponse(f"{BASE_PATH}/register", status_code=303)

    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    templates = request.app.state.templates

    candidate = f"{_local_part(user['personal_email'])}@{settings.default_outbound_domain}"
    taken = await repo.sending_email_exists(candidate)
    return templates.TemplateResponse(request, "register_step3.html", {
        "candidate": candidate,
        "taken": taken,
    })


@router.post("/register/assign-email")
async def register_step3_submit(
    request: Request, alternate_email: str = Form(default="")
):
    user = await _load_pending_user(request)
    if not user:
        return RedirectResponse(f"{BASE_PATH}/register", status_code=303)

    repo: Repository = request.app.state.db
    settings = request.app.state.settings
    templates = request.app.state.templates

    source_email = user["personal_email"]
    if alternate_email.strip():
        normalized_alt = _normalized_email(alternate_email)
        if not normalized_alt:
            candidate = f"{_local_part(user['personal_email'])}@{settings.default_outbound_domain}"
            return templates.TemplateResponse(request, "register_step3.html", {
                "candidate": candidate,
                "taken": True,
                "error": "Please enter a valid email address.",
            }, status_code=400)
        source_email = normalized_alt

    candidate = f"{_local_part(source_email)}@{settings.default_outbound_domain}"
    try:
        activated_user = await repo.assign_sending_email(user["id"], candidate)
    except DuplicateSendingEmailError:
        return templates.TemplateResponse(request, "register_step3.html", {
            "candidate": candidate,
            "taken": True,
            "error": "This address is already in use. Please provide a "
                     "different email address so we can generate an alternative.",
        }, status_code=409)

    token = await create_session_for_user(repo, activated_user, request, settings)
    response = RedirectResponse(f"{BASE_PATH}/tracking", status_code=303)
    set_session_cookie(response, token, settings)
    clear_pending_cookie(response)
    return response
