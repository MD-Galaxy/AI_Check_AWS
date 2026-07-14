"""HTTP routes for EmailPOC — UI pages and the single inbound webhook.

This module contains **only** route declarations. Every handler is thin: it
reads request input, delegates to the shared
:class:`~src.services.conversation_service.ConversationService` (and the
Jinja2 templates) stored on ``request.app.state``, and returns a response.
All construction and wiring lives in :mod:`src.app`, so this file can be
read as a flat table of "URL → behaviour".

Every route below requires a logged-in user (see :mod:`src.auth`) except the
inbound webhook, which providers call anonymously.

Routes:

================ ====== ==============================================
Method + path           Purpose
================ ====== ==============================================
``GET /``               Redirect to ``/tracking``.
``GET /send``           Render the Send RFQ form.
``POST /send``          Create a conversation and send the RFQ.
``GET /tracking``       Personal dashboard: my stats + my conversations.
``GET /tracking/{c}``   Full conversation thread (ownership-checked).
``POST /tracking/{c}/delete`` Delete one of my conversations.
``POST /webhooks/inbound`` Receive an inbound reply (any provider).
``GET /webhooks/inbound``  Validation probe (Elastic Email GETs this).
================ ====== ==============================================

Example:
    >>> from src.route import router
    >>> from fastapi import FastAPI
    >>> app = FastAPI()
    >>> app.include_router(router)            # doctest: +SKIP
"""

from typing import List
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from src.auth.dependencies import require_login
from src.config import BASE_PATH
from src.email_platform.email_master import EmailProviderError
from src.email_platform.factory import EmailProviderFactory
from src.services.conversation_service import ConversationService

# A single router that :mod:`src.app` includes on the FastAPI application.
router = APIRouter()

# Human-friendly labels for the Send RFQ page's provider dropdown, keyed by
# the same provider key used in src/email_platform/factory.py. A provider
# with no entry here just falls back to its raw key, capitalized — add an
# entry when registering a new provider if the raw key isn't a good label.
_PROVIDER_LABELS = {
    "engagelab": "EngageLab",
    "sendcloud": "SendCloud",
    "sendgrid": "SendGrid",
    "mailgun": "Mailgun",
    "elasticemail": "Elastic Email",
}
CHINESE_PROVIDERS = ["sendcloud", "engagelab"]


def _available_providers(settings) -> list[dict]:
    """List every factory-registered provider for the Send RFQ dropdown.

    Args:
        settings: The application :class:`~src.config.Settings`.

    Returns:
        list[dict]: One ``{"key": ..., "label": ..., "outbound_domain": ...}``
            per provider registered in
            :class:`~src.email_platform.factory.EmailProviderFactory`, in
            registration order. ``outbound_domain`` drives the live "From"/
            "Reply address" preview on the form; a provider whose domain
            isn't configured yet just shows an empty preview (the send
            itself still fails fast with a clear error — see
            :meth:`~src.services.conversation_service.ConversationService.get_provider`).
    """
    return [
        {
            "key": key,
            "label": _PROVIDER_LABELS.get(key, key.capitalize()),
            "outbound_domain": settings.provider_outbound_domain(key),
        }
        for key in CHINESE_PROVIDERS
    ]


# Maps ConversationService.handle_inbound's "status" field to an HTTP
# status code. "matched"/"unmatched"/"skipped" are all valid, non-retryable
# outcomes (a spam email or an address that doesn't match a conversation is
# not a delivery failure), so they stay 200 — a non-2xx would make most
# providers retry the same POST. "rejected" (bad signature) and "error"
# (unparseable payload) are genuine failures and get a non-2xx status.
_INBOUND_STATUS_CODES = {
    "matched": 200,
    "unmatched": 200,
    "skipped": 200,
    "rejected": 400,
    "error": 500,
}


# ── UI routes ────────────────────────────────────────────────────────


@router.get("/")
async def home(_current_user: dict = Depends(require_login)):
    """Redirect the authenticated root path to the personal dashboard."""
    return RedirectResponse(f"{BASE_PATH}/tracking", status_code=303)


@router.get("/send")
async def send_email_page(
    request: Request,
    success: str = "",
    error: str = "",
    conv_id: str = "",
    current_user: dict = Depends(require_login),
):
    """Render the Send RFQ form page.

    Displays the HTML form for composing a new RFQ. Optional query
    parameters let the page surface success/error feedback after a
    POST/redirect cycle. The form includes a required "Provider" dropdown
    (default empty — no provider is pre-selected); the chosen provider
    decides which ``{PROVIDER}_API_USER`` / ``{PROVIDER}_API_KEY`` /
    ``{PROVIDER}_OUTBOUND_DOMAIN`` / ``{PROVIDER}_COMPANY_NAME`` are used
    for this send (see
    :meth:`~src.services.conversation_service.ConversationService.get_provider`).

    Args:
        request (Request): FastAPI request (required by Jinja2).
        success (str): Non-empty value triggers a success banner.
        error (str): Non-empty value triggers an error banner with the
            URL-decoded message.
        conv_id (str): Conversation id used in the success banner link.
        current_user (dict): The logged-in user (sender identity).

    Returns:
        TemplateResponse: The rendered ``index.html`` template.
    """
    templates = request.app.state.templates
    service: ConversationService = request.app.state.service
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "send",
            "success": success,
            "error": error,
            "conv_id": conv_id,
            "current_user": current_user,
            "available_providers": _available_providers(request.app.state.settings),
            "predefined_projects": await service.db.get_predefined_projects(),
        },
    )


@router.post("/send")
async def send_email_form(
    request: Request,
    project_id: str = Form(default=""),
    project_name: str = Form(default=""),
    provider_name: str = Form(default=""),
    supplier_email: str = Form(...),
    supplier_name: str = Form(...),
    product_name: str = Form(...),
    quantity: int = Form(...),
    target_price: str = Form(...),
    attachments: List[UploadFile] = File(default=[]),
    current_user: dict = Depends(require_login),
):
    """Process the RFQ form submission and send the email.

    Creates a conversation, dispatches the RFQ through the provider chosen
    on the form's required "Provider" dropdown, persists everything and
    redirects to the conversation detail page on success. Provider/
    configuration failures (including an empty selection, in case the
    browser's own ``required`` validation is bypassed) are caught and
    surfaced to the user as a banner rather than a 500 page. The sender is
    always the logged-in user — there is no user picker anymore
    (requirement 5).

    Args:
        request (Request): FastAPI request.
        provider_name (str): Provider key selected on the form, e.g.
            ``"engagelab"`` — required, no default selection.
        supplier_email (str): Supplier's email address.
        supplier_name (str): Supplier's display name.
        product_name (str): Name of the product being quoted.
        quantity (int): Requested quantity in units.
        target_price (str): Target unit price string, e.g. ``"$12.00"``.
        current_user (dict): The logged-in user (sender identity).

    Returns:
        RedirectResponse: ``303`` to ``/tracking/{conv_id}`` on success, or
            back to ``/send?error=...`` on failure.
    """
    service: ConversationService = request.app.state.service
    log = request.app.state.log
    try:
        if not provider_name.strip():
            raise EmailProviderError("Please select an email provider.")

        attachment_data = []
        for upload in attachments:
            if upload.filename:
                content = await upload.read()
                attachment_data.append(
                    {
                        "filename": upload.filename,
                        "content": content,
                        "content_type": (
                            upload.content_type or "application/octet-stream"
                        ),
                    }
                )

        conversation = await service.create_conversation(
            current_user["id"],
            current_user["full_name"],
            supplier_email,
            supplier_name,
            project_id=project_id,
            project_name=project_name,
            provider_name=provider_name,
        )
        conv_id = conversation["conv_id"]

        await service.send_rfq(
            user_id=current_user["id"],
            conv_id=conv_id,
            supplier_email=supplier_email,
            supplier_name=supplier_name,
            product_name=product_name,
            quantity=quantity,
            target_price=target_price,
            provider_name=provider_name,
            attachments=attachment_data or None,
        )
        return RedirectResponse(
            f"{BASE_PATH}/tracking/{conv_id}?success=1",
            status_code=303,
        )
    except EmailProviderError as exc:
        # Expected, well-described failure (bad key, send rejected, ...).
        log.error("Send failed: %s", exc)
        return RedirectResponse(
            f"{BASE_PATH}/send?error={quote(str(exc)[:300])}",
            status_code=303,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort safety net
        log.exception("Unexpected error while sending RFQ")
        return RedirectResponse(
            f"{BASE_PATH}/send?error={quote(str(exc)[:300])}",
            status_code=303,
        )


@router.get("/tracking")
async def tracking_home(
    request: Request,
    deleted: str = "",
    current_user: dict = Depends(require_login),
):
    """Render the personal dashboard: my stats + my conversations.

    Args:
        request (Request): FastAPI request.
        deleted (str): Non-empty value triggers a "conversation deleted"
            banner after a delete/redirect cycle.
        current_user (dict): The logged-in user.

    Returns:
        TemplateResponse: Rendered ``tracking.html`` with ``stats`` and
            ``conversations`` scoped to ``current_user``.
    """
    service: ConversationService = request.app.state.service
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "tracking.html",
        {
            "active_page": "tracking",
            "current_user": current_user,
            "stats": await service.db.get_user_stats(current_user["id"]),
            "conversations": await service.db.get_user_conversations(
                current_user["id"]
            ),
            "deleted": deleted,
        },
    )


@router.get("/tracking/{conv_id}")
async def conversation_detail(
    request: Request,
    conv_id: str,
    success: str = "",
    current_user: dict = Depends(require_login),
):
    """Render the full email thread for a single conversation.

    Merges sent and received records into one chronological timeline; each
    item carries a ``direction`` key so the template can style sent vs
    received differently.

    Args:
        request (Request): FastAPI request.
        conv_id (str): The 8-character conversation identifier (token).
        success (str): Non-empty triggers a success banner.
        current_user (dict): The logged-in user (used for the ownership
            check).

    Returns:
        TemplateResponse: Rendered ``conversation_detail.html`` with
            ``conversation`` and ``thread``.

    Raises:
        HTTPException: ``404`` if ``conv_id`` is not found or belongs to a
            different user.
    """
    service: ConversationService = request.app.state.service
    templates = request.app.state.templates

    conversation = await service.db.get_conversation(conv_id)
    if not conversation or str(conversation["user_id"]) != str(current_user["id"]):
        raise HTTPException(status_code=404, detail="Conversation not found")

    thread = []
    for email in conversation.get("emails_sent", []):
        thread.append(
            {
                **email,
                "direction": "sent",
                "_ts": email.get("sent_at", ""),
            }
        )
    for email in conversation.get("emails_received", []):
        thread.append(
            {
                **email,
                "direction": "received",
                "_ts": email.get("received_at", ""),
            }
        )
    thread.sort(key=lambda item: item.get("_ts", ""))

    return templates.TemplateResponse(
        request,
        "conversation_detail.html",
        {
            "active_page": "tracking",
            "current_user": current_user,
            "conversation": conversation,
            "thread": thread,
            "success": success,
        },
    )


@router.post("/tracking/{conv_id}/delete")
async def delete_conversation(
    request: Request, conv_id: str, current_user: dict = Depends(require_login)
):
    """Delete one of my conversations and its attachments, then redirect.

    Args:
        request (Request): FastAPI request.
        conv_id (str): The conversation token to delete.
        current_user (dict): The logged-in user (used for the ownership
            check).

    Returns:
        RedirectResponse: ``303`` to ``/tracking?deleted=1``.

    Raises:
        HTTPException: ``404`` if ``conv_id`` is not found or belongs to a
            different user.
    """
    service: ConversationService = request.app.state.service
    if not await service.delete_conversation(conv_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return RedirectResponse(f"{BASE_PATH}/tracking?deleted=1", status_code=303)


# ── Inbound webhook (single URL for every provider) ──────────────────


@router.post("/webhooks/inbound")
async def handle_inbound_email(request: Request):
    """Receive and process one inbound email from any provider.

    This is the single endpoint every provider's inbound feature posts to.
    The provider-specific parsing, conversation matching, attachment
    storage and reply classification all happen inside
    :meth:`ConversationService.handle_inbound`; the inbound parser is fixed
    at startup (``src.app._INBOUND_EMAIL_PROVIDER``) since this one endpoint
    only understands one payload format at a time — independent of which
    provider a sender picks per outbound send on the Send RFQ form.
    Deliberately public — providers call this anonymously, so it is never
    behind ``require_login``.

    Args:
        request (Request): FastAPI request. The body is form or JSON data
            depending on the provider.

    Returns:
        JSONResponse: The status payload from
            :meth:`ConversationService.handle_inbound` — one of ``matched``,
            ``unmatched``, ``skipped`` (spam), ``rejected`` (bad signature)
            or ``error`` — with a matching HTTP status code (200 for
            matched/unmatched/skipped, 400 for rejected, 500 for error; see
            :data:`_INBOUND_STATUS_CODES`).
    """
    service: ConversationService = request.app.state.service
    result = await service.handle_inbound(request)
    status_code = _INBOUND_STATUS_CODES.get(result.get("status"), 200)
    return JSONResponse(content=result, status_code=status_code)


@router.get("/webhooks/inbound")
async def validate_inbound_webhook():
    """Answer the GET probe some providers send before saving a route.

    Elastic Email (and others) validate an inbound notification URL by
    issuing a ``GET`` and requiring a ``2xx`` response before they will save
    it. This handler exists solely to satisfy that probe. Deliberately
    public, same reasoning as the POST variant above.

    Returns:
        dict: ``{"status": "ok"}`` with an implicit ``200`` status.
    """
    return {"status": "ok"}
