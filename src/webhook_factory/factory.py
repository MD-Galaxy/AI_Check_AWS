"""Factory that builds inbound webhook parser instances.

:class:`WebhookParserFactory` maps a provider key to the matching
:class:`~src.webhook_factory.webhook_master.WebhookParserMaster` subclass
so the single ``POST /webhooks/inbound`` route can decode that provider's
payload. The app builds exactly one parser at startup
(``src.app._INBOUND_EMAIL_PROVIDER``), since this one endpoint only
understands one payload format at a time. It mirrors
:class:`src.email_platform.factory.EmailProviderFactory` on the inbound
side.

Example:
    >>> from src.webhook_factory.factory import WebhookParserFactory
    >>> from src.config import get_settings
    >>> from src.logger import AppLogger
    >>> parser = WebhookParserFactory.create(
    ...     "sendgrid", get_settings(), AppLogger.get())
    >>> parser.provider_name
    'sendgrid'
"""

import logging

from src.config import Settings
from src.email_platform.email_master import ProviderConfigError
from src.webhook_factory.elasticemail_webhook import (
    ElasticEmailWebhookParser,
)
from src.webhook_factory.engagelab_webhook import EngageLabWebhookParser
from src.webhook_factory.mailgun_webhook import MailgunWebhookParser
from src.webhook_factory.sendcloud_webhook import SendCloudWebhookParser
from src.webhook_factory.sendgrid_webhook import SendGridWebhookParser
from src.webhook_factory.webhook_master import WebhookParserMaster

# Registry mapping the lowercase provider key to its parser class. Keep the
# keys identical to those in the email-provider factory so the same
# provider key can build either a send-side or receive-side instance.
#
# NOTE: "sendcloud" maps to a stub parser (SendCloud's inbound webhook
# payload has not been documented yet) — outbound sending works, inbound
# replies fail with a clear "not implemented" error instead of crashing.
_PARSERS: dict[str, type[WebhookParserMaster]] = {
    "sendgrid": SendGridWebhookParser,
    "mailgun": MailgunWebhookParser,
    "elasticemail": ElasticEmailWebhookParser,
    "sendcloud": SendCloudWebhookParser,
    "engagelab": EngageLabWebhookParser,
}


class WebhookParserFactory:
    """Construct the configured inbound webhook parser instance.

    The factory is stateless; it exposes a single classmethod that performs
    the lookup-and-instantiate step.

    Example:
        >>> WebhookParserFactory.supported()
        ['sendgrid', 'mailgun', 'elasticemail', 'sendcloud', 'engagelab']
    """

    @classmethod
    def create(
        cls,
        provider_name: str,
        settings: Settings,
        logger: logging.Logger,
    ) -> WebhookParserMaster:
        """Instantiate the parser identified by ``provider_name``.

        Args:
            provider_name (str): Provider key, e.g. ``"mailgun"``. Matched
                case-insensitively after trimming whitespace.
            settings (Settings): Shared application configuration passed to
                the parser constructor.
            logger (logging.Logger): Shared application logger passed to the
                parser constructor.

        Returns:
            WebhookParserMaster: A fully constructed parser instance.

        Raises:
            ProviderConfigError: If ``provider_name`` is not a registered
                provider (same error type as the email-provider factory, so
                callers can handle both factories uniformly).

        Example:
            >>> parser = WebhookParserFactory.create(
            ...     "mailgun", settings, logger)   # doctest: +SKIP
            >>> parser.provider_name               # doctest: +SKIP
            'mailgun'
        """
        key = (provider_name or "").strip().lower()
        parser_cls = _PARSERS.get(key)
        if parser_cls is None:
            supported = ", ".join(_PARSERS)
            raise ProviderConfigError(
                f"Unknown email provider '{provider_name}' for webhook "
                f"parsing. Supported providers: {supported}."
            )
        logger.info("Selected inbound webhook parser: %s", key)
        return parser_cls(settings, logger)

    @classmethod
    def supported(cls) -> list[str]:
        """Return the list of registered parser keys.

        Returns:
            list[str]: Provider keys in registration order.

        Example:
            >>> "mailgun" in WebhookParserFactory.supported()
            True
        """
        return list(_PARSERS)
