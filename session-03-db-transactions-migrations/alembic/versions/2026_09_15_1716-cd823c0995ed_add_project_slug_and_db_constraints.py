"""add_project_slug_and_db_constraints

Revision ID: cd823c0995ed
Revises: 096305ddb2ff
Create Date: 2026-09-15 17:16:31.667290

Add project slug with backfill, check constraints, and indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cd823c0995ed"
down_revision: str | None = "096305ddb2ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Indexes
    op.create_index("ix_activity_log_actor_id", "activity_log", ["actor_id"], unique=False)
    op.create_index(
        "ix_activity_log_entity", "activity_log", ["entity_type", "entity_id"], unique=False
    )
    op.create_index("ix_notification_task_id", "notification", ["task_id"], unique=False)
    op.create_index(
        "ix_task_assignment_history_new_assignee_id",
        "task_assignment_history",
        ["new_assignee_id"],
        unique=False,
    )

    # Add project.slug with 3-phase backfill
    op.add_column("project", sa.Column("slug", sa.String(length=80), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE project
            SET slug = lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))
                       || '-' || id::text
            WHERE slug IS NULL
            """
        )
    )
    op.alter_column("project", "slug", nullable=False)
    op.create_index("ix_project_slug", "project", ["slug"], unique=False)
    op.create_unique_constraint("uq_project_slug", "project", ["slug"])

    # Check constraints
    op.create_check_constraint(
        "ck_notification_status",
        "notification",
        "status IN ('pending', 'sent', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_activity_log_entity_type",
        "activity_log",
        "entity_type IN ('task', 'project', 'user')",
    )


def downgrade() -> None:
    # Drop check constraints
    op.drop_constraint("ck_activity_log_entity_type", "activity_log", type_="check")
    op.drop_constraint("ck_notification_status", "notification", type_="check")

    # Drop project.slug
    op.drop_constraint("uq_project_slug", "project", type_="unique")
    op.drop_index("ix_project_slug", table_name="project")
    op.drop_column("project", "slug")

    # Drop indexes
    op.drop_index(
        "ix_task_assignment_history_new_assignee_id",
        table_name="task_assignment_history",
    )
    op.drop_index("ix_notification_task_id", table_name="notification")
    op.drop_index("ix_activity_log_entity", table_name="activity_log")
    op.drop_index("ix_activity_log_actor_id", table_name="activity_log")
