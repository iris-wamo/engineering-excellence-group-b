"""drop superseded task status priority index

Revision ID: cbf85300077c
Revises: d4e5f6a7b8c9
Create Date: 2026-11-15 00:44:05.256304

ix_task_status_priority_id (from f7715786b494) was superseded by
ix_task_workspace_status_priority_id in d4e5f6a7b8c9, which created the new
index but never dropped the old one. Drop it so the database matches the model.

Locking: DROP INDEX takes a brief ACCESS EXCLUSIVE lock on task (catalog change only,
no table scan). The downgrade's CREATE INDEX scans the whole table and blocks writes to
task while it runs; fine at this app's data sizes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cbf85300077c"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # if_exists: databases built with create_all (or cleaned by hand) never had it.
    op.drop_index("ix_task_status_priority_id", table_name="task", if_exists=True)


def downgrade() -> None:
    op.create_index(
        "ix_task_status_priority_id",
        "task",
        ["status", "priority", sa.literal_column("id DESC")],
        unique=False,
    )
