"""Add review status to TaskStatus enum

Revision ID: ab1234567890
Revises: f7715786b494
Create Date: 2026-10-04 17:42:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab1234567890"
down_revision: str | None = "f7715786b494"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in Postgres,
    # so run it in an autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'review'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum. Doing so would mean creating a new
    # type, altering every column that uses it, and dropping the old type.
    # Intentionally a no-op: the extra 'review' value is harmless if left in place.
    pass
