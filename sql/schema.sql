-- EmailPOC schema — PostgreSQL 16
-- Mirrors MIGRATION_PLAN.md §2.2. Applied by Alembic (alembic/versions/); kept
-- here as a plain, reviewable reference and for manual `psql -f` bootstrapping.
--
-- Duplicate prevention is enforced at the DB level everywhere the app must
-- never have two rows meaning the same thing:
--   * users.personal_email / users.sending_email       -> UNIQUE
--   * user_sessions.token_hash                          -> UNIQUE
--   * conversations.token                                -> UNIQUE
--   * emails.message_id                                  -> UNIQUE
-- The application still pre-checks and retries on collision (see
-- src/db/repository.py) so a race just re-picks a value instead of crashing;
-- these constraints are the backstop that makes that guarantee airtight.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── users ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name      VARCHAR NOT NULL,
    last_name       VARCHAR NOT NULL,
    personal_email  VARCHAR NOT NULL,
    password_hash   VARCHAR NOT NULL,
    sending_email   VARCHAR,
    status          VARCHAR NOT NULL DEFAULT 'pending',
    is_admin        BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_personal_email UNIQUE (personal_email),
    CONSTRAINT uq_users_sending_email UNIQUE (sending_email),
    CONSTRAINT ck_users_status CHECK (status IN ('pending', 'active'))
);

-- ── user_sessions ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash      VARCHAR NOT NULL,
    user_agent      VARCHAR,
    ip_address      VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_user_sessions_token_hash UNIQUE (token_hash)
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id);

-- ── products ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── conversations ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    product_id          UUID REFERENCES products (id),
    -- project_name is the catalog product's name at selection time; the
    -- spec's product_name is a separate, later snapshot (send_rfq lets the
    -- user retype/edit the product name that actually goes in the RFQ body).
    -- Kept as two columns, deviating from MIGRATION_PLAN.md §2.2, so today's
    -- UI (which displays both) keeps working unmodified.
    project_name        VARCHAR,
    product_name        VARCHAR,
    quantity            VARCHAR,
    target_price        VARCHAR,
    supplier_name       VARCHAR NOT NULL,
    supplier_email      VARCHAR NOT NULL,
    -- Nullable with a default rather than the spec's strict NOT NULL: today's
    -- send flow creates the conversation row before the RFQ subject exists
    -- (product/quantity/price are collected in the same form submit but
    -- persisted a moment later via update_conversation). Revisit once phase 6
    -- (outbound rework) folds subject-building into conversation creation.
    subject             VARCHAR NOT NULL DEFAULT '',
    token               VARCHAR(8) NOT NULL,
    reply_to_address    VARCHAR NOT NULL,
    provider            VARCHAR NOT NULL,
    status              VARCHAR NOT NULL DEFAULT 'open',
    reply_count         INT NOT NULL DEFAULT 0,
    last_reply_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_conversations_token UNIQUE (token),
    CONSTRAINT ck_conversations_status CHECK (status IN ('open', 'replied', 'declined'))
);

CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

-- ── emails ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS emails (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    direction           VARCHAR NOT NULL,
    from_email          VARCHAR NOT NULL,
    to_email            VARCHAR NOT NULL,
    subject             VARCHAR NOT NULL,
    body_html           TEXT,
    body_text           TEXT,
    message_id          VARCHAR NOT NULL,
    in_reply_to         VARCHAR,
    references_header   TEXT,
    reply_type          VARCHAR,
    matched_via         VARCHAR,
    dkim                VARCHAR,
    spf                 VARCHAR,
    spam_score          NUMERIC,
    provider            VARCHAR NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_emails_message_id UNIQUE (message_id),
    CONSTRAINT ck_emails_direction CHECK (direction IN ('sent', 'received'))
);

CREATE INDEX IF NOT EXISTS ix_emails_conversation_id ON emails (conversation_id);

-- ── attachments ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id        UUID NOT NULL REFERENCES emails (id) ON DELETE CASCADE,
    filename        VARCHAR NOT NULL,
    url             VARCHAR NOT NULL,
    content_type    VARCHAR,
    size_bytes      INT
);

CREATE INDEX IF NOT EXISTS ix_attachments_email_id ON attachments (email_id);

-- ── unmatched_emails ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS unmatched_emails (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_payload                 JSONB NOT NULL,
    to_email                    VARCHAR,
    from_email                  VARCHAR,
    reason                      VARCHAR NOT NULL,
    candidate_conversation_ids  UUID[],
    status                      VARCHAR NOT NULL DEFAULT 'needs_review',
    resolved_conversation_id    UUID REFERENCES conversations (id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_unmatched_emails_status CHECK (status IN ('needs_review', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS ix_unmatched_emails_status ON unmatched_emails (status);
