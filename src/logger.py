"""Centralised, configurable application logger for EmailPOC.

The whole application logs through **one** shared :class:`logging.Logger`
instance so that every line — whether emitted by a route, a provider or the
webhook parser — uses the same format and the same level. The level is read
from the ``LOG_LEVEL`` environment variable (via
:class:`src.config.Settings`), so operators can switch between ``DEBUG`` in
development and ``WARNING`` in production without touching code.

The :class:`AppLogger` helper builds that logger on first use and hands the
same object back on every subsequent call. The application factory
(:mod:`src.app`) configures it once at startup and then passes the instance
into the database, the email provider, the webhook parser and the service
layer.

Example:
    >>> from src.logger import AppLogger
    >>> log = AppLogger.configure("DEBUG")
    >>> log.info("server starting")          # doctest: +SKIP
    2026-06-23 10:00:00 | INFO | emailpoc | server starting
    >>> AppLogger.get() is log               # same shared object
    True
"""

import logging
import sys

# Name of the single logger every module shares. Using a fixed name means
# ``logging.getLogger(LOGGER_NAME)`` returns the identical object anywhere.
LOGGER_NAME = "emailpoc"

# Human-readable log line: timestamp | LEVEL | logger | message.
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class AppLogger:
    """Factory and accessor for the single shared application logger.

    The class never holds per-instance state; both methods operate on the
    module-level :data:`LOGGER_NAME` logger so the application has exactly
    one logger object regardless of how many times the helpers are called.

    Example:
        >>> log = AppLogger.configure("INFO")
        >>> log2 = AppLogger.get()
        >>> log is log2
        True
    """

    @classmethod
    def configure(
        cls, level: str = "INFO", name: str = LOGGER_NAME
    ) -> logging.Logger:
        """Build (or reconfigure) the shared logger and return it.

        Attaches a single ``StreamHandler`` writing to ``stdout`` with the
        standard format, sets the threshold from ``level`` and disables
        propagation so records are not duplicated by the root logger. Calling
        this more than once is safe: the existing handler is reused and only
        the level is updated, so no duplicate handlers accumulate (which would
        otherwise print every line multiple times).

        Args:
            level (str): Logging threshold name such as ``"DEBUG"``,
                ``"INFO"``, ``"WARNING"`` or ``"ERROR"``. Unknown values fall
                back to ``INFO``.
            name (str): Logger name. Defaults to the shared
                :data:`LOGGER_NAME`; override only in isolated tests.

        Returns:
            logging.Logger: The configured shared logger.

        Example:
            >>> log = AppLogger.configure("DEBUG")
            >>> log.level == logging.DEBUG
            True
        """
        logger = logging.getLogger(name)

        # Map the textual level to its numeric constant; default to INFO so a
        # typo in ``LOG_LEVEL`` never silences the application entirely.
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        logger.setLevel(numeric_level)

        # Only attach a handler the first time — repeat calls (e.g. on reload)
        # must not stack handlers and emit each record multiple times.
        if not logger.handlers:
            handler = logging.StreamHandler(stream=sys.stdout)
            handler.setFormatter(
                logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
            )
            logger.addHandler(handler)

        # Records stop here instead of also bubbling up to the root logger,
        # which would print every line a second time.
        logger.propagate = False
        return logger

    @classmethod
    def get(cls, name: str = LOGGER_NAME) -> logging.Logger:
        """Return the shared logger, configuring it on demand.

        Use this from code that did not receive an injected logger and just
        needs the shared instance. If :meth:`configure` has not run yet the
        logger is created with default settings.

        Args:
            name (str): Logger name. Defaults to :data:`LOGGER_NAME`.

        Returns:
            logging.Logger: The shared logger.

        Example:
            >>> AppLogger.get().name
            'emailpoc'
        """
        logger = logging.getLogger(name)
        if not logger.handlers:
            # Never configured yet — build it with defaults so callers always
            # get a usable, formatted logger.
            return cls.configure(name=name)
        return logger
