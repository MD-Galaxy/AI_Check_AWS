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

# Human-friendly labels for providers surfaced anywhere in the UI, keyed by
# the same provider key used in src/email_platform/factory.py.
_PROVIDER_LABELS = {
    "engagelab": "EngageLab",
    "sendcloud": "SendCloud",
    "sendgrid": "SendGrid",
    "mailgun": "Mailgun",
    "elasticemail": "Elastic Email",
}

# Provider keys offered on the Send RFQ form's "Provider" dropdown, in
# display order.
_FORM_PROVIDERS = ["sendcloud", "engagelab"]

_SUPPLIER_TYPE_LABELS = {"chinese": "Chinese", "non_chinese": "Non-Chinese"}

# Which supplier types each provider on the form can actually be used for,
# and which internal factory key (see src/email_platform/factory.py) that
# combination resolves to. SendCloud and EngageLab both reach Chinese *and*
# non-Chinese recipients, but through different, region-locked base
# URLs/credentials (setup_docs/aurora_send_cloud/AuroraSendCloud_Documentation.md
# §2: Hong Kong/CN for Chinese mailboxes, Singapore for everyone else — so
# "sendcloud" + Chinese resolves to the separate "sendcloud_hk" factory key).
# EngageLab's two data centers (Singapore/Turkey, per
# setup_docs/engagelab_guide/Engagelab_Documentation.md §2) aren't documented
# as a China-vs-non-China split, so it sends through the same Singapore
# endpoint for both supplier types. SendGrid has no regional split and is
# reserved for Non-Chinese suppliers.
_SEND_KEYS = {
    ("sendcloud", "chinese"): "sendcloud_hk",
    ("sendcloud", "non_chinese"): "sendcloud",
    ("engagelab", "chinese"): "engagelab",
    ("engagelab", "non_chinese"): "engagelab",
    ("sendgrid", "non_chinese"): "sendgrid",
}


def _available_providers(settings) -> list[dict]:
    """List the providers offered on the Send RFQ form's "Provider" dropdown.

    Args:
        settings: The application :class:`~src.config.Settings`.

    Returns:
        list[dict]: One ``{"key", "label", "outbound_domain", "supported_types"}``
            per provider in :data:`_FORM_PROVIDERS`. ``outbound_domain``
            drives the live "From"/"Reply address" preview on the form;
            ``supported_types`` lets the client warn on a provider/supplier-type
            combination the server would reject (the server re-validates
            regardless — see :func:`send_email_form`). A provider whose
            domain isn't configured yet just shows an empty preview (the
            send itself still fails fast with a clear error — see
            :meth:`~src.services.conversation_service.ConversationService.get_provider`).
    """
    return [
        {
            "key": key,
            "label": _PROVIDER_LABELS.get(key, key.capitalize()),
            "outbound_domain": settings.provider_outbound_domain(key),
            "supported_types": [
                stype for (pkey, stype) in _SEND_KEYS if pkey == key
            ],
        }
        for key in _FORM_PROVIDERS
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


@router.get("/quick-send")
async def quick_send_page(
    request: Request,
    current_user: dict = Depends(require_login),
):
    """Render the Quick Test Send page.

    A one-click testing surface: one card per provider in
    :data:`_FORM_PROVIDERS` (SendCloud, EngageLab), each split into a
    Chinese and a Non-Chinese section. Every section only asks for the
    destination email — the rest of the RFQ payload (supplier name,
    product, quantity, target price) is filled in with fixed defaults
    client-side (see ``templates/quick_send.html``), which then posts to
    the same ``POST /send`` this module already exposes. On a successful
    send the page opens the resulting conversation's tracking page
    (``/tracking/{conv_id}``) in a new tab.

    Args:
        request (Request): FastAPI request (required by Jinja2).
        current_user (dict): The logged-in user (sender identity).

    Returns:
        TemplateResponse: The rendered ``quick_send.html`` template.
    """
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "quick_send.html",
        {
            "active_page": "quick_send",
            "current_user": current_user,
            "available_providers": _available_providers(request.app.state.settings),
        },
    )


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
    POST/redirect cycle. The form has a required "Provider" dropdown
    (SendCloud / EngageLab / SendGrid, default empty) and the Supplier
    Details section has a required "Supplier Type" dropdown (Chinese /
    Non-Chinese, default empty). SendCloud and EngageLab both reach
    Chinese and Non-Chinese suppliers, through different region-locked
    URLs/credentials for SendCloud (Hong Kong/CN vs Singapore) and the
    same Singapore endpoint either way for EngageLab; SendGrid only
    supports Non-Chinese. :func:`send_email_form` resolves the
    provider+supplier-type pair to the actual sending region server-side
    (see :data:`_SEND_KEYS`) and rejects any combination a provider doesn't
    support.

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
    supplier_type: str = Form(default=""),
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
    on the form's required "Provider" dropdown — routed to the region that
    matches the required "Supplier Type" dropdown when the provider has
    one (SendCloud: Hong Kong/CN for Chinese, Singapore for Non-Chinese;
    see :data:`_SEND_KEYS`) — persists everything and redirects to the
    conversation detail page on success. A provider/supplier-type
    combination the provider doesn't support at all (e.g. SendGrid with
    Chinese) is rejected. Provider/configuration failures (including an
    empty selection or an unsupported combination, in case the browser's
    own ``required`` validation is bypassed) are caught and surfaced to the
    user as a banner rather than a 500 page. The sender is always the
    logged-in user — there is no user picker anymore (requirement 5).

    Args:
        request (Request): FastAPI request.
        provider_name (str): Provider key selected on the form, e.g.
            ``"engagelab"`` — required, no default selection.
        supplier_type (str): ``"chinese"`` or ``"non_chinese"``, selected
            on the form — required, no default selection; must be one
            ``provider_name`` actually supports (see :data:`_SEND_KEYS`).
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
        key = provider_name.strip().lower()
        stype = supplier_type.strip().lower()
        if not key:
            raise EmailProviderError("Please select an email provider.")
        if stype not in _SUPPLIER_TYPE_LABELS:
            raise EmailProviderError("Please select a supplier type.")
        if key not in _PROVIDER_LABELS:
            raise EmailProviderError(f"Unknown email provider '{provider_name}'.")
        send_key = _SEND_KEYS.get((key, stype))
        if send_key is None:
            raise EmailProviderError(
                f"{_PROVIDER_LABELS.get(key, key)} doesn't support "
                f"{_SUPPLIER_TYPE_LABELS[stype]} suppliers. Pick a provider "
                "that supports this supplier type."
            )
        provider_name = send_key

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
