"""Outbound email provider backed by the Twilio SendGrid API.

:class:`SendGridEmailProvider` implements :meth:`EmailMaster.send_email`
using the official :mod:`sendgrid` Python SDK. The ``From`` header is
whatever address the caller passes in —
:meth:`~src.services.conversation_service.ConversationService.send_rfq`
builds it fresh per send via
:meth:`~src.email_platform.email_master.EmailMaster.build_sending_email` —
and the ``Reply-To`` header is the dynamic conversation address so that
supplier replies are delivered back to SendGrid's Inbound Parse and
forwarded to this app's webhook.

Configuration consumed (see :class:`src.config.Settings`):

- ``SENDGRID_API_KEY`` *(required)* – API key with **Mail Send** access.
- ``SENDGRID_OUTBOUND_DOMAIN`` *(required)* – domain used to build the
  ``From`` and dynamic Reply-To addresses for sends made through SendGrid.
- ``SENDGRID_COMPANY_NAME`` – display name in the ``From`` header (defaults
  to ``"Your Company"``).

Example:
    >>> from src.email_platform.sendgrid_provider import (
    ...     SendGridEmailProvider)
    >>> from src.config import get_settings
    >>> from src.logger import AppLogger
    >>> provider = SendGridEmailProvider(get_settings(), AppLogger.get())
    >>> provider.provider_name
    'sendgrid'
"""

import base64
import logging

import sendgrid
from sendgrid.helpers.mail import (
    Attachment,
    Disposition,
    FileContent,
    FileName,
    FileType,
    From,
    Mail,
    ReplyTo,
    To,
)

from src.config import Settings
from src.email_platform.email_master import EmailMaster, EmailSendError


class SendGridEmailProvider(EmailMaster):
    """Send RFQ emails through the SendGrid REST API.

    Inherits all address and template helpers from :class:`EmailMaster` and
    adds the SendGrid-specific transmission logic.

    Attributes:
        settings (Settings): Shared application configuration.
        log (logging.Logger): Shared application logger.

    Example:
        >>> provider = SendGridEmailProvider(settings, logger)
        >>> result = provider.send_email(            # doctest: +SKIP
        ...     from_email="noreply@yourdomain.com", from_name="Acme",
        ...     to_email="buyer@x.com", to_name="Buyer",
        ...     subject="Hi", html_body="<p>Hi</p>",
        ...     reply_to="usr42_conv3fa9c1b2@mail.yourdomain.com")
        >>> result["status_code"]                    # doctest: +SKIP
        202
    """

    def __init__(
        self, settings: Settings, logger: logging.Logger
    ) -> None:
        """Initialise the provider and the SendGrid client.

        The API key is validated immediately so misconfiguration fails fast
        at startup rather than on the first send attempt.

        Args:
            settings (Settings): Shared application configuration.
            logger (logging.Logger): Shared application logger.

        Returns:
            None

        Raises:
            ProviderConfigError: If ``SENDGRID_API_KEY`` is not set.
        """
        super().__init__(settings, logger)
        api_key = self._require(
            settings.sendgrid_api_key, "SENDGRID_API_KEY"
        )
        # The SDK client is stateless and reusable across requests.
        self._client = sendgrid.SendGridAPIClient(api_key=api_key)
        self.log.info("SendGrid provider initialised")

    @property
    def provider_name(self) -> str:
        """Return the provider key ``"sendgrid"``.

        Returns:
            str: Always ``"sendgrid"``.
        """
        return "sendgrid"

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
        """Send one email via SendGrid and normalise the result.

        Builds a :class:`sendgrid.helpers.mail.Mail` message with the given
        headers, sets ``Reply-To`` to the dynamic conversation address and
        submits it. SendGrid returns HTTP ``202`` when the message is queued.

        Args:
            from_email (str): Sender address for the ``From`` header —
                built per send via ``EmailMaster.build_sending_email``.
            from_name (str): Sender display name.
            to_email (str): Recipient address.
            to_name (str): Recipient display name.
            subject (str): Subject line.
            html_body (str): HTML body.
            reply_to (str): Dynamic conversation address used as
                ``Reply-To``.

        Returns:
            dict: ``{"status_code": int, "provider": "sendgrid",
                "provider_message_id": str | None}``.

        Raises:
            EmailSendError: If the SendGrid SDK raises or the network call
                fails. The original exception text is preserved.

        Example:
            >>> provider.send_email(                  # doctest: +SKIP
            ...     from_email="noreply@yourdomain.com",
            ...     from_name="Acme", to_email="buyer@x.com",
            ...     to_name="Buyer", subject="Hi",
            ...     html_body="<p>Hi</p>",
            ...     reply_to="usr42_conv3fa9c1b2@mail.yourdomain.com")
            {'status_code': 202, 'provider': 'sendgrid', ...}
        """
        try:
            message = Mail(
                from_email=From(from_email, from_name),
                to_emails=To(to_email, to_name),
                subject=subject,
                html_content=html_body,
            )
            # Reply-To carries the dynamic address so supplier replies flow
            # back through SendGrid Inbound Parse to the webhook.
            message.reply_to = ReplyTo(reply_to)

            for att in (attachments or []):
                sg_att = Attachment(
                    FileContent(
                        base64.b64encode(att["content"]).decode()
                    ),
                    FileName(att["filename"]),
                    FileType(
                        att.get("content_type", "application/octet-stream")
                    ),
                    Disposition("attachment"),
                )
                message.add_attachment(sg_att)

            response = self._client.send(message)

            # SendGrid exposes the provider message id in the response
            # headers under ``X-Message-Id`` when available.
            headers = getattr(response, "headers", {}) or {}
            message_id = None
            if hasattr(headers, "get"):
                message_id = headers.get("X-Message-Id")

            self.log.info(
                "SendGrid accepted email to %s (status=%s)",
                to_email,
                response.status_code,
            )
            return {
                "status_code": response.status_code,
                "provider": self.provider_name,
                "provider_message_id": message_id,
            }
        except Exception as exc:  # noqa: BLE001 - normalise to one type
            self.log.error("SendGrid send failed: %s", exc)
            raise EmailSendError(
                f"SendGrid failed to send email to {to_email}: {exc}"
            ) from exc
