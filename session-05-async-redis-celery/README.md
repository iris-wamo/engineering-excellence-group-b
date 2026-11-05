# TaskFlow — Session 05

Internal team work management backend. This session builds on Session 04 and moves TaskFlow
from a basic API into an asynchronous backend workflow. It focuses on async programming in FastAPI
(non-blocking endpoints, concurrent external calls, timeouts), Redis caching and cache invalidation
strategies, Redis Pub/Sub vs. Redis Streams for event channeling, Celery background jobs with retries
and worker failure handling, Celery Beat periodic scheduling, and Flower monitoring for worker
observability. Design notes for each topic are in [`docs/session-05/`](docs/session-05/) and
reproducible walkthroughs in [`demos/session-05/`](demos/session-05/).

The database design this is built from is documented in
[`docs/session-03/db/schema-design.md`](docs/session-03/db/schema-design.md), with the diagram in
[`docs/session-03/db/ERD.png`](docs/session-03/db/ERD.png).
---

## Table of contents

- [What you need](#what-you-need)
- [Quick start with Docker](#quick-start-with-docker)
- [Full-stack walkthrough](#full-stack-walkthrough)
- [Step 1 — Install uv](#step-1--install-uv)
- [Step 2 — Install PostgreSQL](#step-2--install-postgresql)
  - [macOS](#macos)
  - [Linux](#linux)
  - [Windows](#windows)
- [Step 3 — Create the database and user](#step-3--create-the-database-and-user)
- [Step 4 — Configure and run](#step-4--configure-and-run)
- [Makefile Targets](#makefile-targets)
- [Running tests](#running-tests)
- [Pre-commit hooks](#pre-commit-hooks)
- [Project layout](#project-layout)
- [Working with migrations](#working-with-migrations)
- [Seeding & Performance Test Data](#seeding--performance-test-data)
- [Inspecting the database](#inspecting-the-database)
- [Using pgAdmin](#using-pgadmin)

---

## What you need

| Tool | Why | Notes |
|------|-----|-------|
| **uv** | Runs Python and installs dependencies | Also installs the right Python for you — you do **not** need to install Python separately |
| **Docker** (with Compose) | Runs the whole stack: PostgreSQL, MongoDB, Redis, API, Celery worker, Celery Beat, Flower | Recommended; see [Quick start with Docker](#quick-start-with-docker) |
| **PostgreSQL** | The main database | Only if you run it natively instead of in Docker (Steps 2–3) |
| **MongoDB** | Raw task imports | Any modern version; or `docker compose up -d mongo` |
| **Redis** | Cache, task events, Celery broker and results, the reminder lock | Any modern version; or `docker compose up -d redis` |

The project targets **Python 3.12+**, but `uv` downloads and manages that automatically.
With Docker, uv and Docker are the only things you install by hand.

---

## Quick start with Docker

From the `session-05-async-redis-celery/` directory:

```bash
# 1. Install dependencies on the host (for tests, seeding and scripts) and create .env
make install

# 2. Pick your own Flower login in .env (the template has a placeholder). Compose refuses
#    to run any command while it is missing:  FLOWER_BASIC_AUTH=<user>:<password>

# 3. Build and start every service; the api container runs the migrations on start
make docker-build
make docker-up

# 4. Load demo data and create the test database used by `make test`
make seed
docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test"'
```

- API docs: <http://localhost:8000/docs>
- Flower: <http://127.0.0.1:5555> (or `FLOWER_PORT`), log in with `FLOWER_BASIC_AUTH`
- Logs: `make docker-logs` (API) or `make docker-logs s=celery-worker`

The `.env.example` defaults point host commands at the Docker ports: PostgreSQL on **5433**,
MongoDB on 27017 and Redis on 6379. To run without Docker, follow Steps 1–4 below.

---

## Full-stack walkthrough

`make docker-up` starts every service the Session 05 flow needs. A task change goes through
all of them: the API commits and responds, Redis invalidates the cache and carries the
events and the jobs, the worker delivers the notification, Beat schedules reminders, and
Flower shows the jobs. The full trace, the failure cases and the tradeoffs are in
[`docs/session-05/end-to-end-flow.md`](docs/session-05/end-to-end-flow.md).

| Service | Address | Role in the flow | Watch it with |
|---------|---------|------------------|---------------|
| `api` | <http://localhost:8000/docs> | Commits the change, invalidates the cache, queues the job, publishes the events | `make docker-logs` |
| `db` | `localhost:5433` | Tasks, history, and the `notification` outbox | `make docker-db-shell` |
| `mongo` | `localhost:27017` | Raw task imports (not part of this flow) | |
| `redis` | `localhost:6379` | db 0: cache and task events · db 1: Celery broker · db 2: results | `make redis-cli`, `make events-streams` |
| `celery-worker` | | Delivers notifications, runs the Beat sweeps | `make docker-logs s=celery-worker` |
| `celery-beat` | | Queues the reminder sweep (60s) and the outbox sweep (300s) | `make docker-logs s=celery-beat` |
| `flower` | <http://127.0.0.1:5555> | Workers, job history, retries and failures | Browser, log in with `FLOWER_BASIC_AUTH` |

```bash
make docker-up
docker compose ps    # all seven services running; api, db, mongo, redis healthy
make flow-demo       # one task change through every service, checked step by step (~1-2 min)
```

`make flow-demo` creates its own users, project and task through the API (no `make seed`
needed) and leaves them in place to inspect. It exits non-zero if any step fails. To walk
the same flow by hand for a recording, follow
[`demos/session-05/07-end-to-end-flow/demo.md`](demos/session-05/07-end-to-end-flow/demo.md).

---

## Step 1 — Install uv

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your terminal, then confirm it works:

```bash
uv --version
```

(Alternatives if you prefer: `brew install uv` on macOS, `pipx install uv`, or
`winget install astral-sh.uv` on Windows.)

---

## Step 2 — Install PostgreSQL

Pick your operating system.

### macOS

Using [Homebrew](https://brew.sh):

```bash
brew install postgresql
brew services start postgresql
```


### Linux

**Debian / Ubuntu:**

```bash
sudo apt update
sudo apt install postgresql
sudo systemctl enable --now postgresql
```



### Windows

1. Download the installer from
   [postgresql.org/download/windows](https://www.postgresql.org/download/windows/).
2. Run it. During setup:
   - Set and **remember the password** for the `postgres` superuser.
   - Keep the default port **5432**.
   - Leave "pgAdmin 4" and "Command Line Tools" ticked.
3. After installing, use the **"SQL Shell (psql)"** shortcut from the Start menu, or add
   Postgres to your `PATH` so `psql` works in any terminal.

On Windows you connect as the `postgres` user and enter the password you chose during
installation.

---


## Step 3 — Create the database and user

This creates a dedicated login role (`taskflow`), an empty database (`taskflow`) owned by
it, and a second `taskflow_test` database used by the test suite (see
[Running tests](#running-tests)). Do this **once**. The command differs slightly per OS
because of how you reach the Postgres admin account.

**macOS:**

```bash
psql -d postgres -c "CREATE ROLE taskflow WITH LOGIN PASSWORD 'taskflow';"
psql -d postgres -c "CREATE DATABASE taskflow OWNER taskflow;"
psql -d postgres -c "CREATE DATABASE taskflow_test OWNER taskflow;"
```

**Linux:**

```bash
sudo -u postgres psql -c "CREATE ROLE taskflow WITH LOGIN PASSWORD 'taskflow';"
sudo -u postgres psql -c "CREATE DATABASE taskflow OWNER taskflow;"
sudo -u postgres psql -c "CREATE DATABASE taskflow_test OWNER taskflow;"
```

**Windows** (in "SQL Shell (psql)", or any terminal with psql on the PATH — it will prompt
for the `postgres` password you set during install):

```bat
psql -U postgres -c "CREATE ROLE taskflow WITH LOGIN PASSWORD 'taskflow';"
psql -U postgres -c "CREATE DATABASE taskflow OWNER taskflow;"
psql -U postgres -c "CREATE DATABASE taskflow_test OWNER taskflow;"
```

Confirm the new role can actually log in over the network (all platforms):

```bash
psql "postgresql://taskflow:taskflow@localhost:5432/taskflow" -c "SELECT current_user, current_database();"
```


---

## Step 4 — Configure and run

From the `session-05-async-redis-celery/` directory:

```bash
# 1. Install Python + all dependencies into a local .venv
uv sync                       # or use make install

# 2. Create your local env file from the template
cp .env.example .env          # macOS / Linux
copy .env.example .env        # Windows (cmd)

# 3. Create the tables by running every migration
uv run alembic upgrade head   # or use make migrate

# 4. Start the API (auto-reloads on code changes)
uv run uvicorn app.main:app --reload  # or use make run
```

The `.env.example` defaults match the role and database from Step 3, but `DATABASE_URL`
points at port **5433**, the Docker Compose port. For a native Postgres, change it to
`localhost:5432`. Also check that `MONGO_URL` and `REDIS_URL` point at your MongoDB and Redis
(or start just those two with `docker compose up -d mongo redis`).

To run the background jobs natively, start `make celery-worker` and `make celery-beat` in
separate terminals (and `make flower` to watch them).


---

## Makefile Targets

We provide a self-documenting `Makefile` to standardize common commands instead of remembering raw `uv run ...` or `uv ...` invocations.

To list all available commands grouped by section, run:
```bash
make help  # or simply `make`
```

### Available Targets grouped by section:

#### General & Setup
- `make help` - List all available targets grouped by section.
- `make install` - Installs Python version, all dependencies via `uv sync`, and copies `.env.example` to `.env` if not present.
- `make run` - Starts the FastAPI development server with reload.

#### Database & Migrations
- `make db-shell` - Opens an interactive `psql` shell on the database in `DATABASE_URL` (`.env`).
- `make migrate` - Runs database migrations (upgrades to head).
- `make migrate-create m="message"` - Generates a new database migration revision.
- `make migrate-check` - Fails if the models and the migrations differ (`alembic check`).
- `make migrate-current` - Shows current database migration revision.
- `make migrate-history` - Lists all database migration history.

#### Data Seeding
All seed targets except `seed-clean` truncate every table before loading data.
- `make seed` - Truncates all tables and loads the default demo dataset (~200 tasks).
- `make seed-large` - Truncates all tables and loads 10,000 tasks for query performance benchmarking.
- `make seed-huge` - Truncates all tables and loads 50,000 tasks for heavy stress testing.
- `make seed-clean` - Truncates all tables and leaves an empty schema (0 rows).
- `make seed-reset` / `make db-reset` - Aliases for `make seed`.
- `make db-clean` - Alias for `make seed-clean`.


#### Code Quality & Linting
- `make format` - Formats the codebase using Ruff.
- `make lint` - Runs Ruff to lint, format-check, and Mypy to typecheck the code.
- `make typecheck` - Runs Mypy to typecheck the codebase.
- `make lint-fix` - Auto-fixes lint issues and formats code.
- `make hooks` - Installs the pre-commit git hooks (run once after pulling).
- `make hooks-run` - Runs all pre-commit hooks against every file.

#### Testing & Coverage
- `make test` - Runs the full test suite (unit, integration, auth).
- `make test-unit` - Runs unit tests only; no database needed.
- `make test-integration` - Runs integration tests; needs PostgreSQL, MongoDB and Redis.
- `make test-auth` - Runs auth tests; needs PostgreSQL and MongoDB.
- `make test-cov` - Runs the full test suite with a coverage report.

#### Docker & Containerization
- `make docker-build` - Builds the Docker images for every Compose service with a `build` section.
- `make docker-up` - Starts every Compose service in the background.
- `make docker-down` - Stops and removes every Compose container; named volumes (database data) are kept.
- `make docker-logs` - Follows the `api` logs. Add `s=<service>` for another service, e.g. `make docker-logs s=redis`.
- `make docker-shell` - Open shell inside API container.
- `make docker-db-shell` - Opens a `psql` shell inside the Postgres container, as its `POSTGRES_USER` on `POSTGRES_DB`; no host `psql` needed.
- `make redis-cli` - Open a `redis-cli` shell on the Dockerized Redis.

#### Celery & Background Tasks
These run on the host against the Redis in `.env`; with `make docker-up`, the `celery-worker`, `celery-beat` and `flower` containers already run them.
- `make celery-worker` - Starts a Celery worker (assignment notifications, outbox sweep, due-task reminders).
- `make celery-beat` - Starts Celery Beat, which queues the outbox sweep (every 300s) and the due-task reminder sweep (every 60s).
- `make flower` - Starts Flower on `127.0.0.1:${FLOWER_PORT:-5555}`; it asks for a login when `FLOWER_BASIC_AUTH` is set.
- `make celery-demo` - Scripted Celery jobs demo: success, duplicate delivery, retries, permanent failure, worker offline, A → B → A reassignment.
- `make beat-demo` - Scripted Beat reminder demo: due-date filtering, overlap lock and dedup. It uses its own lock key and rolls back its rows, so it is safe next to the running `celery-beat`; it prints the Flower URL but does not check Flower.
- `make flow-demo` - End-to-end demo against the running Docker stack: one task change through the API, cache, events, worker, Beat and Flower. See [Full-stack walkthrough](#full-stack-walkthrough).

#### Task Events (Redis)
- `make events-pubsub` - Run the Redis Pub/Sub task event consumer until Ctrl+C.
- `make events-streams` - Run the Redis Streams task event consumer until Ctrl+C. Add `NAME=worker-1` to keep the same consumer name across restarts.
- `make events-demo` - Scripted Pub/Sub vs Streams comparison: offline consumer, duplicate events, crash before acknowledgement.

Task status changes and assignments publish events to both transports. See
[`docs/session-05/redis-pubsub-vs-streams.md`](docs/session-05/redis-pubsub-vs-streams.md).

> **Note on host commands with Docker**: When the stack is running via `make docker-up`, PostgreSQL is mapped to host port **5433** (via `compose.override.yaml`). Ensure `DATABASE_URL` in `.env` uses `localhost:5433` (e.g. `postgresql+asyncpg://taskflow:taskflow@localhost:5433/taskflow`) so that host make commands (`make seed`, `make migrate`, `make test`) connect to the container database.
Redis is mapped to host port **6379**, matching `REDIS_URL` in `.env.example`; tests use logical database 15 on the same server.



---

## Running tests

```bash
uv run pytest                 # or use make test
```

Unit tests need nothing running (`make test-unit`). Integration and auth tests run against
real services, not SQLite or fakes, so the schema and constraints (enums, unique indexes,
etc.) are exercised the same way they are in production:

- **PostgreSQL**: the `DATABASE_URL` database name plus `_test` (e.g. `taskflow_test`, created
  in Step 3 or in the Docker quick start). The schema is created once per run; each test runs
  inside a transaction that is rolled back, so tests never see each other's rows.
- **MongoDB**: the `MONGO_DB` name plus `_test`.
- **Redis**: logical database 15 on the `REDIS_URL` server, emptied around each test that uses
  it, so the app's own data is never touched.

---

## Pre-commit hooks

Pre-commit runs quality checks automatically before each commit, so lint, formatting, and type errors are caught locally instead of in CI or review.
The hooks are configured in [`.pre-commit-config.yaml`](.pre-commit-config.yaml):

| Hook | What it does |
|------|--------------|
| `trailing-whitespace`, `check-yaml`, `check-toml`, `check-json`, `check-merge-conflict` | Basic file hygiene |
| `ruff-check` / `ruff-format` | Lints and formats Python code |
| `mypy` | Static type checking of the whole project (`mypy .`) |
| `pytest` | Runs the test suite |

`pre-commit` is installed with the dev dependencies (`make install`).

```bash
make hooks        # or: uv run pre-commit install --config .pre-commit-config.yaml
```

After that the hooks run automatically on `git commit`. To run every hook against the whole
codebase:

```bash
make hooks-run    # or: uv run pre-commit run --all-files
```

---

## Project layout

```
session-05-async-redis-celery/
app/
  main.py              FastAPI application entry point
  api/                 API router and route endpoints
  auth/                Authentication & RBAC dependencies
  services/            Business logic service layer
  repositories/        Database queries and data access layer
  workflows/           Domain workflow and transition engines
  events/              Task events: payload, Redis publisher, Pub/Sub and Streams consumers
  models/              SQLAlchemy ORM models
  schemas/             Pydantic validation schemas
  core/                App settings and exception handlers
  db/                  Database engine, Mongo, and Redis client management
  tasks/               Celery jobs: assignment notifications, outbox sweep, due-task reminders
packages/
  taskflow_shared/     Reusable shared package (errors, pagination, logging, enums, Redis lock, run_async)
scripts/               Seed data, event consumers, and the scripted demos behind the make targets
makefiles/             Make targets, grouped by section and included by the Makefile
alembic/
  env.py               Alembic migration configuration
  versions/            Migration files
tests/
  unit/                Isolated unit tests
  integration/         API and DB integration tests
  auth/                Authentication & RBAC security tests
  fixtures/            Reusable test fixtures and factory helpers
docs/
  session-03/          Preserved documentation and findings from Session 03
  session-04/          Preserved architecture and design docs from Session 04
  session-05/          Async architecture, Redis caching/channeling, Celery jobs & Beat, Flower, and SLOs
demos/
  session-03/          Preserved demos from Session 03
  session-04/          Preserved demos from Session 04
  session-05/          Reproducible demo guides and Loom recordings for Session 05
.env.example           Template for local .env
```

---

## Working with migrations

Migrations are how the database schema changes in a tracked, repeatable way. Instead of
editing tables by hand, you change a model, generate a migration, review it, and apply it —
so every machine ends up with an identical schema.

```bash
# Apply all outstanding migrations (creates/updates tables)
uv run alembic upgrade head   # or use make migrate

# Which migration is the database currently on?
uv run alembic current        # or use make migrate-current

# See the full history
uv run alembic history        # or use make migrate-history

# Undo the most recent migration
uv run alembic downgrade -1

# Undo everything (drops all our tables and enum types)
uv run alembic downgrade base
```

**When you change a model** (add a column, a table, etc.):

```bash
# 1. Generate a migration by diffing the models against the live database
uv run alembic revision --autogenerate -m "short description of the change"  # or use make migrate-create m="message"

# 2. OPEN the generated file in alembic/versions/ and read it before applying.
#    Autogenerate is a starting point, not the final answer — it can miss enum
#    drops, server defaults, and data migrations. Adjust it by hand as needed.

# 3. Apply it
uv run alembic upgrade head   # or use make migrate

# 4. Confirm the models and database now agree (should report no changes)
uv run alembic check          # or use make migrate-check
```

> **Every new model file must be imported in `app/models/__init__.py`.** Alembic only knows
> about tables registered on `Base.metadata`; if a model isn't imported there, autogenerate
> can't see it and will even try to *drop* the table if it already exists.

---

## Seeding & Performance Test Data

The project includes a dedicated, high-performance database seeding script (`scripts/seed_data.py`) separated from Alembic schema migrations. It generates realistic data for users, projects, memberships, and tasks.

### Quick Commands

```bash
# Every command below except db-clean truncates all tables first.

# 1. Seed database with default local demo data (~200 tasks)
make seed

# 2. Seed database with 10,000 tasks for query performance & EXPLAIN ANALYZE testing
make seed-large

# 3. Seed database with 50,000 tasks for heavy stress testing
make seed-huge

# 4. Wipe / truncate all database tables leaving an empty schema (0 rows)
make db-clean

# 5. Same as make seed (alias)
make db-reset
```




### Custom Options

You can also run `scripts/seed_data.py` directly with custom volume parameters:

```bash
uv run python scripts/seed_data.py --reset --users 50 --projects 10 --tasks 5000 --batch-size 1000
```

### Example Terminal Summary Output

```
==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 0.42 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 10
project              | 5
project_user         | 18
task                 | 200
==================================================
```

---


## Inspecting the database

```bash
# Open an interactive psql shell on the database in DATABASE_URL (\q to quit)
make db-shell

# Or, with the Docker stack running, inside the Postgres container
make docker-db-shell
```

Useful commands once inside psql:

```
\dt              list tables
\d task          describe the task table (columns, defaults, indexes, foreign keys)
\dT+             list the enum types and their allowed values
\di              list indexes
\q               quit
```


---

## Using pgAdmin

pgAdmin is a graphical client. It comes bundled with the Windows and macOS installers, or
grab it from [pgadmin.org](https://www.pgadmin.org/).

1. On first launch it asks for a **master password**. This is pgAdmin's own password for
   encrypting saved connections — it is **not** a Postgres password. Set anything.
2. Right-click **Servers → Register → Server…**
3. **General** tab → Name: `TaskFlow Local` (just a label).
4. **Connection** tab:

   | Field | Value |
   |-------|-------|
   | Host name/address | `localhost` |
   | Port | `5432` (`5433` for the Docker stack) |
   | Maintenance database | `taskflow` |
   | Username | `taskflow` |
   | Password | `taskflow` |
   | Save password? | ✓ |

5. **Save.**

Then browse to:

```
Servers → TaskFlow Local → Databases → taskflow → Schemas → public → Tables
```

- **See columns:** expand a table → **Columns**
- **See rows:** right-click a table → **View/Edit Data → All Rows**
- **See the real DDL:** click a table → the **SQL** tab on the right
- **Run your own queries:** **Tools → Query Tool**, then press ▶ (or F5)

> If you already have a server registered on `localhost:5432`, you don't need a new one —
> `taskflow` is just another database on the same server. Right-click the existing server →
> **Refresh**, and `taskflow` appears alongside your other databases.

