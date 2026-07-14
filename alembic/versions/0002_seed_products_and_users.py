"""seed products and legacy predefined users

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09

Seeds the `products` table from the old hardcoded PREDEFINED_PROJECTS list
and the `users` table from the old hardcoded PREDEFINED_USERS list (both
source modules are deleted now that real tables replace them — see
MIGRATION_PLAN.md §2.4). Seeded users get a random, unusable password hash
and a derived `sending_email` (local-part of their personal email + the
configured default outbound domain) so the app keeps working before the registration
/ login flow (MIGRATION_PLAN.md §3) exists. The first user is marked
is_admin so the future admin overview has at least one account to use.
"""
import secrets
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from passlib.hash import bcrypt
from sqlalchemy.dialects import postgresql

from alembic import op
from src.config import get_settings

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREDEFINED_USERS = [
    {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567891",
        "full_name": "James Whitfield",
        "email": "james.whitfield@galaxyweblinks.com",
    },
    {
        "id": "b2c3d4e5-f6a7-8901-bcde-f12345678902",
        "full_name": "Oliver Bennett",
        "email": "oliver.bennett@galaxyweblinks.com",
    },
    {
        "id": "c3d4e5f6-a7b8-9012-cdef-123456789013",
        "full_name": "Emily Clarke",
        "email": "emily.clarke@galaxyweblinks.com",
    },
    {
        "id": "d4e5f6a7-b8c9-0123-def0-234567890124",
        "full_name": "Thomas Wright",
        "email": "thomas.wright@galaxyweblinks.com",
    },
    {
        "id": "e5f6a7b8-c9d0-1234-ef01-345678901235",
        "full_name": "Charlotte Hughes",
        "email": "charlotte.hughes@galaxyweblinks.com",
    },
]

PREDEFINED_PRODUCT_NAMES = [
    "Stainless Steel Bottle 1L",
    "Neodymium Magnet Set",
    "Bamboo Cutting Board",
    "Silicone Kitchen Spatula",
    "Leather Wallet Bifold",
    "Cotton Canvas Tote Bag",
    "Ceramic Coffee Mug 350ml",
    "Wooden Picture Frame 5x7",
    "Zinc Alloy Keychain Hook",
    "Microfiber Cleaning Cloth",
]


def upgrade() -> None:
    products = sa.table(
        "products",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        products,
        [{"id": uuid.uuid4(), "name": name} for name in PREDEFINED_PRODUCT_NAMES],
    )

    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("first_name", sa.String()),
        sa.column("last_name", sa.String()),
        sa.column("personal_email", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("sending_email", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_admin", sa.Boolean()),
    )

    outbound_domain = get_settings().default_outbound_domain
    rows = []
    for index, user in enumerate(PREDEFINED_USERS):
        first_name, _, last_name = user["full_name"].partition(" ")
        local_part = user["email"].split("@", 1)[0]
        sending_email = (
            f"{local_part}@{outbound_domain}" if outbound_domain else None
        )
        rows.append({
            "id": uuid.UUID(user["id"]),
            "first_name": first_name,
            "last_name": last_name or "",
            "personal_email": user["email"],
            "password_hash": bcrypt.hash(secrets.token_urlsafe(32)),
            "sending_email": sending_email,
            "status": "active",
            "is_admin": index == 0,
        })
    op.bulk_insert(users, rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM users WHERE personal_email IN ({})".format(
            ", ".join(f"'{u['email']}'" for u in PREDEFINED_USERS)
        )
    )
    op.execute(
        "DELETE FROM products WHERE name IN ({})".format(
            ", ".join(f"'{n}'" for n in PREDEFINED_PRODUCT_NAMES)
        )
    )
