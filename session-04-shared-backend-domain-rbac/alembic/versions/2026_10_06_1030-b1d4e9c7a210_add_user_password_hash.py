"""add_user_password_hash

Revision ID: b1d4e9c7a210
# Revises: f7715786b494
# Create Date: 2026-10-06 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1d4e9c7a210"
down_revision: str | None = "f7715786b494"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable so existing rows stay valid, accounts without a hash cannot log in.
    op.add_column("user", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "password_hash")
