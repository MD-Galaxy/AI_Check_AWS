"""Environment-driven configuration for the EmailPOC application.

This module reads every tunable value from environment variables (loaded
from the project ``.env`` file) and exposes them through a single,
immutable :class:`Settings` object. Centralising configuration here means
no other module has to call :func:`os.getenv` directly, which keeps
provider classes, the webhook parsers and the routes free of scattered
environment lookups.

Configuration is grouped into three concerns:

1. **Global** – ``LOG_LEVEL`` and other app-wide settings.
2. **Per-provider credentials** – the API keys / outbound domain / display
   name each provider needs, e.g. ``ENGAGELAB_API_USER``,
   ``ENGAGELAB_OUTBOUND_DOMAIN``, ``ENGAGELAB_COMPANY_NAME``. There is no
   single "active" provider anymore — the sender picks a provider per send
   (see the "Provider" dropdown on the Send RFQ page,
   :func:`src.route.send_email_page`), and only the credentials for
   *whichever* provider is selected need to be configured;
   :meth:`Settings.provider_outbound_domain` /
   :meth:`Settings.provider_company_name` read them generically by
   provider key so adding a new provider needs no changes here — just its
   ``{PROVIDER}_*`` env vars, a new :class:`~src.email_platform.email_master.EmailMaster`
   subclass and a registration in
   :mod:`src.email_platform.factory`.
3. **Filesystem paths** – computed relative to the repository root so the
   application behaves the same regardless of the current working
   directory.

Example:
    >>> from src.config import get_settings
    >>> settings = get_settings()
    >>> settings.provider_outbound_domain("engagelab")
    'mail.jobsetu.online'
    >>> settings.attachments_dir.name
    'attachments'
"""

import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load ``.env`` exactly once, as early as possible. ``load_dotenv`` is
# idempotent, so importing this module from the Uvicorn reloader subprocess
# (which starts a brand-new interpreter) still picks up the variables.
load_dotenv()

# Repository root = the parent of the ``src`` package directory. Every
# filesystem path below is anchored here so paths never depend on the shell
# working directory the server was launched from.
BASE_DIR = Path(__file__).resolve().parents[1]

# URL prefix the whole app is served under, e.g. http://0.0.0.0:8000/email_poc/.
# Every route, redirect, cookie path, static/attachment mount and template
# link is anchored to this so the app can be moved to a different prefix by
# changing this one constant.
BASE_PATH = "/email_poc"

# Base path the Bedrock Availability POC's routes are mounted under (see
# src/app.py, which pulls in bedrock_availability_poc/app.py's router into
# this same process/port). Must match BASE_PATH in
# bedrock_availability_poc/app.py.
BEDROCK_BASE_PATH = "/check-bedrock"


class Settings:
    """Immutable snapshot of all application configuration.

    A single instance is built once (via :func:`get_settings`) at startup
    and then dependency-injected into the database, the email provider, the
    webhook parser and the service layer. Treat instances as read-only.

    Attributes:
        log_level (str): Logging threshold name, e.g. ``"DEBUG"`` or
            ``"INFO"``. Consumed by :class:`src.logger.AppLogger`.
        sendgrid_api_key (str | None): SendGrid API key.
        mailgun_api_key (str | None): Mailgun private API key.
        mailgun_domain (str | None): Mailgun sending domain.
        mailgun_api_base (str): Mailgun API base URL — ``api.mailgun.net``
            for the US region or ``api.eu.mailgun.net`` for the EU region.
        mailgun_signing_key (str | None): Mailgun HTTP webhook signing key
            used to verify inbound POST authenticity.
        elasticemail_api_key (str | None): Elastic Email API key.
        elasticemail_api_url (str): Elastic Email v4 REST base URL.
        sendcloud_api_user (str | None): SendCloud ``API_USER`` credential.
        sendcloud_api_key (str | None): SendCloud ``API_KEY`` credential.
        sendcloud_api_base (str): SendCloud REST base URL (region-specific).
        engagelab_api_user (str | None): EngageLab ``API_USER`` credential.
        engagelab_api_key (str | None): EngageLab ``API_KEY`` credential.
        engagelab_api_base (str): EngageLab REST base URL (region-specific).
        base_dir (Path): Repository root directory.
        data_dir (Path): Directory holding the JSON store and attachments.
        attachments_dir (Path): Directory where inbound attachments land.
        static_dir (Path): Directory served at ``/static``.
        templates_dir (Path): Jinja2 templates directory.
        db_path (Path): Path to the JSON store file.

    Example:
        >>> s = Settings()
        >>> s.provider_outbound_domain("engagelab")
        'mail.jobsetu.online'
    """

    def __init__(self) -> None:
        """Read every configuration value from the environment.

        All values are resolved here so the rest of the application can rely
        on plain attribute access. Missing optional values fall back to
        sensible defaults; missing *required* values are validated lazily by
        whichever provider actually needs them (so, for example, you can run
        the SendGrid provider without setting any Mailgun variables).

        Returns:
            None
        """
        # ── Database ──────────────────────────────────────────────────
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5433/emailpoc",
        )

        # ── Auth / sessions ───────────────────────────────────────────
        # Signs the short-lived "pending registration" cookie used between
        # the registration wizard's steps (§3.2) — NOT used for session
        # tokens themselves (those are random + DB-verified, unaffected by
        # this key). Falling back to a fresh random value means existing
        # in-progress registrations are invalidated on every restart; set it
        # explicitly for anything longer-lived than local dev.
        self.secret_key = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
        self.session_ttl_days = int(os.getenv("SESSION_TTL_DAYS", "7"))
        self.session_cookie_secure = (
            os.getenv("SESSION_COOKIE_SECURE", "true").strip().lower() == "true"
        )
        # Local-dev-only login bypass (see src/auth/dev_bypass.py). Off by
        # default so a stray deploy never exposes an unauthenticated login.
        self.dev_bypass_login = (
            os.getenv("DEV_BYPASS_LOGIN", "false").strip().lower() == "true"
        )

        # ── Global settings ──────────────────────────────────────────
        self.log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

        # ── SendGrid credentials ─────────────────────────────────────
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")

        # ── Mailgun credentials ──────────────────────────────────────
        self.mailgun_api_key = os.getenv("MAILGUN_API_KEY")
        self.mailgun_domain = os.getenv("MAILGUN_DOMAIN")
        self.mailgun_api_base = os.getenv(
            "MAILGUN_API_BASE", "https://api.mailgun.net"
        ).rstrip("/")
        self.mailgun_signing_key = os.getenv("MAILGUN_WEBHOOK_SIGNING_KEY")

        # ── Elastic Email credentials ────────────────────────────────
        self.elasticemail_api_key = os.getenv("ELASTICEMAIL_API_KEY")
        self.elasticemail_api_url = os.getenv(
            "ELASTICEMAIL_API_URL", "https://api.elasticemail.com/v4"
        ).rstrip("/")

        # ── SendCloud credentials ─────────────────────────────────────
        self.sendcloud_api_user = os.getenv("SENDCLOUD_API_USER")
        self.sendcloud_api_key = os.getenv("SENDCLOUD_API_KEY")
        # Singapore region (default): https://api.aurorasendcloud.com
        # US region: https://api-us.aurorasendcloud.com
        # CN (Hong Kong SAR) region: https://api-hk.aurorasendcloud.com
        self.sendcloud_api_base = os.getenv(
            "SENDCLOUD_API_BASE", "https://api.aurorasendcloud.com"
        ).rstrip("/")

        # ── EngageLab credentials ────────────────────────────────────
        self.engagelab_api_user = os.getenv("ENGAGELAB_API_USER")
        self.engagelab_api_key = os.getenv("ENGAGELAB_API_KEY")
        # Singapore region (default): https://email.api.engagelab.cc
        # Turkey region: https://emailapi-tr.engagelab.com
        self.engagelab_api_base = os.getenv(
            "ENGAGELAB_API_BASE", "https://email.api.engagelab.cc"
        ).rstrip("/")

        # ── Bedrock Availability POC (linked from the "/" landing page) ──
        # Full override for the "Check Bedrock" button's target URL. Leave
        # unset (the default) to auto-derive it from the incoming request's
        # own host/port + BEDROCK_BASE_PATH — that works unmodified for both
        # local dev and a production host, since the Bedrock routes are
        # mounted on this very app. Set this explicitly only when a reverse
        # proxy fronts this app under a different external host/path than
        # the one it sees the request on.
        self.bedrock_service_url = os.getenv("BEDROCK_SERVICE_URL") or None

        # ── Filesystem paths (anchored at the repository root) ───────
        self.base_dir = BASE_DIR
        self.data_dir = BASE_DIR / "data"
        self.attachments_dir = self.data_dir / "attachments"
        self.static_dir = BASE_DIR / "static"
        self.templates_dir = BASE_DIR / "templates"
        self.db_path = self.data_dir / "db.json"

    # ── Per-provider outbound domain / display name ───────────────────
    # These are read generically by provider key rather than as fixed
    # attributes above, so a brand-new provider only needs its
    # ``{PROVIDER}_OUTBOUND_DOMAIN`` / ``{PROVIDER}_COMPANY_NAME`` env vars
    # (plus a new EmailMaster subclass registered in
    # src/email_platform/factory.py) — nothing here has to change.

    def provider_outbound_domain(self, provider_name: str) -> str:
        """Return the sending domain configured for ``provider_name``.

        Used to build both the per-conversation dynamic Reply-To address
        and the From address (see
        :meth:`~src.email_platform.email_master.EmailMaster.build_dynamic_email`
        / :meth:`~src.email_platform.email_master.EmailMaster.build_sending_email`).
        Different providers can use different domains, e.g.
        ``ENGAGELAB_OUTBOUND_DOMAIN`` vs ``SENDCLOUD_OUTBOUND_DOMAIN`` — keep
        them equal across providers unless the inbound webhook parser is
        also taught to check every configured domain, since only one
        provider's parser handles ``POST /webhooks/inbound`` (see
        :func:`src.app.create_app`).

        Args:
            provider_name (str): Provider key, e.g. ``"engagelab"``.

        Returns:
            str: The configured domain, or ``""`` if unset.

        Example:
            >>> Settings().provider_outbound_domain("engagelab")
            'mail.jobsetu.online'
        """
        return os.getenv(f"{provider_name.strip().upper()}_OUTBOUND_DOMAIN", "")

    def provider_company_name(self, provider_name: str) -> str:
        """Return the From-header display name configured for ``provider_name``.

        Args:
            provider_name (str): Provider key, e.g. ``"engagelab"``.

        Returns:
            str: The configured display name, or ``"Your Company"`` if unset.

        Example:
            >>> Settings().provider_company_name("engagelab")
            'JobSetu'
        """
        return os.getenv(
            f"{provider_name.strip().upper()}_COMPANY_NAME", "Your Company"
        )

    @property
    def default_outbound_domain(self) -> str:
        """Best-effort domain for contexts with no provider chosen yet.

        Registration (the permanent ``sending_email`` preview/assignment in
        :mod:`src.auth.routes`), the dev-bypass "John Carter" shortcut
        (:mod:`src.auth.dev_bypass`) and generated Message-ID hosts
        (:meth:`~src.db.repository.Repository._generate_message_id`) all
        need *some* domain before any provider has been picked on the Send
        RFQ form. Prefers EngageLab's (the provider with real inbound reply
        parsing), falling back to SendCloud's — extend this if another
        provider becomes the preferred default.

        Returns:
            str: The first configured candidate domain, or ``""`` if none
                are set.
        """
        return (
            self.provider_outbound_domain("engagelab")
            or self.provider_outbound_domain("sendcloud")
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    The result is cached with :func:`functools.lru_cache` so the
    environment is parsed only once per process and every caller shares the
    exact same object.

    Returns:
        Settings: The cached configuration snapshot.

    Example:
        >>> from src.config import get_settings
        >>> get_settings() is get_settings()
        True
    """
    return Settings()
