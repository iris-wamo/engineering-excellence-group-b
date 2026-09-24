"""add_mongo_import_id_to_task

Revision ID: 5c60a4a4906c
Revises: aae8fcd27de6
Create Date: 2026-09-24 01:39:53.986755

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c60a4a4906c"
down_revision: str | None = "aae8fcd27de6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task", sa.Column("mongo_import_id", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("task", "mongo_import_id")
