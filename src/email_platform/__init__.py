"""Pluggable outbound email providers for EmailPOC.

This package implements the *strategy + factory* pattern for sending email:

- :mod:`src.email_platform.email_master` defines :class:`EmailMaster`, the
  abstract base holding every behaviour shared across providers (dynamic
  address generation/parsing, RFQ subject/body rendering).
- :mod:`src.email_platform.sendgrid_provider`,
  :mod:`src.email_platform.mailgun_provider` and
  :mod:`src.email_platform.elasticemail_provider` are the concrete
  providers, each implementing only the provider-specific
  :meth:`EmailMaster.send_email`.
- :mod:`src.email_platform.factory` exposes
  :class:`EmailProviderFactory`, which returns the provider selected by the
  ``EMAIL_PROVIDER`` environment variable.

Import the factory (not the concrete providers) so the active provider
stays a configuration choice:

    >>> from src.email_platform.factory import EmailProviderFactory
"""

from src.email_platform.email_master import (
    EmailMaster,
    EmailProviderError,
    EmailSendError,
    ProviderConfigError,
)
from src.email_platform.factory import EmailProviderFactory

__all__ = [
    "EmailMaster",
    "EmailProviderError",
    "EmailSendError",
    "ProviderConfigError",
    "EmailProviderFactory",
]
