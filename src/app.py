"""FastAPI application factory for EmailPOC.

This module performs all dependency wiring exactly once and exposes the
ready-to-serve :data:`app` object that Uvicorn imports
(``src.app:app``). The construction order is:

1. Load configuration (:func:`src.config.get_settings`).
2. Configure the single shared logger from ``LOG_LEVEL``.
3. Build the async Postgres engine/session factory.
4. Build the active email provider and inbound webhook parser from
   ``EMAIL_PROVIDER`` via their factories.
5. Assemble the :class:`ConversationService`.
6. Mount static directories, register templates and include the routes.

Every collaborator is attached to ``app.state`` so the thin handlers in
:mod:`src.route` can reach them without re-constructing anything.

Example:
    >>> from src.app import app          # doctest: +SKIP
    >>> app.title                        # doctest: +SKIP
    'EmailPOC'
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.auth.dev_bypass import router as dev_bypass_router
from src.auth.routes import router as auth_router
from src.config import BASE_PATH, BEDROCK_BASE_PATH, get_settings
from src.db.repository import Repository
from src.db.session import create_engine_and_sessionmaker
from src.email_platform.factory import EmailProviderFactory
from src.logger import AppLogger
from src.route import router
from src.services.conversation_service import ConversationService
from src.webhook_factory.factory import WebhookParserFactory


def create_app() -> FastAPI:
    """Build, wire and return the FastAPI application.

    Construction is deliberately eager: if the configured provider is
    missing credentials, the matching factory raises immediately so the
    process fails fast at startup with a clear message rather than on the
    first request.

    Returns:
        FastAPI: A fully configured application with static mounts,
            templates and routes registered, and all collaborators stored on
            ``app.state``.

    Raises:
        ProviderConfigError: If ``EMAIL_PROVIDER`` is unknown or the active
            provider's required credentials are not set.

    Example:
        >>> app = create_app()           # doctest: +SKIP
        >>> "/webhooks/inbound" in {r.path for r in app.routes}  # noqa
        True
    """
    settings = get_settings()

    # 1. Configure the single shared logger from the env-driven level.
    logger = AppLogger.configure(settings.log_level)
    logger.info(
        "Starting EmailPOC (provider=%s, log_level=%s)",
        settings.email_provider,
        settings.log_level,
    )

    # 2. Ensure the directories the app reads/writes/serves all exist.
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)
    settings.static_dir.mkdir(parents=True, exist_ok=True)

    # 3. Build infrastructure + the active provider/parser pair.
    engine, session_factory = create_engine_and_sessionmaker(settings.database_url)
    db = Repository(session_factory, settings, logger)
    email_provider = EmailProviderFactory.create(
        settings.email_provider, settings, logger
    )
    webhook_parser = WebhookParserFactory.create(
        settings.email_provider, settings, logger
    )
    service = ConversationService(
        db, email_provider, webhook_parser, settings, logger
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await engine.dispose()

    # 4. Assemble the FastAPI app and register everything.
    app = FastAPI(title="EmailPOC", lifespan=lifespan)
    app.mount(
        f"{BASE_PATH}/static",
        StaticFiles(directory=str(settings.static_dir)),
        name="static",
    )
    app.mount(
        f"{BASE_PATH}/attachments",
        StaticFiles(directory=str(settings.attachments_dir)),
        name="attachments",
    )

    # 5. Stash collaborators so the route handlers stay construction-free.
    app.state.settings = settings
    app.state.log = logger
    app.state.db = db
    app.state.email_provider = email_provider
    app.state.webhook_parser = webhook_parser
    app.state.service = service
    app.state.templates = Jinja2Templates(
        directory=str(settings.templates_dir)
    )
    app.state.templates.env.globals["base_path"] = BASE_PATH

    app.include_router(auth_router, prefix=BASE_PATH)
    app.include_router(dev_bypass_router, prefix=BASE_PATH)
    app.include_router(router, prefix=BASE_PATH)

    # 6. Bare "/" landing page — links out to both POCs (this app's own
    # /email_poc routes, and the separately-running bedrock_availability_poc
    # container), so it's registered on the app directly rather than under
    # BASE_PATH.
    @app.get("/")
    async def landing(request: Request):
        # Prefer an explicit override (e.g. a reverse proxy fronting the
        # bedrock service on a different host/path); otherwise derive the
        # link from this very request's own host, so it's correct unmodified
        # on localhost, a LAN IP, or a production domain alike.
        bedrock_url = settings.bedrock_service_url or (
            f"{request.url.scheme}://{request.url.hostname}:"
            f"{settings.bedrock_port}{BEDROCK_BASE_PATH}/"
        )
        return app.state.templates.TemplateResponse(request, "landing.html", {
            "base_path": BASE_PATH,
            "bedrock_url": bedrock_url,
            "dev_bypass_enabled": settings.dev_bypass_login,
        })

    logger.info("EmailPOC application ready")
    return app


# The module-level application object Uvicorn imports as ``src.app:app``.
# Defined at import time so ``--reload`` can re-import it on file changes.
app = create_app()
