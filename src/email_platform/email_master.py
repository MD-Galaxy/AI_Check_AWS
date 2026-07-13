"""Abstract base class and shared logic for every email provider.

All outbound email providers (SendGrid, Mailgun, Elastic Email) inherit
from :class:`EmailMaster`. The base class owns the behaviour that is
identical no matter which provider actually transmits the message:

- :meth:`EmailMaster.generate_conversation_id` – mint a conversation id.
- :meth:`EmailMaster.build_dynamic_email` – encode ``user_id`` /
  ``conv_id`` into a per-conversation address.
- :meth:`EmailMaster.parse_dynamic_email` – decode that address back into
  its ``user_id`` / ``conv_id`` (also used by the inbound webhook).
- :meth:`EmailMaster.build_rfq_subject` / :meth:`EmailMaster.build_rfq_html`
  – render the standard RFQ subject line and HTML body.

Each concrete provider only has to implement two members: the
:attr:`EmailMaster.provider_name` property and the
:meth:`EmailMaster.send_email` method, which performs the provider-specific
network call and returns a normalised result dict.

Example:
    >>> from src.email_platform.factory import EmailProviderFactory
    >>> from src.config import get_settings
    >>> from src.logger import AppLogger
    >>> provider = EmailProviderFactory.create(
    ...     "sendgrid", get_settings(), AppLogger.get())
    >>> cid = provider.generate_conversation_id()
    >>> addr = provider.build_dynamic_email("42", cid)
    >>> provider.parse_dynamic_email(addr)["user_id"]
    '42'
"""

import logging
import re
import uuid
from abc import ABC, abstractmethod
from email.utils import parseaddr

from src.config import Settings


class EmailProviderError(Exception):
    """Base error for every email-provider failure.

    Catching :class:`EmailProviderError` catches both configuration
    problems (:class:`ProviderConfigError`) and send failures
    (:class:`EmailSendError`).
    """


class ProviderConfigError(EmailProviderError):
    """Raised when a provider is missing required configuration.

    For example, selecting ``EMAIL_PROVIDER=mailgun`` without setting
    ``MAILGUN_API_KEY`` raises this error with a message naming the missing
    variable.
    """


class EmailSendError(EmailProviderError):
    """Raised when a provider fails to transmit an outbound email.

    Wraps the underlying SDK / HTTP exception in a single, predictable
    error type with a human-readable message so callers do not have to know
    which provider was used.
    """


class EmailMaster(ABC):
    """Common base for all outbound email providers.

    Concrete subclasses implement :attr:`provider_name` and
    :meth:`send_email`; everything else is shared here so the address
    scheme and RFQ template stay identical across providers.

    Attributes:
        settings (Settings): Shared application configuration.
        log (logging.Logger): Shared application logger.

    Example:
        >>> class Dummy(EmailMaster):
        ...     provider_name = "dummy"
        ...     def send_email(self, **kw):
        ...         return {"status_code": 202, "provider": "dummy",
        ...                 "provider_message_id": "x"}
    """

    def __init__(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        """Store the shared configuration and logger.

        Args:
            settings (Settings): The application configuration snapshot.
            logger (logging.Logger): The shared application logger.

        Returns:
            None
        """
        self.settings = settings
        self.log = logger

    # ── Provider identity (must be overridden) ───────────────────────

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the lowercase provider key.

        Returns:
            str: One of ``"sendgrid"``, ``"mailgun"``, ``"elasticemail"``,
                ``"sendcloud"`` or ``"engagelab"``.
        """
        raise NotImplementedError

    # ── Shared address helpers ───────────────────────────────────────

    def generate_conversation_id(self) -> str:
        """Generate a short, unique 8-character hex conversation id.

        Uses the first 8 characters of a UUID4 (hyphens removed), giving
        roughly 4 billion unique values — more than enough for this POC.

        Returns:
            str: 8-character lowercase hexadecimal string,
                e.g. ``"3fa9c1b2"``.

        Example:
            >>> cid = provider.generate_conversation_id()
            >>> len(cid)
            8
        """
        return uuid.uuid4().hex[:8]

    def build_dynamic_email(self, user_name: str, conv_id: str) -> str:
        """Construct the dynamic email address for a conversation.

        Converts the user's display name to CamelCase (e.g.
        ``"James Whitfield"`` → ``"JamesWhitfield"``) and combines it with the
        conversation/thread id via a hyphen so the address is human-readable
        and the conv_id can be recovered from any reply that arrives there.

        Args:
            user_name (str): The user's display name (e.g. ``"James Whitfield"``).
            conv_id (str): The 8-character conversation identifier returned
                by :meth:`generate_conversation_id`.

        Returns:
            str: Fully qualified address, e.g.
                ``"JamesWhitfield-3fa9c1b2@mail.jobsetu.online"``.

        Example:
            >>> provider.build_dynamic_email("James Whitfield", "3fa9c1b2")
            'JamesWhitfield-3fa9c1b2@mail.jobsetu.online'
        """
        camel = "".join(word.capitalize() for word in user_name.split())
        return f"{camel}-{conv_id}@{self.settings.inbound_domain}"

    def parse_dynamic_email(self, email_address: str) -> dict | None:
        """Extract ``conv_id`` from a dynamic address.

        Supports two address formats:

        * **Current**: ``{CamelCaseName}-{conv_id}@{INBOUND_DOMAIN}``
          e.g. ``JamesWhitfield-3fa9c1b2@mail.jobsetu.online``
        * **Legacy** (backward-compat): ``{prefix}_conv{conv_id}@{INBOUND_DOMAIN}``
          e.g. ``james.whitfield_conv3fa9c1b2@mail.jobsetu.online``

        Args:
            email_address (str): The raw ``To`` address from an inbound
                email.

        Returns:
            dict | None: ``{"conv_id": str}`` on success, or ``None`` when
                the address does not match any known pattern (or when
                ``INBOUND_DOMAIN`` is not configured).

        Example:
            >>> provider.parse_dynamic_email(
            ...     "JamesWhitfield-3fa9c1b2@mail.jobsetu.online")
            {'conv_id': '3fa9c1b2'}
            >>> provider.parse_dynamic_email("nobody@other.com") is None
            True
        """
        inbound_domain = self.settings.inbound_domain
        if not inbound_domain:
            self.log.error(
                "INBOUND_DOMAIN is not set; cannot match inbound address"
            )
            return None

        domain = re.escape(inbound_domain)
        patterns = [
            # Current format: CamelCaseName-{8hex}@domain
            rf"[A-Za-z0-9]+-([a-f0-9]{{8}})@{domain}(?![\w.-])",
            # Legacy format: any_prefix_conv{8hex}@domain
            rf"[a-z0-9._-]+_conv([a-f0-9]{{8}})@{domain}(?![\w.-])",
        ]
        for pattern in patterns:
            match = re.search(pattern, email_address or "", re.IGNORECASE)
            if match:
                return {"conv_id": match.group(1)}
        return None

    def parse_conv_id_from_body(self, *texts: str) -> dict | None:
        """Recover ``conv_id`` from the quoted RFQ reference footer.

        Some mail clients mangle the dynamic ``To`` address when a supplier
        forwards an RFQ instead of replying to it directly (autocomplete or
        an address-book entry can drop the ``-{conv_id}`` suffix entirely).
        When that happens the quoted original message is still present in
        the body, including the ``Reference: CONV-{conv_id}`` footer written
        by :meth:`build_rfq_html`, so it is used as a fallback match.

        Args:
            *texts (str): Candidate bodies to search, e.g. ``body_text`` and
                ``body_html`` — the first match wins.

        Returns:
            dict | None: ``{"conv_id": str}`` (lowercase) on success, or
                ``None`` if no candidate contains the footer reference.

        Example:
            >>> provider.parse_conv_id_from_body(
            ...     "On Mon, ... Reference: CONV-3FA9C1B2 | USR-42")
            {'conv_id': '3fa9c1b2'}
        """
        for text in texts:
            match = re.search(r"CONV-([A-Fa-f0-9]{8})\b", text or "")
            if match:
                return {"conv_id": match.group(1).lower()}
        return None

    @staticmethod
    def extract_email_address(raw: str) -> str:
        """Strip a display name off a raw ``From``/``To`` header value.

        Inbound payloads often carry ``"James Whitfield <a@b.com>"`` rather
        than a bare address; matching against a stored address (e.g.
        ``users.sending_email``) needs just the ``a@b.com`` part.

        Args:
            raw (str): The raw header value, with or without a display name.

        Returns:
            str: The lowercased bare address, or ``""`` if none could be
                parsed out.

        Example:
            >>> EmailMaster.extract_email_address(
            ...     "James Whitfield <james@mail.jobsetu.online>")
            'james@mail.jobsetu.online'
        """
        return (parseaddr(raw or "")[1] or "").strip().lower()

    # ── Shared RFQ rendering ─────────────────────────────────────────

    def build_rfq_subject(self, conv_id: str, product_name: str) -> str:
        """Build the standard RFQ subject line.

        Args:
            conv_id (str): The conversation identifier; its first four
                characters become a short, human-friendly reference tag.
            product_name (str): The product being quoted.

        Returns:
            str: A subject line such as
                ``"[RFQ-3FA9] Request for Quotation — Speaker X200"``.

        Example:
            >>> provider.build_rfq_subject("3fa9c1b2", "Speaker X200")
            '[RFQ-3FA9] Request for Quotation — Speaker X200'
        """
        tag = conv_id[:4].upper()
        return (
            f"[RFQ-{tag}] Request for Quotation — {product_name}"
        )

    def build_rfq_html(
        self,
        *,
        user_id: str,
        conv_id: str,
        supplier_name: str,
        product_name: str,
        quantity: int,
        target_price: str,
    ) -> str:
        """Render the HTML body of an RFQ email.

        The markup is intentionally inline-styled so it renders consistently
        across email clients, which strip ``<style>`` blocks.

        Args:
            user_id (str): The owning user (shown in the footer reference).
            conv_id (str): The conversation identifier (shown in the footer).
            supplier_name (str): Salutation name for the supplier.
            product_name (str): Product being quoted.
            quantity (int): Number of units requested.
            target_price (str): Buyer's target unit price, e.g. ``"$12.00"``.

        Returns:
            str: A complete HTML fragment ready to use as the email body.

        Example:
            >>> html = provider.build_rfq_html(
            ...     user_id="42", conv_id="3fa9c1b2",
            ...     supplier_name="Acme", product_name="X200",
            ...     quantity=500, target_price="$12.00")
            >>> "Request for Quotation" not in html  # subject, not body
            True
            >>> "Acme" in html
            True
        """
        company = self.settings.company_name
        # Built as a list of short lines so no single source line exceeds
        # the 79-column limit; ``"".join`` reassembles the final markup.
        # Small base64-encoded blue banner (320×40 PNG) for image-tracking
        # tests — demonstrates inline image rendering across email clients.
        parts = [
            '<div style="font-family: Arial, sans-serif; '
            'max-width: 600px;">',
            # Company banner image (inline base64 — renders without external
            # host; tests that images in email body are tracked correctly)
            f'<img src="https://placehold.co/320x40/blue/white?text={company}" '
            f'alt="{company}" width="320" height="40" '
            'style="display:block; margin-bottom:16px;">',
            f"<p>Dear {supplier_name},</p>",
            "<p>I am writing to request a formal quotation for the "
            "following:</p>",
            '<table border="1" cellpadding="8" cellspacing="0"',
            ' style="border-collapse: collapse; width: 100%;">',
            '<tr style="background-color: #f5f5f5;">',
            "<th>Product</th><th>Quantity</th><th>Target Price</th></tr>",
            f"<tr><td>{product_name}</td>",
            f"<td>{quantity} units</td>",
            f"<td>{target_price} per unit</td></tr>",
            "</table>",
            "<p>Please include the following in your quotation:</p>",
            "<ul>",
            "<li>Unit price at stated quantity (FOB)</li>",
            "<li>Minimum order quantity (MOQ)</li>",
            "<li>Lead time and production capacity</li>",
            "<li>Payment terms</li>",
            "<li>Product specifications and certifications</li>",
            "</ul>",
            "<p>We look forward to your response within 3 business "
            "days.</p>",
            f"<p>Best regards,<br><strong>{company} Sourcing Team"
            "</strong></p>",
            '<hr style="border:none; border-top:1px solid #eee; '
            'margin-top:30px;">',
            '<p style="font-size:11px; color:#aaa;">',
            f"Reference: CONV-{conv_id.upper()} | USR-{user_id} "
            f"| THREAD-{conv_id.upper()}</p>",
            "</div>",
        ]
        return "".join(parts)

    # ── Provider-specific transmission (must be overridden) ──────────

    @abstractmethod
    def send_email(
        self,
        *,
        from_email: str,
        from_name: str,
        to_email: str,
        to_name: str,
        subject: str,
        html_body: str,
        reply_to: str,
        attachments: list | None = None,
    ) -> dict:
        """Transmit a single email through the concrete provider.

        Implementations perform the provider-specific network call and
        normalise the result so callers never depend on a provider's native
        response shape.

        Args:
            from_email (str): Verified sender address for the ``From``
                header.
            from_name (str): Display name for the ``From`` header.
            to_email (str): Recipient address.
            to_name (str): Recipient display name.
            subject (str): Subject line.
            html_body (str): HTML body of the message.
            reply_to (str): ``Reply-To`` address — the dynamic conversation
                address so replies route back correctly.
            attachments (list | None): Optional list of attachment dicts,
                each with keys ``filename`` (str), ``content`` (bytes) and
                ``content_type`` (str).

        Returns:
            dict: Normalised result with keys ``status_code`` (int),
                ``provider`` (str) and ``provider_message_id``
                (str | None).

        Raises:
            ProviderConfigError: If required credentials are missing.
            EmailSendError: If the provider rejects or fails the send.
        """
        raise NotImplementedError

    # ── Internal helpers shared by subclasses ────────────────────────

    def _require(self, value: str | None, name: str) -> str:
        """Return ``value`` or raise if it is missing/empty.

        Subclasses call this to validate that a required credential or
        setting is present before attempting a send.

        Args:
            value (str | None): The configuration value to check.
            name (str): The environment-variable name, used in the error
                message so operators know exactly what to fix.

        Returns:
            str: The validated, non-empty value.

        Raises:
            ProviderConfigError: If ``value`` is ``None`` or empty.

        Example:
            >>> provider._require("abc", "SENDGRID_API_KEY")
            'abc'
        """
        if not value:
            raise ProviderConfigError(
                f"Missing required configuration: {name}. "
                f"Set it in your .env file."
            )
        return value
