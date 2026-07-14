"""Async Postgres-backed façade that replaces the old ``EmailDB`` JSON store.

Exposes (almost) the exact same method surface as the old ``src/db.py`` so
:class:`~src.services.conversation_service.ConversationService` needed only
``await`` added at call sites, not a rewrite (per MIGRATION_PLAN.md §2.4).
Every public method opens and closes its own session — callers never see a
:class:`~sqlalchemy.ext.asyncio.AsyncSession`.

Dropped versus the old surface (per MIGRATION_PLAN.md §2.2's notes — these
existed only because JSON has no joins): ``insert_user_conversation``,
``insert_thread``, ``get_thread``, ``get_user_conversation_info``. Plain SQL
joins on ``conversations.user_id`` replace them.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src.config import Settings
from src.db.models import (
    Attachment,
    Conversation,
    Email,
    Product,
    UnmatchedEmail,
    User,
    UserSession,
)


class DuplicateConversationTokenError(Exception):
    """Raised when a freshly generated 8-char conversation token collides.

    The ``conversations.token`` column is ``UNIQUE`` at the DB level (see
    ``sql/schema.sql``); this exception is how that constraint violation
    surfaces so the caller can mint a new token and retry, mirroring the
    collision-retry pattern MIGRATION_PLAN.md §3.2 specifies for
    ``sending_email`` assignment.
    """


class DuplicatePersonalEmailError(Exception):
    """Raised when a registration's ``personal_email`` is already taken."""


class DuplicateSendingEmailError(Exception):
    """Raised when a candidate ``sending_email`` collides with another user's."""


class Repository:
    """Async façade over every table in the Postgres schema.

    Attributes:
        settings (Settings): Shared application configuration.
        log (logging.Logger): Shared application logger.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        self._session_factory = session_factory
        self.settings = settings
        self.log = logger

    def _session(self) -> AsyncSession:
        return self._session_factory()

    # ── Users / products (read-only catalog lookups) ───────────────────

    async def get_predefined_users(self) -> list[dict]:
        async with self._session() as session:
            result = await session.execute(select(User).order_by(User.created_at))
            return [self._user_to_dict(u) for u in result.scalars()]

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with self._session() as session:
            user = await session.get(User, self._as_uuid(user_id))
            return self._user_to_dict(user) if user else None

    async def get_predefined_projects(self) -> list[dict]:
        async with self._session() as session:
            result = await session.execute(select(Product).order_by(Product.created_at))
            return [{"id": str(p.id), "product_name": p.name} for p in result.scalars()]

    async def get_project_by_id(self, project_id: str) -> dict | None:
        async with self._session() as session:
            product = await session.get(Product, self._as_uuid(project_id))
            return {"id": str(product.id), "product_name": product.name} if product else None

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        return {
            "id": str(user.id),
            "full_name": f"{user.first_name} {user.last_name}".strip(),
            "email": user.personal_email,
        }

    # ── Auth: users ──────────────────────────────────────────────────────

    async def create_pending_user(
        self, first_name: str, last_name: str, personal_email: str, password_hash: str
    ) -> dict:
        """Insert a new ``status='pending'`` user (registration wizard step 1).

        Raises:
            DuplicatePersonalEmailError: If ``personal_email`` is already
                registered.
        """
        async with self._session() as session:
            row = User(
                id=uuid.uuid4(),
                first_name=first_name,
                last_name=last_name,
                personal_email=personal_email,
                password_hash=password_hash,
                status="pending",
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if self._is_unique_violation(exc, "uq_users_personal_email"):
                    raise DuplicatePersonalEmailError(personal_email) from exc
                raise
            return self._auth_user_to_dict(row)

    async def get_user_auth_by_personal_email(self, personal_email: str) -> dict | None:
        async with self._session() as session:
            user = (
                await session.execute(
                    select(User).where(User.personal_email == personal_email)
                )
            ).scalar_one_or_none()
            return self._auth_user_to_dict(user) if user else None

    async def get_user_auth_by_id(self, user_id: str) -> dict | None:
        async with self._session() as session:
            user = await session.get(User, self._as_uuid(user_id))
            return self._auth_user_to_dict(user) if user else None

    async def get_user_by_sending_email(self, sending_email: str) -> dict | None:
        """Reverse-lookup the user who owns a permanent ``sending_email``.

        Used to bind a supplier's brand-new (headerless) email to its owning
        user when it carries no conv_id anywhere — see
        :meth:`~src.services.conversation_service.ConversationService._match_new_thread`.
        ``sending_email`` is ``UNIQUE`` (``uq_users_sending_email``), so at
        most one user can match.

        Args:
            sending_email (str): The bare address to look up (case-insensitive).

        Returns:
            dict | None: The auth-shaped user dict (see
                :meth:`_auth_user_to_dict`), or ``None`` if no user has this
                ``sending_email``.
        """
        async with self._session() as session:
            user = (
                await session.execute(
                    select(User).where(
                        func.lower(User.sending_email) == sending_email.lower()
                    )
                )
            ).scalar_one_or_none()
            return self._auth_user_to_dict(user) if user else None

    async def assign_sending_email(self, user_id: str, sending_email: str) -> dict:
        """Finish registration: set the permanent ``sending_email`` and activate.

        Raises:
            DuplicateSendingEmailError: If ``sending_email`` collides with
                another user's (race with a concurrent registration picking
                the same prefix — see MIGRATION_PLAN.md §3.2).
        """
        async with self._session() as session:
            user = await session.get(User, self._as_uuid(user_id))
            if user is None:
                raise ValueError(f"Unknown user_id: {user_id}")
            user.sending_email = sending_email
            user.status = "active"
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if self._is_unique_violation(exc, "uq_users_sending_email"):
                    raise DuplicateSendingEmailError(sending_email) from exc
                raise
            return self._auth_user_to_dict(user)

    @staticmethod
    def _auth_user_to_dict(user: User) -> dict:
        return {
            "id": str(user.id),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": f"{user.first_name} {user.last_name}".strip(),
            "personal_email": user.personal_email,
            "password_hash": user.password_hash,
            "sending_email": user.sending_email,
            "status": user.status,
            "is_admin": user.is_admin,
        }

    # ── Auth: sessions ───────────────────────────────────────────────────

    async def create_session(
        self,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        async with self._session() as session:
            session.add(
                UserSession(
                    id=uuid.uuid4(),
                    user_id=self._as_uuid(user_id),
                    token_hash=token_hash,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    expires_at=expires_at,
                )
            )
            await session.commit()

    async def get_session_user(self, token_hash: str) -> dict | None:
        """Look up the user for a valid, unexpired session and touch it.

        Bumps ``last_seen_at`` (and extends ``expires_at`` if it's less than
        half the configured TTL away) on every call — the sliding-expiry
        behaviour MIGRATION_PLAN.md §3.1 specifies.

        Returns:
            dict | None: The auth user dict, or ``None`` if the token is
                unknown, expired, or its user no longer exists.
        """
        now = datetime.now(timezone.utc)
        async with self._session() as session:
            row = (
                await session.execute(
                    select(UserSession)
                    .options(selectinload(UserSession.user))
                    .where(UserSession.token_hash == token_hash)
                )
            ).scalar_one_or_none()
            if row is None or row.expires_at < now:
                return None
            row.last_seen_at = now
            ttl = row.expires_at - row.created_at
            if row.expires_at - now < ttl / 2:
                row.expires_at = now + ttl
            await session.commit()
            return self._auth_user_to_dict(row.user)

    async def delete_session(self, token_hash: str) -> None:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(UserSession).where(UserSession.token_hash == token_hash)
                )
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()

    # ── Auth: per-user stats (personal dashboard) ───────────────────────

    async def update_pending_user(
        self,
        user_id: str,
        first_name: str,
        last_name: str,
        personal_email: str,
        password_hash: str,
    ) -> dict:
        """Overwrite a ``status='pending'`` user's step-1 fields (the "Edit" link).

        Raises:
            DuplicatePersonalEmailError: If ``personal_email`` was changed to
                one already registered by a different account.
        """
        async with self._session() as session:
            user = await session.get(User, self._as_uuid(user_id))
            if user is None or user.status != "pending":
                raise ValueError(f"No pending user with id: {user_id}")
            user.first_name = first_name
            user.last_name = last_name
            user.personal_email = personal_email
            user.password_hash = password_hash
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if self._is_unique_violation(exc, "uq_users_personal_email"):
                    raise DuplicatePersonalEmailError(personal_email) from exc
                raise
            return self._auth_user_to_dict(user)

    async def sending_email_exists(self, sending_email: str) -> bool:
        async with self._session() as session:
            result = await session.execute(
                select(User.id).where(User.sending_email == sending_email)
            )
            return result.scalar_one_or_none() is not None

    async def get_user_stats(self, user_id: str) -> dict:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(
                        func.count(Conversation.id),
                        func.sum(case((Conversation.status == "open", 1), else_=0)),
                        func.sum(case((Conversation.status == "replied", 1), else_=0)),
                        func.sum(case((Conversation.status == "declined", 1), else_=0)),
                    ).where(Conversation.user_id == self._as_uuid(user_id))
                )
            ).one()
        return {
            "total": row[0] or 0,
            "open": int(row[1] or 0),
            "replied": int(row[2] or 0),
            "declined": int(row[3] or 0),
        }

    # ── Conversations: write ────────────────────────────────────────────

    async def insert_conversation(self, conversation: dict) -> None:
        """Persist a new conversation.

        Raises:
            DuplicateConversationTokenError: If ``conversation["conv_id"]``
                (the token) collides with an existing conversation's token.
        """
        async with self._session() as session:
            row = Conversation(
                id=uuid.uuid4(),
                user_id=self._as_uuid(conversation["user_id"]),
                product_id=self._as_uuid(conversation.get("project_id")),
                project_name=conversation.get("project_name") or None,
                product_name=conversation.get("product_name"),
                quantity=self._as_str(conversation.get("quantity")),
                target_price=conversation.get("target_price"),
                supplier_name=conversation["supplier_name"],
                supplier_email=conversation["supplier_email"],
                subject=conversation.get("subject") or "",
                token=conversation["conv_id"],
                reply_to_address=conversation["email_address"],
                provider=conversation["provider"],
                status=conversation.get("status", "open"),
                reply_count=conversation.get("reply_count", 0),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if self._is_unique_violation(exc, "uq_conversations_token"):
                    raise DuplicateConversationTokenError(
                        conversation["conv_id"]
                    ) from exc
                raise
        self.log.debug(
            "Inserted conversation %s for user %s",
            conversation["conv_id"],
            conversation["user_id"],
        )

    async def add_sent_email(self, conv_id: str, email_data: dict) -> None:
        async with self._session() as session:
            conv = await self._get_conversation_row(session, conv_id)
            if conv is None:
                self.log.warning("add_sent_email: unknown conv_id %s", conv_id)
                return
            row = Email(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                direction="sent",
                from_email=email_data.get("from_email", ""),
                to_email=email_data.get("to_email", ""),
                subject=email_data.get("subject", ""),
                body_html=email_data.get("body_html"),
                body_text=email_data.get("body_text"),
                message_id=self._generate_message_id(),
                reply_type=email_data.get("email_type"),
                provider=email_data.get("provider") or conv.provider,
            )
            session.add(row)
            await session.flush()
            self._add_attachments(session, row.id, email_data.get("attachments"))
            await session.commit()
        self.log.debug("Recorded sent email on %s", conv_id)

    async def add_received_email(self, conv_id: str, email_data: dict) -> None:
        async with self._session() as session:
            conv = await self._get_conversation_row(session, conv_id)
            if conv is None:
                self.log.warning("add_received_email: unknown conv_id %s", conv_id)
                return
            row = Email(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                direction="received",
                from_email=email_data.get("from_email", ""),
                to_email=email_data.get("to_email", ""),
                subject=email_data.get("subject", ""),
                body_html=email_data.get("body_html"),
                body_text=email_data.get("body_text"),
                message_id=self._generate_message_id(),
                reply_type=email_data.get("email_type"),
                dkim=email_data.get("dkim"),
                spf=email_data.get("spf"),
                spam_score=self._as_float(email_data.get("spam_score")),
                provider=email_data.get("provider") or conv.provider,
            )
            session.add(row)
            await session.flush()
            self._add_attachments(session, row.id, email_data.get("attachments"))
            conv.reply_count = (conv.reply_count or 0) + 1
            conv.last_reply_at = datetime.now(timezone.utc)
            conv.status = "replied"
            await session.commit()
        self.log.debug("Recorded inbound reply on %s", conv_id)

    async def update_conversation(self, conv_id: str, updates: dict) -> None:
        async with self._session() as session:
            conv = await self._get_conversation_row(session, conv_id)
            if conv is None:
                self.log.debug("update_conversation: unknown conv_id %s", conv_id)
                return
            for key, value in updates.items():
                if not hasattr(conv, key):
                    continue
                if key == "quantity":
                    value = self._as_str(value)
                setattr(conv, key, value)
            await session.commit()
        self.log.debug("Updated conversation %s", conv_id)

    async def delete_conversation(
        self, conv_id: str, user_id: str | None = None
    ) -> bool:
        async with self._session() as session:
            conv = await self._get_conversation_row(session, conv_id)
            if conv is None:
                return False
            if user_id is not None and str(conv.user_id) != str(user_id):
                return False
            await session.delete(conv)
            await session.commit()
        self.log.info("Deleted conversation %s (user=%s)", conv_id, user_id)
        return True

    async def delete_user_conversations(self, user_id: str) -> list[str]:
        async with self._session() as session:
            result = await session.execute(
                select(Conversation).where(
                    Conversation.user_id == self._as_uuid(user_id)
                )
            )
            convs = list(result.scalars())
            tokens = [c.token for c in convs]
            for conv in convs:
                await session.delete(conv)
            await session.commit()
        self.log.info(
            "Deleted %d conversation(s) for user %s", len(tokens), user_id
        )
        return tokens

    async def insert_unmatched(self, email_data: dict) -> None:
        async with self._session() as session:
            row = UnmatchedEmail(
                id=uuid.uuid4(),
                raw_payload=email_data,
                to_email=email_data.get("to_email"),
                from_email=email_data.get("from_email"),
                reason=email_data.get("reason", "unmatched"),
                status="needs_review",
            )
            session.add(row)
            await session.commit()
        self.log.info(
            "Stored unmatched inbound email to %s", email_data.get("to_email")
        )

    # ── Conversations: read ─────────────────────────────────────────────

    async def get_conversation(self, conv_id: str) -> dict | None:
        async with self._session() as session:
            conv = await self._get_conversation_row(
                session, conv_id, with_emails=True
            )
            return self._conversation_to_dict(conv, include_emails=True) if conv else None

    async def get_user_conversations(self, user_id: str) -> list[dict]:
        async with self._session() as session:
            result = await session.execute(
                select(Conversation)
                .where(Conversation.user_id == self._as_uuid(user_id))
                .order_by(Conversation.created_at.desc())
            )
            return [
                self._conversation_to_dict(c, include_emails=False)
                for c in result.scalars()
            ]

    async def find_latest_conversation_by_supplier(
        self, user_id: str, supplier_email: str
    ) -> dict | None:
        """Find the most recent conversation between a user and a supplier.

        Used to bind a supplier's brand-new (headerless) email to whichever
        thread they already have going with this user, instead of opening a
        duplicate conversation every time that supplier composes fresh
        instead of hitting reply — see
        :meth:`~src.services.conversation_service.ConversationService._match_new_thread`.

        Args:
            user_id (str): The conversation owner.
            supplier_email (str): The supplier's address (case-insensitive).

        Returns:
            dict | None: The most recently created matching conversation, or
                ``None`` if this supplier has no conversation with the user yet.
        """
        async with self._session() as session:
            conv = (
                await session.execute(
                    select(Conversation)
                    .where(
                        Conversation.user_id == self._as_uuid(user_id),
                        func.lower(Conversation.supplier_email)
                        == supplier_email.lower(),
                    )
                    .order_by(Conversation.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return self._conversation_to_dict(conv, include_emails=False) if conv else None

    async def get_all_users(self) -> list[dict]:
        async with self._session() as session:
            stmt = (
                select(
                    User.id,
                    User.first_name,
                    User.last_name,
                    User.personal_email,
                    func.count(Conversation.id).label("conversation_count"),
                    func.sum(
                        case((Conversation.status == "replied", 1), else_=0)
                    ).label("replied_count"),
                    func.sum(
                        case((Conversation.status == "open", 1), else_=0)
                    ).label("open_count"),
                    func.max(
                        func.coalesce(
                            Conversation.last_reply_at, Conversation.created_at
                        )
                    ).label("last_activity"),
                )
                .join(Conversation, Conversation.user_id == User.id)
                .group_by(User.id, User.first_name, User.last_name, User.personal_email)
            )
            rows = (await session.execute(stmt)).all()
        result = [
            {
                "user_id": str(row.id),
                "user_name": f"{row.first_name} {row.last_name}".strip(),
                "user_email": row.personal_email,
                "conversation_count": row.conversation_count,
                "replied_count": int(row.replied_count or 0),
                "open_count": int(row.open_count or 0),
                "last_activity": row.last_activity.isoformat()
                if row.last_activity
                else "",
            }
            for row in rows
        ]
        result.sort(key=lambda u: u["last_activity"], reverse=True)
        return result

    async def get_stats(self) -> dict:
        async with self._session() as session:
            row = (
                await session.execute(
                    select(
                        func.count(func.distinct(Conversation.user_id)),
                        func.count(Conversation.id),
                        func.sum(
                            case((Conversation.status == "replied", 1), else_=0)
                        ),
                        func.sum(
                            case((Conversation.status == "open", 1), else_=0)
                        ),
                    )
                )
            ).one()
        return {
            "total_users": row[0] or 0,
            "total_conversations": row[1] or 0,
            "total_replied": int(row[2] or 0),
            "total_open": int(row[3] or 0),
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _get_conversation_row(
        self, session: AsyncSession, conv_id: str, with_emails: bool = False
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.token == conv_id)
        if with_emails:
            stmt = stmt.options(
                selectinload(Conversation.user),
                selectinload(Conversation.emails).selectinload(Email.attachments),
            )
        return (await session.execute(stmt)).scalar_one_or_none()

    def _conversation_to_dict(
        self, conv: Conversation, include_emails: bool
    ) -> dict:
        user_name = ""
        if include_emails and conv.user is not None:
            user_name = f"{conv.user.first_name} {conv.user.last_name}".strip()
        result = {
            "conv_id": conv.token,
            "thread_id": conv.token,
            "project_id": str(conv.product_id) if conv.product_id else "",
            "project_name": conv.project_name or "",
            "user_id": str(conv.user_id),
            "user_name": user_name,
            "supplier_email": conv.supplier_email,
            "supplier_name": conv.supplier_name,
            "email_address": conv.reply_to_address,
            "provider": conv.provider,
            "status": conv.status,
            "created_at": conv.created_at.isoformat(),
            "reply_count": conv.reply_count,
            "last_reply_at": conv.last_reply_at.isoformat()
            if conv.last_reply_at
            else None,
            "product_name": conv.product_name,
            "quantity": conv.quantity,
            "target_price": conv.target_price,
            "subject": conv.subject,
            "emails_sent": [],
            "emails_received": [],
        }
        if include_emails:
            for email in sorted(conv.emails, key=lambda e: e.created_at):
                key = "emails_sent" if email.direction == "sent" else "emails_received"
                result[key].append(self._email_to_dict(email))
        return result

    @staticmethod
    def _email_to_dict(email: Email) -> dict:
        ts_field = "sent_at" if email.direction == "sent" else "received_at"
        result = {
            "email_type": email.reply_type,
            "from_email": email.from_email,
            "to_email": email.to_email,
            "subject": email.subject,
            "body_html": email.body_html,
            "body_text": email.body_text,
            "attachments": [
                {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size": a.size_bytes,
                    "url": a.url,
                }
                for a in email.attachments
            ],
            ts_field: email.created_at.isoformat(),
        }
        if email.direction == "received":
            result["dkim"] = email.dkim
            result["spf"] = email.spf
            result["spam_score"] = (
                str(email.spam_score) if email.spam_score is not None else None
            )
        return result

    @staticmethod
    def _add_attachments(
        session: AsyncSession, email_id: uuid.UUID, attachments: list[dict] | None
    ) -> None:
        for att in attachments or []:
            session.add(
                Attachment(
                    id=uuid.uuid4(),
                    email_id=email_id,
                    filename=att.get("filename", "attachment"),
                    url=att.get("url", ""),
                    content_type=att.get("content_type"),
                    size_bytes=att.get("size"),
                )
            )

    def _generate_message_id(self) -> str:
        domain = self.settings.default_outbound_domain or "local"
        return f"<{uuid.uuid4().hex}@{domain}>"

    @staticmethod
    def _as_uuid(value: str | None) -> uuid.UUID | None:
        if not value:
            return None
        return uuid.UUID(str(value))

    @staticmethod
    def _as_str(value) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _as_float(value) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)
        return sqlstate == "23505" and constraint_name in str(orig)
