"""EmailPOC application package.

This package contains the full FastAPI application for the dynamic RFQ
email manager:

- :mod:`src.config` – environment-driven configuration.
- :mod:`src.logger` – the single shared application logger.
- :mod:`src.db` – the thread-safe JSON persistence layer.
- :mod:`src.email_platform` – pluggable outbound email providers
  (SendGrid, Mailgun, Elastic Email) behind a common base + factory.
- :mod:`src.webhook_factory` – pluggable inbound webhook parsers behind a
  common base + factory.
- :mod:`src.services` – business logic that ties the pieces together.
- :mod:`src.route` – the HTTP routes (UI + the single inbound webhook).
- :mod:`src.app` – the FastAPI application factory and the ``app`` object.

The only module that lives at the repository root is ``main.py``, which
simply boots the Uvicorn server pointing at :data:`src.app.app`.
"""
