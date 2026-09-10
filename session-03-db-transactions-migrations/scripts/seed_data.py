"""Database seeding script for local development and query performance benchmarking.

Generates realistic seed data for users, projects, project memberships, and tasks.
Supports clean table reset and batch insertion for high performance.
"""

import argparse
import asyncio
import random
import sys
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models import Project, ProjectUser, Task, User
from app.models.enums import ProjectRole, TaskPriority, TaskStatus

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
    "user authentication endpoint",
    "database connection pooling",
    "composite index on task table",
    "transaction rollback handler",
    "Alembic migration script",
    "MongoDB raw payload logger",
    "ORM N+1 query optimization",
    "deadlock prevention logic",
    "API response caching",
    "rate limiting middleware",
    "Docker compose setup",
    "Makefile test commands",
    "seed script performance",
    "JSON validation schema",
    "health check endpoint",
]


def generate_users(count: int) -> list[dict[str, Any]]:
    users = []
    for i in range(1, count + 1):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        users.append(
            {
                "name": f"{fn} {ln}",
                "email": f"{fn.lower()}.{ln.lower()}{i}@example.com",
                "is_active": True,
            }
        )
    return users


def generate_projects(count: int) -> list[dict[str, Any]]:
    projects = []
    for i in range(1, count + 1):
        base_name = PROJECT_NAMES[(i - 1) % len(PROJECT_NAMES)]
        name = f"{base_name} {i}" if i > len(PROJECT_NAMES) else base_name
        projects.append(
            {
                "name": name,
                "description": f"Engineering initiative focused on {name.lower()}.",
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


def generate_tasks(count: int, project_ids: list[int], user_ids: list[int]) -> list[dict[str, Any]]:
    tasks = []
    statuses = [TaskStatus.todo.value, TaskStatus.in_progress.value, TaskStatus.done.value]
    priorities = [TaskPriority.low.value, TaskPriority.medium.value, TaskPriority.high.value]
    today = date.today()

    for i in range(1, count + 1):
        verb = random.choice(TASK_VERBS)
        noun = random.choice(TASK_NOUNS)
        assignee = random.choice(user_ids) if random.random() > 0.15 else None
        due_offset = random.randint(-15, 30)

        tasks.append(
            {
                "title": f"{verb} {noun} #{i}",
                "description": (
                    f"Detailed requirement for item #{i}: ensure test coverage and documentation."
                ),
                "status": random.choice(statuses),
                "priority": random.choice(priorities),
                "due_date": today + timedelta(days=due_offset),
                "project_id": random.choice(project_ids),
                "assignee_id": assignee,
            }
        )
    return tasks


async def clean_database(session: AsyncSession) -> None:
    print("Clearing existing data...")
    await session.execute(
        text('TRUNCATE TABLE task, project_user, project, "user" RESTART IDENTITY CASCADE;')
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
) -> None:
    target_url = db_url or str(settings.database_url)
    engine = create_async_engine(target_url, echo=False)

    start_time = time.time()
    if clean_only:
        print("Starting clean reset process (Wiping all data)...")
    else:
        print(
            f"Starting seed process (Target: {num_users} users, "
            f"{num_projects} projects, {num_tasks} tasks)..."
        )

    async with AsyncSession(engine) as session:
        if reset or clean_only:
            await clean_database(session)

        if not clean_only:
            # 1. Seed Users
            print(f"Seeding {num_users} users...")
            user_dicts = generate_users(num_users)
            user_stmt = insert(User).values(user_dicts).returning(User.id)
            res = await session.execute(user_stmt)
            user_ids = list(res.scalars().all())
            await session.commit()

            # 2. Seed Projects
            print(f"Seeding {num_projects} projects...")
            proj_dicts = generate_projects(num_projects)
            proj_stmt = insert(Project).values(proj_dicts).returning(Project.id)
            res = await session.execute(proj_stmt)
            project_ids = list(res.scalars().all())
            await session.commit()

            # 3. Seed Project Memberships
            print("Seeding project memberships...")
            memberships = generate_project_users(user_ids, project_ids)
            await session.execute(insert(ProjectUser).values(memberships))
            await session.commit()

            # 4. Seed Tasks in batches
            print(f"Seeding {num_tasks} tasks (batch size: {batch_size})...")
            tasks_generated = generate_tasks(num_tasks, project_ids, user_ids)
            for i in range(0, len(tasks_generated), batch_size):
                batch = tasks_generated[i : i + batch_size]
                await session.execute(insert(Task).values(batch))
                print(f"  Inserted tasks {i + 1} to {i + len(batch)}...")
            await session.commit()

        # 5. Gather Final Counts
        user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
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
    print(f"{'user':<20} | {user_count:<15}")
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
