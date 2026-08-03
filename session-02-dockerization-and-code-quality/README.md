# TaskFlow — Session 02

Internal team work management backend. This directory holds the FastAPI application, the
SQLAlchemy database models, and the Alembic migrations.

The database design this is built from is documented in
[`docs/db/schema-design.md`](docs/db/schema-design.md), with the diagram in
[`docs/db/ERD.png`](docs/db/ERD.png).

---

## Table of contents

- [What you need](#what-you-need)
- [Step 1 — Install uv](#step-1--install-uv)
- [Step 2 — Install PostgreSQL](#step-2--install-postgresql)
  - [macOS](#macos)
  - [Linux](#linux)
  - [Windows](#windows)
- [Step 3 — Create the database and user](#step-3--create-the-database-and-user)
- [Step 4 — Configure and run](#step-4--configure-and-run)
- [Running tests](#running-tests)
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
uv sync

# 2. Create your local env file from the template
cp .env.example .env          # macOS / Linux
copy .env.example .env        # Windows (cmd)

# 3. Create the tables by running every migration
uv run alembic upgrade head

# 4. Start the API (auto-reloads on code changes)
uv run uvicorn app.main:app --reload
```

The defaults in `.env.example` already match the role and database from Step 3, so you
normally don't need to edit `.env`. Only change `DATABASE_URL` if your Postgres uses a
different port, user, or password.


---

## Running tests

```bash
uv run pytest
```

Tests run against the real `taskflow_test` database created in Step 3 (the test DB name is
derived from `DATABASE_URL` by appending `_test`) — not SQLite — so the schema and
constraints (enums, unique indexes, etc.) are exercised the same way they are in production.
Each test creates the tables it needs and drops them afterward, so the database is empty
between runs.

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
uv run alembic upgrade head

# Which migration is the database currently on?
uv run alembic current

# See the full history
uv run alembic history

# Undo the most recent migration
uv run alembic downgrade -1

# Undo everything (drops all our tables and enum types)
uv run alembic downgrade base
```

**When you change a model** (add a column, a table, etc.):

```bash
# 1. Generate a migration by diffing the models against the live database
uv run alembic revision --autogenerate -m "short description of the change"

# 2. OPEN the generated file in alembic/versions/ and read it before applying.
#    Autogenerate is a starting point, not the final answer — it can miss enum
#    drops, server defaults, and data migrations. Adjust it by hand as needed.

# 3. Apply it
uv run alembic upgrade head

# 4. Confirm the models and database now agree (should report no changes)
uv run alembic check
```

> **Every new model file must be imported in `app/models/__init__.py`.** Alembic only knows
> about tables registered on `Base.metadata`; if a model isn't imported there, autogenerate
> can't see it and will even try to *drop* the table if it already exists.

---

## Inspecting the database

```bash
# Open an interactive psql shell (\q to quit)
psql "postgresql://taskflow:taskflow@localhost:5432/taskflow"
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

