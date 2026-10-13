"""Database seeding script for local development and query performance benchmarking.

Generates realistic seed data for workspaces, users, workspace memberships, projects,
project memberships, and tasks.
Supports clean table reset and batch insertion for high performance.
"""

import argparse
import asyncio
import random
import re
import sys
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.security import hash_password
from app.core.config import settings
from app.models import Project, ProjectUser, Task, User, Workspace, WorkspaceUser
from app.models.enums import ProjectRole, TaskPriority, TaskStatus

DEFAULT_PASSWORD_HASH = hash_password("password123")

# Sample data generators
FIRST_NAMES = [
    "Alex",
    "Jordan",
    "Taylor",
    "Morgan",
    "Casey",
    "Riley",
    "Avery",
    "Quinn",
    "Dakota",
    "Skyler",
    "Reese",
    "Rowan",
    "Finley",
    "Emerson",
    "Harper",
    "Peyton",
    "Eden",
    "Elliot",
    "Logan",
    "Jesse",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
]

PROJECT_NAMES = [
    "TaskFlow Backend MVP",
    "Database Migration Suite",
    "Authentication & Security Service",
    "Real-time Notification Engine",
    "API Gateway Redesign",
    "Analytics & Reporting Pipeline",
    "Search & Indexing Service",
    "User Onboarding Flow",
    "Billing & Subscription Engine",
    "Mobile App API Sync",
    "Infrastructure Automation",
    "Developer Portal",
    "Audit Logging System",
    "File Storage Microservice",
    "Integration Webhooks",
]

TASK_VERBS = [
    "Implement",
    "Fix",
    "Optimize",
    "Refactor",
    "Add tests for",
    "Document",
    "Design schema for",
    "Benchmark",
    "Review PR for",
    "Migrate",
]

TASK_NOUNS = [
    "user authentication",
    "database indexing",
    "REST endpoints",
    "transaction rollback",
    "Docker compose setup",
    "pagination logic",
    "error handling",
    "query performance",
    "seed script",
    "foreign key constraints",
    "slug generation",
    "migration script",
    "input validation",
    "response caching",
    "health check endpoint",
]

WORKSPACE_NAMES = [
    ("Acme Corp", "acme-corp", "Primary enterprise workspace for Acme Corp engineering teams."),
    (
        "Globex Corporation",
        "globex-corp",
        "International multi-tenant workspace for Globex Corporation.",
    ),
    ("Initech Systems", "initech-systems", "Technology operations workspace for Initech Systems."),
    ("Umbrella Research", "umbrella-research", "Advanced R&D team workspace for Umbrella Labs."),
]


def generate_workspaces(count: int) -> list[dict[str, Any]]:
    workspaces = []
    for i in range(1, count + 1):
        if i <= len(WORKSPACE_NAMES):
            name, slug, desc = WORKSPACE_NAMES[i - 1]
        else:
            name = f"Workspace Organization {i}"
            slug = f"workspace-org-{i}"
            desc = f"Organization tenant workspace #{i}."
        workspaces.append({"name": name, "slug": slug, "description": desc})
    return workspaces


def generate_users(count: int) -> list[dict[str, Any]]:
    users = []
    for i in range(1, count + 1):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        users.append(
            {
                "name": f"{fn} {ln}",
                "email": f"{fn.lower()}.{ln.lower()}{i}@example.com",
                "password_hash": DEFAULT_PASSWORD_HASH,
                "is_active": True,
            }
        )
    return users


def generate_workspace_users(user_ids: list[int], workspace_ids: list[int]) -> list[dict[str, Any]]:
    memberships = []
    seen = set()
    for user_id in user_ids:
        # Each user belongs to at least 1 workspace
        primary_ws = random.choice(workspace_ids)
        memberships.append({"workspace_id": primary_ws, "user_id": user_id})
        seen.add((primary_ws, user_id))

        # Some users (e.g. 30%) belong to a second workspace for cross-tenant testing
        if len(workspace_ids) > 1 and random.random() < 0.30:
            other_ws = random.choice([ws for ws in workspace_ids if ws != primary_ws])
            if (other_ws, user_id) not in seen:
                memberships.append({"workspace_id": other_ws, "user_id": user_id})
                seen.add((other_ws, user_id))
    return memberships


def generate_projects(count: int, workspace_ids: list[int]) -> list[dict[str, Any]]:
    projects = []
    for i in range(1, count + 1):
        base_name = PROJECT_NAMES[(i - 1) % len(PROJECT_NAMES)]
        name = f"{base_name} {i}" if i > len(PROJECT_NAMES) else base_name
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        projects.append(
            {
                "name": name,
                "slug": slug,
                "description": f"Engineering initiative focused on {name.lower()}.",
                "workspace_id": random.choice(workspace_ids),
            }
        )
    return projects


def generate_project_users(user_ids: list[int], project_ids: list[int]) -> list[dict[str, Any]]:
    memberships = []
    for project_id in project_ids:
        # Every project must have exactly 1 owner
        owner_id = random.choice(user_ids)
        memberships.append(
            {
                "project_id": project_id,
                "user_id": owner_id,
                "role": ProjectRole.owner.value,
            }
        )

        # Add additional random members to the project
        num_members = min(len(user_ids) - 1, random.randint(2, max(3, len(user_ids) // 2)))
        other_users = [u for u in user_ids if u != owner_id]
        members = random.sample(other_users, num_members)
        for user_id in members:
            memberships.append(
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "role": ProjectRole.member.value,
                }
            )
    return memberships


def generate_tasks(
    count: int, project_workspace_map: dict[int, int], user_ids: list[int]
) -> list[dict[str, Any]]:
    tasks = []
    statuses = [TaskStatus.todo.value, TaskStatus.in_progress.value, TaskStatus.done.value]
    priorities = [TaskPriority.low.value, TaskPriority.medium.value, TaskPriority.high.value]
    project_ids = list(project_workspace_map.keys())
    today = date.today()

    for i in range(1, count + 1):
        verb = random.choice(TASK_VERBS)
        noun = random.choice(TASK_NOUNS)
        assignee = random.choice(user_ids) if random.random() > 0.15 else None
        due_offset = random.randint(-15, 30)
        proj_id = random.choice(project_ids)

        tasks.append(
            {
                "title": f"{verb} {noun} #{i}",
                "description": (
                    f"Detailed requirement for item #{i}: ensure test coverage and documentation."
                ),
                "status": random.choice(statuses),
                "priority": random.choice(priorities),
                "due_date": today + timedelta(days=due_offset),
                "project_id": proj_id,
                "workspace_id": project_workspace_map[proj_id],
                "assignee_id": assignee,
            }
        )
    return tasks


async def clean_database(session: AsyncSession) -> None:
    print("Clearing existing data...")
    await session.execute(
        text(
            'TRUNCATE TABLE task, project_user, project, workspace_user, workspace, "user" '
            "RESTART IDENTITY CASCADE;"
        )
    )
    await session.commit()
    print("Database truncated successfully.")


async def seed_data(
    num_users: int,
    num_projects: int,
    num_tasks: int,
    batch_size: int,
    reset: bool,
    clean_only: bool = False,
    db_url: str | None = None,
    num_workspaces: int = 2,
) -> None:
    target_url = db_url or str(settings.database_url)
    engine = create_async_engine(target_url, echo=False)

    start_time = time.time()
    if clean_only:
        print("Starting clean reset process (Wiping all data)...")
    else:
        print(
            f"Starting seed process (Target: {num_workspaces} workspaces, {num_users} users, "
            f"{num_projects} projects, {num_tasks} tasks)..."
        )

    async with AsyncSession(engine) as session:
        if reset or clean_only:
            await clean_database(session)

        if not clean_only:
            # 1. Seed Workspaces
            print(f"Seeding {num_workspaces} workspaces...")
            ws_dicts = generate_workspaces(num_workspaces)
            ws_stmt = insert(Workspace).values(ws_dicts).returning(Workspace.id)
            res = await session.execute(ws_stmt)
            workspace_ids = list(res.scalars().all())
            await session.commit()

            # 2. Seed Users
            print(f"Seeding {num_users} users...")
            user_dicts = generate_users(num_users)
            user_stmt = insert(User).values(user_dicts).returning(User.id)
            res = await session.execute(user_stmt)
            user_ids = list(res.scalars().all())
            await session.commit()

            # 3. Seed Workspace Memberships
            print("Seeding workspace memberships...")
            ws_memberships = generate_workspace_users(user_ids, workspace_ids)
            await session.execute(insert(WorkspaceUser).values(ws_memberships))
            await session.commit()

            # 4. Seed Projects
            print(f"Seeding {num_projects} projects...")
            proj_dicts = generate_projects(num_projects, workspace_ids)
            proj_stmt = (
                insert(Project).values(proj_dicts).returning(Project.id, Project.workspace_id)
            )
            res = await session.execute(proj_stmt)
            project_rows = res.all()
            project_workspace_map = {row[0]: row[1] for row in project_rows}
            project_ids = list(project_workspace_map.keys())
            await session.commit()

            # 5. Seed Project Memberships
            print("Seeding project memberships...")
            memberships = generate_project_users(user_ids, project_ids)
            await session.execute(insert(ProjectUser).values(memberships))
            await session.commit()

            # 6. Seed Tasks in batches
            print(f"Seeding {num_tasks} tasks (batch size: {batch_size})...")
            tasks_generated = generate_tasks(num_tasks, project_workspace_map, user_ids)
            for i in range(0, len(tasks_generated), batch_size):
                batch = tasks_generated[i : i + batch_size]
                await session.execute(insert(Task).values(batch))
                print(f"  Inserted tasks {i + 1} to {i + len(batch)}...")
            await session.commit()

        # Gather Final Counts
        ws_count = (await session.execute(select(func.count(Workspace.id)))).scalar_one()
        user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
        wu_count = (await session.execute(select(func.count(WorkspaceUser.user_id)))).scalar_one()
        proj_count = (await session.execute(select(func.count(Project.id)))).scalar_one()
        pu_count = (await session.execute(select(func.count(ProjectUser.user_id)))).scalar_one()
        task_count = (await session.execute(select(func.count(Task.id)))).scalar_one()

    await engine.dispose()
    elapsed = time.time() - start_time

    print("\n" + "=" * 50)
    print(" SEEDING COMPLETE")
    print("=" * 50)
    print(f"Time Taken       : {elapsed:.2f} seconds")
    print("-" * 50)
    print(f"{'Table Name':<20} | {'Row Count':<15}")
    print("-" * 50)
    print(f"{'workspace':<20} | {ws_count:<15}")
    print(f"{'user':<20} | {user_count:<15}")
    print(f"{'workspace_user':<20} | {wu_count:<15}")
    print(f"{'project':<20} | {proj_count:<15}")
    print(f"{'project_user':<20} | {pu_count:<15}")
    print(f"{'task':<20} | {task_count:<15}")
    print("=" * 50 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed database with demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clean / truncate all tables before seeding.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Clean / truncate all tables and exit without seeding new data.",
    )
    parser.add_argument(
        "--workspaces",
        type=int,
        default=2,
        help="Number of workspaces to generate (default: 2).",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=10,
        help="Number of users to generate (default: 10).",
    )
    parser.add_argument(
        "--projects",
        type=int,
        default=5,
        help="Number of projects to generate (default: 5).",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=200,
        help="Number of tasks to generate (default: 200).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for task insertion (default: 1000).",
    )
    parser.add_argument(
        "--seed-val",
        type=int,
        default=42,
        help="Random seed for reproducible dataset generation (default: 42).",
    )

    args = parser.parse_args()
    random.seed(args.seed_val)

    try:
        asyncio.run(
            seed_data(
                num_workspaces=args.workspaces,
                num_users=args.users,
                num_projects=args.projects,
                num_tasks=args.tasks,
                batch_size=args.batch_size,
                reset=args.reset,
                clean_only=args.clean_only,
            )
        )

    except Exception as e:
        print(f"Error seeding database: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
