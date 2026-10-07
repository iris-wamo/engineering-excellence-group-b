"""add_admin_manager_project_roles

Revision ID: c3f8a2b56d41
# Revises: b1d4e9c7a210
# Create Date: 2026-10-07 10:15:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3f8a2b56d41"
down_revision: str | None = "b1d4e9c7a210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE project_role ADD VALUE IF NOT EXISTS 'admin'")
    op.execute("ALTER TYPE project_role ADD VALUE IF NOT EXISTS 'manager'")


def downgrade() -> None:
    op.execute("UPDATE project_user SET role = 'member' WHERE role IN ('admin', 'manager')")
