"""Application entry point for EmailPOC + the Bedrock Availability POC.

This is the only Python module that lives at the repository root; all
application code lives under the :mod:`src` package (which also mounts
``bedrock_availability_poc``'s routes — see ``src/app.py``). The entry point
loads ``.env`` and starts the Uvicorn ASGI server pointing at
:data:`src.app.app`. Hot-reload is enabled so the server restarts when any
``.py`` or template file changes during development.

Usage::

    # Recommended:
    uv run python main.py

    # Or directly via uvicorn:
    uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
"""

from dotenv import load_dotenv

# Load environment variables before anything imports the configuration.
load_dotenv()

import uvicorn  # noqa: E402 - must follow load_dotenv()

# Bind address and port for the development server. Both POCs are served
# from this one port — EmailPOC at /email_poc, Bedrock Availability POC at
# /check-bedrock, and the landing page at /.
_HOST = "0.0.0.0"
_PORT = 8000


def main() -> None:
    """Start the Uvicorn server with hot-reload enabled.

    Binds to all interfaces on port ``8000``. The application is referenced
    by its import string (``"src.app:app"``) rather than the object so that
    ``reload=True`` can re-import it on file changes. In production replace
    ``reload=True`` with ``workers=N`` and front Uvicorn with a reverse
    proxy (nginx / Caddy).

    Returns:
        None

    Example:
        $ uv run python main.py
        INFO: Uvicorn running on http://0.0.0.0:8000 (CTRL+C to quit)
    """
    uvicorn.run(
        "src.app:app",
        host=_HOST,
        port=_PORT,
        reload=True,
    )


if __name__ == "__main__":
    main()
