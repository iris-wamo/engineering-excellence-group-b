"""Add review status to TaskStatus enum

Revision ID: ab1234567890
Revises: 5c60a4a4906c
Create Date: 2026-10-04 17:42:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab1234567890'
down_revision: Union[str, None] = '5c60a4a4906c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use execute to alter the enum type directly in Postgres
    # Cannot be run inside a transaction block in Postgres, so we must disable autocommit for this command if needed,
    # but typically `op.execute` works if we specify isolation_level in some cases.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'review'")

def downgrade() -> None:
    # Postgres doesn't support removing values from ENUM easily.
    # It requires creating a new type, altering the column to use the new type, and dropping the old type.
    # For simplicity, we can pass.
    pass
