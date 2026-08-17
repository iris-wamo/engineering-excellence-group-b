# TaskFlow — Session 02

Internal team work management backend. This directory holds the FastAPI application, the
SQLAlchemy database models, and the Alembic migrations.

The database design this is built from is documented in
[`docs/db/schema-design.md`](docs/db/schema-design.md), with the diagram in
[`docs/db/ERD.png`](docs/db/ERD.png).

---

## Table of contents

- [Run it with Docker](#run-it-with-docker-quickest)
- [What you need](#what-you-need)
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
- [Inspecting the database](#inspecting-the-database)
- [Using pgAdmin](#using-pgadmin)

---

## What you need

| Tool | Why | Notes |
|------|-----|-------|
| **uv** | Runs Python and installs dependencies | Also installs the right Python for you — you do **not** need to install Python separately |
| **PostgreSQL** | The database | Any modern version works |

The project targets **Python 3.12+**, but `uv` downloads and manages that automatically,
so the only two things you install by hand are uv and PostgreSQL.

---

## Run it with Docker

If you have Docker installed, you don't have to install uv or PostgreSQL yourself.
From this directory, run:

```bash
docker compose up --build     # or make docker-up
```

This does three things for you:

1. builds the app image and starts a PostgreSQL database,
2. waits for the database, then runs the migrations, and
3. starts the API on **http://localhost:8000**.


How it's set up:

- The database username, password, and name are all `taskflow`, and the app connects to
  it using the `DATABASE_URL` environment variable set in `docker-compose.yml`.
- `.dockerignore` lists files that are not copied into the image.

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

From the `session-02-dockerization-and-code-quality/` directory:

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

The defaults in `.env.example` already match the role and database from Step 3, so you
normally don't need to edit `.env`. Only change `DATABASE_URL` if your Postgres uses a
different port, user, or password.


---

## Makefile Targets

We provide a self-documenting `Makefile` to standardize common commands instead of remembering raw `uv run ...` or `uv ...` invocations.

To list all available commands in alphabetical order, run:
```bash
make help  # or simply `make`
```

### Available Targets:
- `make install` - Installs Python version, all dependencies via `uv sync`, and copies `.env.example` to `.env` if not present.
- `make run` - Starts the FastAPI development server with reload.
- `make lint` - Runs Ruff to lint, format-check, and Mypy to typecheck the code.
- `make typecheck` - Runs Mypy to typecheck the codebase.
- `make lint-fix` - Auto-fixes lint issues and formats code.
- `make format` - Formats the codebase using Ruff.
- `make hooks` - Installs the pre-commit git hooks (run once after pulling).
- `make hooks-run` - Runs all pre-commit hooks against every file.
- `make test` - Runs all unit tests.
- `make test-cov` - Runs unit tests with code coverage report.
- `make migrate` - Runs database migrations (upgrades to head).
- `make migrate-create m="message"` - Generates a new database migration revision.
- `make migrate-check` - Verifies database migrations match the current models.
- `make migrate-current` - Shows current database migration revision.
- `make migrate-history` - Lists all database migration history.
- `make db-shell` - Opens an interactive `psql` database shell.
- `make docker-up` - Builds and starts the app and database with Docker.
- `make docker-down` - Stops the Docker containers.
- `make docker-logs` - Shows logs from the Docker containers.


---

## Running tests

```bash
uv run pytest                 # or use make test
```

Tests run against the real `taskflow_test` database created in Step 3 (the test DB name is
derived from `DATABASE_URL` by appending `_test`) — not SQLite — so the schema and
constraints (enums, unique indexes, etc.) are exercised the same way they are in production.
Each test creates the tables it needs and drops them afterward, so the database is empty
between runs.

---

## Pre-commit hooks

Pre-commit runs quality checks automatically before each commit, so lint, formatting, and type errors are caught locally instead of in CI or review.
The hooks are configured in [`.pre-commit-config.yaml`](.pre-commit-config.yaml):

| Hook | What it does |
|------|--------------|
| `trailing-whitespace`, `check-yaml`, `check-toml`, `check-json`, `check-merge-conflict` | Basic file hygiene |
| `ruff-check` / `ruff-format` | Lints and formats Python code |
| `mypy` | Static type checking of `app` |
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
app/
  main.py              FastAPI application entry point
  core/config.py       settings; reads and validates DATABASE_URL from .env
  db/base.py           the Base class every model inherits from, plus the timestamp mixin
  db/session.py        engine, session factory, and the get_db() dependency for FastAPI
  models/              one file per table
    user.py            user
    project.py         project
    task.py            task
    project_user.py    project_user (the membership join table)
    enums.py           the status / priority / role enum types
    __init__.py        imports every model so Alembic can see them
alembic/
  env.py               points Alembic at our models (Base.metadata) and the database URL
  versions/            the migration files
alembic.ini            Alembic configuration
docs/db/               the ERD and the schema design
.env.example           template for your local .env
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

## Inspecting the database

```bash
# Open an interactive psql shell (\q to quit)
psql "postgresql://taskflow:taskflow@localhost:5432/taskflow"  # or use make db-shell
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
   | Port | `5432` |
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

