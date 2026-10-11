"""add workspace and multi tenancy

Revision ID: d4e5f6a7b8c9
Revises: c3f8a2b56d41
Create Date: 2026-10-11 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3f8a2b56d41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create workspace table
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_workspace_slug"),
    )

    # 2. Create workspace_user membership table
    op.create_table(
        "workspace_user",
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )

    # 3. Seed default workspace for existing data backward compatibility and sync sequence
    op.execute(
        """
        INSERT INTO workspace (id, name, slug, description, created_at, updated_at)
        VALUES (
            1, 'Default Workspace', 'default-workspace',
            'System default workspace for backward compatibility', NOW(), NOW()
        )
        ON CONFLICT (id) DO NOTHING;
        """
    )
    op.execute(
        """
        SELECT setval(pg_get_serial_sequence('workspace', 'id'),
        COALESCE((SELECT MAX(id) FROM workspace), 1));
        """
    )

    # 4. Add workspace_id to project, backfill, and scope slug uniqueness per workspace
    op.add_column("project", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.execute("UPDATE project SET workspace_id = 1 WHERE workspace_id IS NULL")
    op.alter_column("project", "workspace_id", nullable=False, server_default="1")
    op.create_foreign_key(
        "fk_project_workspace_id",
        "project",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_project_workspace_id", "project", ["workspace_id"])
    op.drop_constraint("uq_project_slug", "project", type_="unique")
    op.create_unique_constraint("uq_project_workspace_slug", "project", ["workspace_id", "slug"])

    # 5. Add workspace_id to task, backfill from parent project, and create composite index
    op.add_column("task", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE task
        SET workspace_id = project.workspace_id
        FROM project
        WHERE task.project_id = project.id AND task.workspace_id IS NULL
        """
    )
    op.execute("UPDATE task SET workspace_id = 1 WHERE workspace_id IS NULL")
    op.alter_column("task", "workspace_id", nullable=False, server_default="1")
    op.create_foreign_key(
        "fk_task_workspace_id",
        "task",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_task_workspace_id", "task", ["workspace_id"])
    op.create_index(
        "ix_task_workspace_status_priority_id",
        "task",
        ["workspace_id", "status", "priority", sa.text("id DESC")],
    )

    # 6. Backfill existing users into default workspace
    op.execute(
        """
        INSERT INTO workspace_user (workspace_id, user_id, joined_at)
        SELECT 1, id, NOW() FROM "user"
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_task_workspace_status_priority_id", table_name="task")
    op.drop_index("ix_task_workspace_id", table_name="task")
    op.drop_constraint("fk_task_workspace_id", "task", type_="foreignkey")
    op.drop_column("task", "workspace_id")

    op.drop_constraint("uq_project_workspace_slug", "project", type_="unique")
    op.create_unique_constraint("uq_project_slug", "project", ["slug"])
    op.drop_index("ix_project_workspace_id", table_name="project")
    op.drop_constraint("fk_project_workspace_id", "project", type_="foreignkey")
    op.drop_column("project", "workspace_id")

    op.drop_table("workspace_user")
    op.drop_table("workspace")
