"""SQLAlchemy 2.0 ORM models for the EmailPOC schema.

Mirrors ``sql/schema.sql`` / MIGRATION_PLAN.md §2.2 exactly — that file is
the reviewable reference, this module (via Alembic) is the source of truth
actually applied to the database. Keep the two in sync by hand; there is no
autogeneration step wired up for this project yet.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Without this, SQLAlchemy binds every `Mapped[datetime]` column as a
    # naive TIMESTAMP regardless of the actual TIMESTAMPTZ column type,
    # and asyncpg then rejects the timezone-aware datetimes the app passes.
    type_annotation_map = {datetime: DateTime(timezone=True)}


def _utcnow() -> datetime:
    """Timezone-aware "now", matching the TIMESTAMPTZ columns below.

    A naive ``datetime.utcnow()`` default mixed with the aware datetimes
    :mod:`src.auth.sessions` computes (``datetime.now(timezone.utc)``) makes
    asyncpg reject the INSERT outright — every default here must be aware.
    """
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    first_name: Mapped[str]
    last_name: Mapped[str]
    personal_email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    sending_email: Mapped[str | None] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="pending")
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active')", name="ck_users_status"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)
    user_agent: Mapped[str | None]
    ip_address: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=_utcnow)
    expires_at: Mapped[datetime]

    user: Mapped["User"] = relationship(back_populates="sessions")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id")
    )
    project_name: Mapped[str | None]
    product_name: Mapped[str | None]
    quantity: Mapped[str | None]
    target_price: Mapped[str | None]
    supplier_name: Mapped[str]
    supplier_email: Mapped[str]
    subject: Mapped[str] = mapped_column(default="")
    token: Mapped[str] = mapped_column(unique=True)
    reply_to_address: Mapped[str]
    provider: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    reply_count: Mapped[int] = mapped_column(default=0)
    last_reply_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="conversations")
    emails: Mapped[list["Email"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'replied', 'declined')",
            name="ck_conversations_status",
        ),
    )


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    direction: Mapped[str]
    from_email: Mapped[str]
    to_email: Mapped[str]
    subject: Mapped[str]
    body_html: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str] = mapped_column(unique=True)
    in_reply_to: Mapped[str | None]
    references_header: Mapped[str | None] = mapped_column(Text)
    reply_type: Mapped[str | None]
    matched_via: Mapped[str | None]
    dkim: Mapped[str | None]
    spf: Mapped[str | None]
    spam_score: Mapped[float | None] = mapped_column(Numeric)
    provider: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="emails")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "direction IN ('sent', 'received')", name="ck_emails_direction"
        ),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str]
    url: Mapped[str]
    content_type: Mapped[str | None]
    size_bytes: Mapped[int | None]

    email: Mapped["Email"] = relationship(back_populates="attachments")


class UnmatchedEmail(Base):
    __tablename__ = "unmatched_emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB)
    to_email: Mapped[str | None]
    from_email: Mapped[str | None]
    reason: Mapped[str]
    candidate_conversation_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )
    status: Mapped[str] = mapped_column(default="needs_review")
    resolved_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id")
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('needs_review', 'resolved', 'ignored')",
            name="ck_unmatched_emails_status",
        ),
    )
