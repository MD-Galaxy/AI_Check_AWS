"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=False),
        sa.Column("personal_email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("sending_email", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("personal_email", name="uq_users_personal_email"),
        sa.UniqueConstraint("sending_email", name="uq_users_sending_email"),
        sa.CheckConstraint("status IN ('pending', 'active')", name="ck_users_status"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("project_name", sa.String(), nullable=True),
        sa.Column("product_name", sa.String(), nullable=True),
        sa.Column("quantity", sa.String(), nullable=True),
        sa.Column("target_price", sa.String(), nullable=True),
        sa.Column("supplier_name", sa.String(), nullable=False),
        sa.Column("supplier_email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False, server_default=""),
        sa.Column("token", sa.String(length=8), nullable=False),
        sa.Column("reply_to_address", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reply_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token", name="uq_conversations_token"),
        sa.CheckConstraint("status IN ('open', 'replied', 'declined')", name="ck_conversations_status"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("from_email", sa.String(), nullable=False),
        sa.Column("to_email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("in_reply_to", sa.String(), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
        sa.Column("reply_type", sa.String(), nullable=True),
        sa.Column("matched_via", sa.String(), nullable=True),
        sa.Column("dkim", sa.String(), nullable=True),
        sa.Column("spf", sa.String(), nullable=True),
        sa.Column("spam_score", sa.Numeric(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", name="uq_emails_message_id"),
        sa.CheckConstraint("direction IN ('sent', 'received')", name="ck_emails_direction"),
    )
    op.create_index("ix_emails_conversation_id", "emails", ["conversation_id"])

    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("emails.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
    )
    op.create_index("ix_attachments_email_id", "attachments", ["email_id"])

    op.create_table(
        "unmatched_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("to_email", sa.String(), nullable=True),
        sa.Column("from_email", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("candidate_conversation_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="needs_review"),
        sa.Column("resolved_conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('needs_review', 'resolved', 'ignored')", name="ck_unmatched_emails_status"),
    )
    op.create_index("ix_unmatched_emails_status", "unmatched_emails", ["status"])


def downgrade() -> None:
    op.drop_table("unmatched_emails")
    op.drop_table("attachments")
    op.drop_table("emails")
    op.drop_table("conversations")
    op.drop_table("products")
    op.drop_table("user_sessions")
    op.drop_table("users")
