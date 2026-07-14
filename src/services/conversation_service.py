"""Conversation orchestration for EmailPOC.

:class:`ConversationService` is the single place that coordinates the
database, outbound email providers and the inbound webhook parser. It
exposes three high-level operations the routes call:

1. :meth:`ConversationService.create_conversation` – mint a conversation
   and its dynamic address, using whichever provider the sender picked.
2. :meth:`ConversationService.send_rfq` – render and send the RFQ email
   through that same provider, then persist the sent record.
3. :meth:`ConversationService.handle_inbound` – parse an inbound webhook
   request, match it to a conversation, store attachments and the reply,
   and classify the supplier's response.

There is no single "active" provider anymore: the Send RFQ form has a
required provider dropdown plus a required "Supplier Type" dropdown
(Chinese / Non-Chinese); the route layer resolves that pair to the actual
provider key to use — e.g. SendCloud + Chinese resolves to the internal
``sendcloud_hk`` key so the send goes through SendCloud's Hong Kong/CN
region instead of its Singapore default (see ``src.route._SEND_KEYS``) —
and :meth:`ConversationService.get_provider`
builds (and caches) an :class:`~src.email_platform.email_master.EmailMaster`
instance per provider key on demand via
:class:`~src.email_platform.factory.EmailProviderFactory` — adding a new
provider needs no changes here. Inbound webhook parsing still uses one
fixed provider instance (``self.email``, injected at construction — see
:func:`src.app.create_app`), since only one provider's inbound payload
format is understood by the single ``POST /webhooks/inbound`` endpoint.

Example:
    >>> service = ConversationService(           # doctest: +SKIP
    ...     db, email_provider, webhook_parser, settings, logger)
    >>> conv = service.create_conversation(       # doctest: +SKIP
    ...     "42", "Buyer Name", "supplier@acme.com", "Acme",
    ...     provider_name="engagelab")
    >>> conv["status"]                            # doctest: +SKIP
    'open'
"""

import logging
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

from fastapi import Request

from src.config import Settings
from src.db.repository import DuplicateConversationTokenError, Repository
from src.email_platform.email_master import EmailMaster, ProviderConfigError
from src.email_platform.factory import EmailProviderFactory
from src.webhook_factory.webhook_master import (
    InboundEmail,
    WebhookParseError,
    WebhookParserMaster,
)

# Inbound emails scoring above this SpamAssassin-style threshold are
# discarded before being matched to a conversation.
_SPAM_THRESHOLD = 5.0

# Bounded retry for the rare case a freshly generated 8-char conversation
# token collides with an existing one (the DB's UNIQUE constraint is the
# real backstop; this just turns a collision into a silent re-pick instead
# of a user-facing error).
_MAX_TOKEN_ATTEMPTS = 5


class ConversationService:
    """Coordinate conversations, outbound sends and inbound replies.

    Attributes:
        db (Repository): The async Postgres persistence layer.
        email (EmailMaster): The default outbound email provider — used for
            inbound webhook parsing and for any conversation created without
            an explicit ``provider_name`` (e.g. a brand-new headerless
            supplier email, see :meth:`_match_new_thread`). Its inherited
            address helpers are reused on the inbound side so the
            encode/decode logic has a single source of truth.
        webhook (WebhookParserMaster): The active inbound webhook parser.
        settings (Settings): Shared application configuration.
        log (logging.Logger): Shared application logger.

    Example:
        >>> service = ConversationService(       # doctest: +SKIP
        ...     db, email_provider, webhook_parser, settings, logger)
    """

    def __init__(
        self,
        db: Repository,
        email_provider: EmailMaster,
        webhook_parser: WebhookParserMaster,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        """Store the collaborators this service orchestrates.

        Args:
            db (Repository): The async Postgres persistence layer.
            email_provider (EmailMaster): The default outbound provider (see
                :attr:`email`).
            webhook_parser (WebhookParserMaster): The active inbound parser.
            settings (Settings): Shared application configuration.
            logger (logging.Logger): Shared application logger.

        Returns:
            None
        """
        self.db = db
        self.email = email_provider
        self.webhook = webhook_parser
        self.settings = settings
        self.log = logger
        self._provider_cache: dict[str, EmailMaster] = {
            email_provider.provider_name: email_provider
        }

    def get_provider(self, provider_name: str) -> EmailMaster:
        """Return the :class:`EmailMaster` instance for ``provider_name``.

        Instances are built lazily (via
        :class:`~src.email_platform.factory.EmailProviderFactory`, which
        validates that provider's credentials) and cached, so selecting the
        same provider on a later send reuses the same instance instead of
        re-validating configuration every time.

        Args:
            provider_name (str): Provider key selected on the Send RFQ form,
                e.g. ``"engagelab"``.

        Returns:
            EmailMaster: The (possibly newly built) provider instance.

        Raises:
            ProviderConfigError: If ``provider_name`` is empty, unknown, or
                that provider is missing required configuration.
        """
        key = (provider_name or "").strip().lower()
        if not key:
            raise ProviderConfigError("No email provider selected.")
        if key not in self._provider_cache:
            self._provider_cache[key] = EmailProviderFactory.create(
                key, self.settings, self.log
            )
        return self._provider_cache[key]

    # ── Outbound ─────────────────────────────────────────────────────

    async def create_conversation(
        self,
        user_id: str,
        user_name: str,
        supplier_email: str,
        supplier_name: str = "",
        project_id: str = "",
        project_name: str = "",
        provider_name: str | None = None,
    ) -> dict:
        """Create and persist a new tracked conversation.

        Generates a unique token (used as conv_id for email routing) and the
        associated dynamic email address, then stores the record in
        ``conversations``. Retries with a freshly generated token, up to
        :data:`_MAX_TOKEN_ATTEMPTS` times, if the token collides with an
        existing conversation's — the DB's own UNIQUE constraint on
        ``conversations.token`` is what actually guarantees no duplicates;
        this loop just makes a collision invisible to the caller.

        Args:
            user_id (str): The platform user UUID who owns this conversation.
            user_name (str): The user's display name.
            supplier_email (str): The supplier address for the outbound RFQ.
            supplier_name (str): Human-readable supplier display name.
            project_id (str): UUID of the selected predefined project.
                When provided this is stored as the "Conversation ID" for
                grouping; the generated token handles email routing.
            project_name (str): Product name from the selected project.
            provider_name (str | None): Provider picked on the Send RFQ
                form (see :meth:`get_provider`). ``None`` uses :attr:`email`,
                the default provider — used when a conversation is opened
                from the inbound side (:meth:`_match_new_thread`), where
                there is no form selection to read.

        Returns:
            dict: The newly created conversation record.

        Raises:
            DuplicateConversationTokenError: If every attempt collides
                (astronomically unlikely with an 8-char hex token space).
            ProviderConfigError: If ``provider_name`` is unknown or missing
                required configuration.
        """
        provider = self.get_provider(provider_name) if provider_name else self.email
        now = datetime.now(timezone.utc).isoformat()
        last_error: DuplicateConversationTokenError | None = None

        for _ in range(_MAX_TOKEN_ATTEMPTS):
            conv_id = provider.generate_conversation_id()
            email_addr = provider.build_dynamic_email(user_name, conv_id)

            conversation = {
                "conv_id": conv_id,
                "thread_id": conv_id,
                "project_id": project_id,
                "project_name": project_name,
                "user_id": str(user_id),
                "user_name": user_name,
                "supplier_email": supplier_email,
                "supplier_name": supplier_name,
                "email_address": email_addr,
                "provider": provider.provider_name,
                "status": "open",
                "created_at": now,
                "reply_count": 0,
                "last_reply_at": None,
                "emails_sent": [],
                "emails_received": [],
            }
            try:
                await self.db.insert_conversation(conversation)
            except DuplicateConversationTokenError as exc:
                last_error = exc
                self.log.warning("Conversation token collision on %s, retrying", conv_id)
                continue

            self.log.info(
                "Created conversation %s (project=%s user=%s provider=%s)",
                conv_id,
                project_id or "none",
                user_id,
                provider.provider_name,
            )
            return conversation

        raise last_error

    async def send_rfq(
        self,
        *,
        user_id: str,
        conv_id: str,
        supplier_email: str,
        supplier_name: str,
        product_name: str,
        quantity: int,
        target_price: str,
        provider_name: str,
        attachments: list | None = None,
    ) -> dict:
        """Render and send an RFQ email, then persist the sent record.

        The ``From`` header is rebuilt fresh for this send via
        :meth:`~src.email_platform.email_master.EmailMaster.build_sending_email`
        on the selected provider (so its domain matches whatever that
        provider is actually authorised to send from — different providers
        use different ``{PROVIDER}_OUTBOUND_DOMAIN`` values); the
        ``Reply-To`` header is the conversation's dynamic address so that
        replies route back to the inbound webhook. After a successful send
        the record is appended to the conversation and the product metadata
        is merged into the conversation root for the tracking UI.

        Args:
            user_id (str): The user who owns the conversation.
            conv_id (str): The 8-character conversation identifier.
            supplier_email (str): Destination address for the RFQ.
            supplier_name (str): Supplier display name for the salutation.
            product_name (str): Product being quoted.
            quantity (int): Number of units requested.
            target_price (str): Buyer's target unit price, e.g. ``"$12.00"``.
            provider_name (str): Provider picked on the Send RFQ form (see
                :meth:`get_provider`).

        Returns:
            dict: Summary with keys ``status_code``, ``provider``, ``from``,
                ``to`` and ``conv_id``.

        Raises:
            EmailProviderError: If the provider is misconfigured or the send
                fails (subclasses :class:`ProviderConfigError` and
                :class:`EmailSendError`).

        Example:
            >>> result = service.send_rfq(            # doctest: +SKIP
            ...     user_id="42", conv_id="3fa9c1b2",
            ...     supplier_email="buyer@acme.com",
            ...     supplier_name="Acme", product_name="X200",
            ...     quantity=500, target_price="$12.00",
            ...     provider_name="engagelab")
            >>> result["status_code"]                 # doctest: +SKIP
            202
        """
        provider = self.get_provider(provider_name)
        conversation = await self.db.get_conversation(conv_id)
        user = await self.db.get_user_auth_by_id(user_id)
        reply_to = (
            conversation["email_address"]
            if conversation
            else provider.build_dynamic_email(
                user["full_name"] if user else user_id, conv_id
            )
        )
        from_email = (
            provider.build_sending_email(user["full_name"]) if user else None
        )
        subject = provider.build_rfq_subject(conv_id, product_name)
        html_body = provider.build_rfq_html(
            user_id=user_id,
            conv_id=conv_id,
            supplier_name=supplier_name,
            product_name=product_name,
            quantity=quantity,
            target_price=target_price,
        )
        now = datetime.now(timezone.utc).isoformat()

        # Delegate transmission to the selected provider. Any failure raises
        # an EmailProviderError, which the route turns into a user message
        result = provider.send_email(
            from_email=from_email,
            from_name=provider.company_name,
            to_email=supplier_email,
            to_name=supplier_name,
            subject=subject,
            html_body=html_body,
            reply_to=reply_to,
            attachments=attachments,
        )

        sent_record = {
            "email_type": "new_thread",
            "from_email": from_email,
            "reply_to": reply_to,
            "to_email": supplier_email,
            "subject": subject,
            "body_html": html_body,
            "product_name": product_name,
            "quantity": quantity,
            "target_price": target_price,
            "attachments": [
                {"filename": a["filename"],
                 "content_type": a.get("content_type", "application/octet-stream"),
                 "size": len(a["content"])}
                for a in (attachments or [])
            ],
            "provider": result.get("provider"),
            "provider_message_id": result.get("provider_message_id"),
            "status_code": result.get("status_code"),
            "sent_at": now,
        }
        await self.db.add_sent_email(conv_id, sent_record)
        await self.db.update_conversation(conv_id, {
            "product_name": product_name,
            "quantity": quantity,
            "target_price": target_price,
            "subject": subject,
        })

        return {
            "status_code": result.get("status_code"),
            "provider": result.get("provider"),
            "from": from_email,
            "to": supplier_email,
            "conv_id": conv_id,
        }

    async def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Delete a conversation owned by ``user_id`` and its attachments.

        Verifies ownership before deleting anything, so one user cannot
        delete another user's conversation by guessing its id. Attachment
        files are named ``{conv_id}_...`` on disk (see
        :meth:`~src.webhook_factory.webhook_master.WebhookParserMaster.persist_attachments`),
        so they can be removed with a simple glob.

        Args:
            conv_id (str): The conversation to delete.
            user_id (str): The user requesting the deletion.

        Returns:
            bool: True if the conversation existed and belonged to
                ``user_id`` and was deleted, False otherwise.
        """
        conversation = await self.db.get_conversation(conv_id)
        if not conversation or str(conversation["user_id"]) != str(user_id):
            return False

        for path in Path(self.settings.attachments_dir).glob(f"{conv_id}_*"):
            path.unlink(missing_ok=True)

        await self.db.delete_conversation(conv_id, user_id)
        self.log.info("Deleted conversation %s for user %s", conv_id, user_id)
        return True

    async def delete_user_conversations(self, user_id: str) -> int:
        """Delete every conversation, email and attachment for a user.

        Used by the Email Tracking page's per-user delete action, where
        deleting a user is really "wipe all conversations owned by this
        user" — the user's own row in ``users`` is untouched, so they can
        still start new conversations afterwards.

        Args:
            user_id (str): The user whose entire tracking history should
                be wiped.

        Returns:
            int: The number of conversations deleted.
        """
        conv_ids = await self.db.delete_user_conversations(user_id)
        for conv_id in conv_ids:
            for path in Path(self.settings.attachments_dir).glob(f"{conv_id}_*"):
                path.unlink(missing_ok=True)
        self.log.info(
            "Deleted %d conversation(s) and their attachments for user %s",
            len(conv_ids),
            user_id,
        )
        return len(conv_ids)

    # ── Inbound ──────────────────────────────────────────────────────

    async def handle_inbound(self, request: Request) -> dict:
        """Parse and process one inbound webhook request end-to-end.

        Pipeline:

        1. Parse the provider payload into an :class:`InboundEmail`.
        2. Reject it if the signature could not be verified.
        3. Skip it if the spam score exceeds the threshold.
        4. Decode the ``To`` address into ``user_id`` / ``conv_id``; record
           it for manual review if it does not match the dynamic pattern.
        5. Persist any attachments and the reply, then classify it.

        Args:
            request (Request): The FastAPI request for the inbound POST.

        Returns:
            dict: A status payload — one of
                ``{"status": "error"}``,
                ``{"status": "rejected", "reason": "invalid_signature"}``,
                ``{"status": "skipped", "reason": "spam"}``,
                ``{"status": "unmatched"}`` or
                ``{"status": "matched", "user_id": ..., "conv_id": ...,
                "action": ...}``.

        Example:
            >>> payload = await service.handle_inbound(req)  # noqa
            >>> payload["status"]                            # doctest: +SKIP
            'matched'
        """
        try:
            inbound = await self.webhook.parse(request)
        except WebhookParseError as exc:
            self.log.error("Inbound parse failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

        self.log.info(
            "[Inbound] %s -> %s | %s",
            inbound.from_email,
            inbound.to_email,
            inbound.subject,
        )

        if not inbound.signature_verified:
            self.log.warning("Rejected inbound: signature not verified")
            return {"status": "rejected", "reason": "invalid_signature"}

        if inbound.spam_score > _SPAM_THRESHOLD:
            self.log.info(
                "Skipped inbound: spam score %s", inbound.spam_score
            )
            return {"status": "skipped", "reason": "spam"}

        return await self._record_inbound(inbound)

    async def _record_inbound(self, inbound: InboundEmail) -> dict:
        """Match a parsed inbound email and persist it.

        Matching is tried in order, each covering a gap the previous one
        cannot:

        1. The dynamic ``To`` address (the normal reply/forward path).
        2. Forwarded replies can arrive with that address mangled by the
           supplier's mail client (the ``-{conv_id}`` suffix dropped by
           autocomplete/address-book normalisation), so the quoted body is
           searched for the ``CONV-{conv_id}`` reference footer every RFQ
           email carries — see
           :meth:`~src.email_platform.email_master.EmailMaster.parse_conv_id_from_body`.
        3. A supplier composing a brand-new email (not reply/forward) has
           no conv_id anywhere — no dynamic address, no quoted footer (see
           ``setup_docs/engagelab_guide/engagelab_new_thread_issue.md``). If
           it was addressed to a user's permanent, unique ``sending_email``,
           that alone identifies the owning user, so it is bound to their
           latest conversation with this supplier (or a new one is opened)
           — see :meth:`_match_new_thread`.

        Args:
            inbound (InboundEmail): The normalised inbound email.

        Returns:
            dict: ``{"status": "unmatched"}`` if none of the three strategies
                resolve a conv_id, otherwise
                ``{"status": "matched", "user_id": ..., "conv_id": ...,
                "action": ...}``.
        """
        received_at = datetime.now(timezone.utc).isoformat()
        parsed = (
            self.email.parse_dynamic_email(inbound.to_email)
            or self.email.parse_conv_id_from_body(
                inbound.body_text, inbound.body_html
            )
        )
        if not parsed:
            new_thread_conv_id = await self._match_new_thread(inbound)
            if new_thread_conv_id:
                parsed = {"conv_id": new_thread_conv_id}

        if not parsed:
            await self.db.insert_unmatched({
                "reason": "address_not_recognized",
                "from_email": inbound.from_email,
                "to_email": inbound.to_email,
                "subject": inbound.subject,
                "provider": inbound.provider,
                "received_at": received_at,
                "needs_review": True,
            })
            self.log.info("Unmatched inbound address: %s", inbound.to_email)
            return {"status": "unmatched"}

        conv_id = parsed["conv_id"]
        conversation = await self.db.get_conversation(conv_id)
        if not conversation:
            await self.db.insert_unmatched({
                "reason": "conversation_not_found",
                "from_email": inbound.from_email,
                "to_email": inbound.to_email,
                "subject": inbound.subject,
                "provider": inbound.provider,
                "received_at": received_at,
                "needs_review": True,
            })
            self.log.info("Unmatched conv_id %s in address: %s", conv_id, inbound.to_email)
            return {"status": "unmatched"}

        user_id = conversation["user_id"]
        self.log.info("Matched inbound -> user=%s conv=%s", user_id, conv_id)

        attachments = self.webhook.persist_attachments(
            conv_id, inbound.attachments
        )
        inbound_record = {
            "email_type": self._detect_email_type(inbound.subject),
            "from_email": inbound.from_email,
            "to_email": inbound.to_email,
            "subject": inbound.subject,
            "body_text": inbound.body_text,
            "body_html": inbound.body_html,
            "attachments": attachments,
            "dkim": inbound.dkim,
            "spf": inbound.spf,
            "spam_score": str(inbound.spam_score),
            "provider": inbound.provider,
            "received_at": received_at,
        }
        await self.db.add_received_email(conv_id, inbound_record)
        action = await self._classify_reply(conv_id, inbound.body_text)

        return {
            "status": "matched",
            "user_id": user_id,
            "conv_id": conv_id,
            "action": action,
        }

    async def _match_new_thread(self, inbound: InboundEmail) -> str | None:
        """Bind a brand-new, headerless supplier email to its owning user.

        A supplier who composes a fresh email instead of hitting reply/
        forward produces a message with no conv_id anywhere — no dynamic
        address, no quoted ``CONV-`` footer (see
        ``setup_docs/engagelab_guide/engagelab_new_thread_issue.md`` for why
        that's structurally unavoidable). But a supplier can only have
        addressed it to a user's permanent, unique ``sending_email``
        (assigned once at registration), so that address alone identifies
        the owner. The email is then filed under the most recent existing
        conversation with this supplier, or a new conversation is opened if
        this supplier has never emailed this user before.

        Args:
            inbound (InboundEmail): The normalised inbound email.

        Returns:
            str | None: The conv_id to record this email against, or
                ``None`` if ``inbound.to_email`` isn't any user's
                ``sending_email``.
        """
        to_address = self.email.extract_email_address(inbound.to_email)
        user = (
            await self.db.get_user_by_sending_email(to_address)
            if to_address
            else None
        )
        if not user:
            return None

        supplier_email = self.email.extract_email_address(inbound.from_email)
        existing = await self.db.find_latest_conversation_by_supplier(
            user["id"], supplier_email
        )
        if existing:
            self.log.info(
                "New-thread inbound from %s bound to existing conversation %s",
                supplier_email,
                existing["conv_id"],
            )
            return existing["conv_id"]

        supplier_name = parseaddr(inbound.from_email or "")[0] or supplier_email
        conversation = await self.create_conversation(
            user_id=user["id"],
            user_name=user["full_name"],
            supplier_email=supplier_email,
            supplier_name=supplier_name,
        )
        await self.db.update_conversation(
            conversation["conv_id"], {"subject": inbound.subject or ""}
        )
        self.log.info(
            "New-thread inbound from %s opened conversation %s for user %s",
            supplier_email,
            conversation["conv_id"],
            user["id"],
        )
        return conversation["conv_id"]

    async def _classify_reply(self, conv_id: str, reply_body: str) -> str:
        """Classify a supplier reply with simple keyword matching.

        Buckets the reply into one of four action classes. A ``DECLINED``
        classification also flips the conversation status to ``"declined"``.
        This is the integration point for a future negotiation agent.

        Args:
            conv_id (str): The conversation receiving the reply.
            reply_body (str): Plain-text body of the inbound email.

        Returns:
            str: One of ``"QUOTE_RECEIVED"``, ``"DECLINED"``,
                ``"CLARIFICATION_NEEDED"`` or ``"MANUAL_REVIEW"``.

        Example:
            >>> service._classify_reply(             # doctest: +SKIP
            ...     "3fa9c1b2", "Our price is $11.50/unit.")
            'QUOTE_RECEIVED'
        """
        text = (reply_body or "").lower()
        if any(w in text for w in ["price", "quote", "usd", "$", "unit"]):
            action = "QUOTE_RECEIVED"
        elif any(
            w in text for w in ["sorry", "cannot", "unable", "no stock"]
        ):
            action = "DECLINED"
            await self.db.update_conversation(conv_id, {"status": "declined"})
        elif any(
            w in text for w in ["question", "clarif", "more info", "?"]
        ):
            action = "CLARIFICATION_NEEDED"
        else:
            action = "MANUAL_REVIEW"

        self.log.info("Reply on %s classified as %s", conv_id, action)
        # Hook a negotiation agent here, e.g.:
        #   agent.invoke({"conv_id": conv_id, "action": action, ...})
        return action

    @staticmethod
    def _detect_email_type(subject: str) -> str:
        """Detect whether an inbound email is a reply, forward, or new thread.

        Args:
            subject (str): The subject line of the inbound email.

        Returns:
            str: One of ``"reply"``, ``"forwarded"``, or ``"new_thread"``.
        """
        s = (subject or "").strip().lower()
        if s.startswith("re:") or s.startswith("re "):
            return "reply"
        if s.startswith("fwd:") or s.startswith("fw:") or s.startswith("fwd "):
            return "forwarded"
        return "new_thread"
