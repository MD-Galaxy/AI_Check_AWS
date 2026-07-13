"""Async SQLAlchemy engine/session factory for EmailPOC.

One engine is created per process (in :func:`create_engine_and_sessionmaker`,
called once from :func:`src.app.create_app`) and handed to every request via
``app.state``. Routes never construct a session themselves — they go through
:class:`~src.db.repository.Repository`, which owns the session lifecycle for
each call.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_sessionmaker(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Build the async engine and a bound session factory.

    Args:
        database_url (str): SQLAlchemy async connection string, e.g.
            ``"postgresql+asyncpg://user:pass@host:5432/dbname"``.

    Returns:
        tuple[AsyncEngine, async_sessionmaker[AsyncSession]]: The engine
            (call ``await engine.dispose()`` on shutdown) and a session
            factory for creating one ``AsyncSession`` per unit of work.
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
