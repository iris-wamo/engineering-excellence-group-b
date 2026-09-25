# Migration Safety Checklist

A simple checklist for reviewing a pull request (PR) that changes the database with an Alembic migration.

## Before you start: a few words explained

- **Migration**: a Python file in `alembic/versions/` that changes the database structure, e.g. adds a table or a column.
- **Upgrade**: applying the migration (`alembic upgrade`).
- **Downgrade**: undoing the migration (`alembic downgrade`).
- **Parent revision**: the migration that comes just before this one.
- **Backfill**: filling a new column with values for rows that already exist.
- **Constraint**: a rule the database enforces, e.g. "this value must be unique".
- **Lock**: while a migration changes a table, PostgreSQL can make other queries on that table wait.

## How to use it

1. Test the migration on a **throwaway database**, never a shared one.
2. Go through each question below.
3. Mark every item with one of these words, plus a short reason:

| Word | Meaning |
|---|---|
| PASS | Checked, and it's fine |
| FAIL | Checked, and there's a problem |
| RISK | Checked; it's only a problem in some situations |
| N/A | Doesn't apply to this migration |
| UNVERIFIED | Not checked yet |

## Handy commands

**First, find two IDs.** Open the migration file. Near the top you'll see:

```python
revision = "aae8fcd27de6"   # the ID of THIS migration
down_revision = None        # the ID of the migration BEFORE it
```

- **This migration's ID** is `revision`.
- **The one before it** is `down_revision`. If it says `None`, this is the first migration, so use the word `base` (it means "empty database").

**Then run these commands in order**, on a **test** database:

1. `uv run alembic heads` shows the newest migration. You should see **one** line.
2. `uv run alembic upgrade <ID before>` moves the database to just before the migration.
3. `uv run alembic upgrade <this ID>` applies the migration. It should finish with no errors.
4. `uv run alembic check` should say `No new upgrade operations detected.`
5. `uv run alembic downgrade <ID before>` undoes the migration. It should finish with no errors.
6. `uv run alembic upgrade <this ID>` applies it again. It should still work.

**Example with this repo's migration**, where this ID is `aae8fcd27de6` and the ID before is `base`:

```bash
uv run alembic heads                  # shows: aae8fcd27de6 (head)
uv run alembic upgrade base
uv run alembic upgrade aae8fcd27de6
uv run alembic check                  # shows: No new upgrade operations detected.
uv run alembic downgrade base
uv run alembic upgrade aae8fcd27de6
```

---

## The checklist

### 1. Migration order
- [ ] **1.1** Does `alembic heads` show exactly **one** head?
  *Why:* with two heads, `alembic upgrade head` refuses to run.
- [ ] **1.2** Could another open PR create a second head, because it starts from the same parent revision?

### 2. Can it be undone? (reversibility)
- [ ] **2.1** Does `downgrade()` remove everything `upgrade()` added, in reverse order?
- [ ] **2.2** Does `downgrade()` leave alone things created by older migrations, such as shared enum types?
- [ ] **2.3** After upgrade → downgrade → upgrade, is the database structure the same as after a single upgrade?

### 3. What happens to existing data?
- [ ] **3.1** Can any existing row break the new rules? Examples: a value too long for the new column, a duplicate where values must be unique, or an empty value where one is required.
- [ ] **3.2** If the migration fails halfway, is the database left exactly as it was before?

### 4. Required columns (NOT NULL)
- [ ] **4.1** If a required (NOT NULL) column is added to a table that has rows, are those rows filled first, or is there a default value?
- [ ] **4.2** Will the **old** version of the app still work after the migration runs? (While a new version is being deployed, old app code may still be running.)

### 5. Filling in data (backfills)
- [ ] **5.1** Can a filled-in value be too long for the column?
- [ ] **5.2** Can two filled-in values be the same where they must be unique?
- [ ] **5.3** Does the migration create values in the **same format** as the app code that will create them later? If not, new rows can clash with old ones.
- [ ] **5.4** On a big table, will the fill take too long or lock the table for too long?

### 6. Rules (constraints)
- [ ] **6.1** Does every new rule have a clear name, so the downgrade can remove it by name?
- [ ] **6.2** Do existing rows already follow the new rule? If not, the migration will fail.
- [ ] **6.3** When a rule is broken, does the app return a clear error instead of crashing?


### 7. Seed data (sample data)
- [ ] **7.1** Is sample data kept **out** of the migration file?
- [ ] **7.2** Does the seed script still work on the **old** (parent) database structure? You need that to test the migration against existing data.
- [ ] **7.3** Does the seed script work on the **new** database structure?


### 8. Table locking
- [ ] **8.1** Which tables will be blocked while the migration runs, and does the block stop reads, writes, or both?
- [ ] **8.2** Did you know all migrations in one `alembic upgrade` run share **one transaction**? The blocks last until the very end, and one failure undoes all of them.


### 9. Proof
- [ ] **9.1** Does the PR show the results of: an upgrade on an empty DB, an upgrade on a DB with data, a downgrade, and upgrade → downgrade → upgrade?
- [ ] **9.2** Can someone else repeat those tests using scripts that are committed to the repo?
- [ ] **9.3** Does the PR say which parts were written by `alembic --autogenerate` and which were written by hand?

---

## Self-test: which migration was checked?

The checklist was tested against the only migration in this folder: **`aae8fcd27de6`**, called `initial schema`.

- **File:** `alembic/versions/2026_07_24_1533-aae8fcd27de6_initial_schema.py`
- **Comes after:** nothing. It is the first migration and starts from an empty database.

**What this migration does, in plain words:**
1. Creates the 4 main tables: `user`, `project`, `project_user` (who is in which project) and `task`.
2. Creates 3 enum types (lists of allowed values): `task_status`, `task_priority` and `project_role`.
3. Adds the rules: unique email per user, links between tables (foreign keys), and "only one owner per project".

**How it was tested:** on throwaway PostgreSQL 16 databases in a temporary Docker container. No real database was touched.

Because this is the **first** migration, many questions are N/A: there was no older database with rows, and no older app version.

| Item | Result | What we found |
|---|---|---|
| 1.1 | PASS | `alembic heads` shows one head: `aae8fcd27de6` |
| 1.2 | PASS | No other migration starts from an empty database. |
| 2.1 | PASS | Undo removed all 4 tables and all 3 enum types |
| 2.2 | N/A | There are no older migrations |
| 2.3 | PASS | The database structure after undo + redo was exactly the same as after the first upgrade |
| 3.1 | N/A | It starts from an empty database, so there are no existing rows |
| 3.2 | PASS | When it failed on purpose (tables already there), the database was left exactly as before |
| 4.1, 4.2 | N/A | The tables are brand new and empty, and there is no older app version |
| 5.1–5.4 | N/A | Nothing is filled in; there is no backfill |
| 6.1 | RISK | Only the "one owner per project" rule has a name chosen by us. The other rules got names picked by PostgreSQL (e.g. `user_email_key`), so future migrations must use those exact names |
| 6.2 | N/A | No existing rows |
| 6.3 | RISK | A duplicate email gives a clear error. The other rules have no error handling in the app |
| 7.1 | PASS | No sample data in the migration file |
| 7.2 | N/A | The database before this migration is empty, so there's nothing to seed |
| 7.3 | PASS | The seed script worked after the migration: 10 users, 5 projects, 200 tasks |
| 8.1 | PASS | It only creates new tables, so nothing that's already in use gets blocked |
| 8.2 | PASS | Everything runs in one transaction, so the failed run in 3.2 was fully undone |
| 9.1 | FAIL | No results of an undo or undo + redo test are saved in the repo |
| 9.2 | RISK | The README and Makefile show the commands, but there's no script that runs these tests |
| 9.3 | FAIL | The file says "auto generated", but 3 lines in `downgrade()` were written by hand (they delete the enum types). This isn't written anywhere |
