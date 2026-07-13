"""Factory that builds the active outbound email provider.

:class:`EmailProviderFactory` maps the ``EMAIL_PROVIDER`` configuration
value to the matching :class:`~src.email_platform.email_master.EmailMaster`
subclass and returns a ready-to-use instance. Callers never import a
concrete provider directly, so swapping providers is a one-line ``.env``
change with no code edits.

Example:
    >>> from src.email_platform.factory import EmailProviderFactory
    >>> from src.config import get_settings
    >>> from src.logger import AppLogger
    >>> provider = EmailProviderFactory.create(
    ...     "sendgrid", get_settings(), AppLogger.get())
    >>> provider.provider_name
    'sendgrid'
"""

import logging

from src.config import Settings
from src.email_platform.elasticemail_provider import ElasticEmailProvider
from src.email_platform.email_master import EmailMaster, ProviderConfigError
from src.email_platform.engagelab_provider import EngageLabEmailProvider
from src.email_platform.mailgun_provider import MailgunEmailProvider
from src.email_platform.sendcloud_provider import SendCloudEmailProvider
from src.email_platform.sendgrid_provider import SendGridEmailProvider

# Registry mapping the lowercase provider key to its implementation class.
# Add a new provider by writing its class and registering it here — nothing
# else in the application needs to change.
_PROVIDERS: dict[str, type[EmailMaster]] = {
    "sendgrid": SendGridEmailProvider,
    "mailgun": MailgunEmailProvider,
    "elasticemail": ElasticEmailProvider,
    "sendcloud": SendCloudEmailProvider,
    "engagelab": EngageLabEmailProvider,
}


class EmailProviderFactory:
    """Construct the configured email provider instance.

    The factory is stateless; it exposes a single classmethod that performs
    the lookup-and-instantiate step.

    Example:
        >>> EmailProviderFactory.supported()
        ['sendgrid', 'mailgun', 'elasticemail', 'sendcloud', 'engagelab']
    """

    @classmethod
    def create(
        cls,
        provider_name: str,
        settings: Settings,
        logger: logging.Logger,
    ) -> EmailMaster:
        """Instantiate the provider identified by ``provider_name``.

        Args:
            provider_name (str): Provider key, e.g. ``"sendgrid"``. Matched
                case-insensitively after trimming whitespace.
            settings (Settings): Shared application configuration passed to
                the provider constructor.
            logger (logging.Logger): Shared application logger passed to the
                provider constructor.

        Returns:
            EmailMaster: A fully constructed provider instance.

        Raises:
            ProviderConfigError: If ``provider_name`` is not a registered
                provider. The message lists the supported keys.

        Example:
            >>> provider = EmailProviderFactory.create(
            ...     "mailgun", settings, logger)   # doctest: +SKIP
            >>> provider.provider_name             # doctest: +SKIP
            'mailgun'
        """
        key = (provider_name or "").strip().lower()
        provider_cls = _PROVIDERS.get(key)
        if provider_cls is None:
            supported = ", ".join(_PROVIDERS)
            raise ProviderConfigError(
                f"Unknown EMAIL_PROVIDER '{provider_name}'. "
                f"Supported providers: {supported}."
            )
        logger.info("Selected email provider: %s", key)
        return provider_cls(settings, logger)

    @classmethod
    def supported(cls) -> list[str]:
        """Return the list of registered provider keys.

        Returns:
            list[str]: Provider keys in registration order.

        Example:
            >>> "sendgrid" in EmailProviderFactory.supported()
            True
        """
        return list(_PROVIDERS)
