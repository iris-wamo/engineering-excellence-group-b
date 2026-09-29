# Demo: Row Locks and Deadlocks

## Loom Video

https://www.loom.com/share/1153f6b42e5f4158b04c7103b6b209b4

## Objective

Show what happens when two database sessions try to update the same rows at the same time, in a
different order. First we show one session simply **blocking** and waiting for the other. Then we
show two sessions blocking on *each other* at the same time, which Postgres detects as a
**deadlock** and resolves by cancelling one of them.

## Scenario

Two people are editing tasks at the same time, but going in a different order:

- **Session 1** updates task id 1.
- **Session 2** updates task id 2, then tries to update task id 1.

Each session locks the row it updates until it commits or rolls back. Because they lock the rows
in opposite order, they end up waiting on each other forever — that's a deadlock. Postgres notices
this automatically and kills one of the two sessions so the other can continue.

## Commands / Steps Used

Seed the database first so there's real data to lock (from the session directory):

```bash
make seed-large
```

Two terminals, both connected to the same database (the seeded Docker DB on port 5433):

```bash
psql "postgresql://taskflow:taskflow@localhost:5433/taskflow"
```

We'll use task **id 1** and **id 2** below (present after `make seed-large`).

**Terminal 1:**

```sql
BEGIN;
UPDATE task SET status = 'in_progress' WHERE id = 1;
-- stop here, don't run anything else yet
```

**Terminal 2** (after Terminal 1 has run its update above):

```sql
BEGIN;
UPDATE task SET status = 'in_progress' WHERE id = 2;   -- fine, different row
UPDATE task SET status = 'done' WHERE id = 1;           -- blocks: Terminal 1 already holds this row
-- Terminal 2 now hangs here, waiting
```

**Back in Terminal 1** (this closes the cycle):

```sql
UPDATE task SET status = 'done' WHERE id = 2;   -- Terminal 2 is holding this row -> deadlock
```

Within about a second, Postgres's deadlock detector fires. One of the two terminals gets a
`deadlock detected` error and its transaction is automatically rolled back. The other terminal's
blocked update then goes through immediately.

Afterwards, run `ROLLBACK;` (or `COMMIT;`) in whichever session is still open, to leave the
database clean.

## Expected Behavior

- Terminal 2's second `UPDATE` blocks and does not return.
- A few seconds after Terminal 1 runs its second `UPDATE`, Postgres detects that the two sessions
  are waiting on each other and errors out one of them with `deadlock detected`.
- The surviving session's blocked `UPDATE` then completes right away.
- No `statement_timeout` is involved — Postgres finds the deadlock on its own; you don't wait for
  a timeout.

## Actual Findings

<!-- TODO: fill in after re-running with evidence -->

## Evidence

<!-- TODO: paste both terminals' full output here, including the `ERROR: deadlock detected` block -->

## What We Learned

- **Why it happened:** each `UPDATE` takes a row-level lock that's held until `COMMIT`/`ROLLBACK`.
  When two transactions lock the same two rows in opposite order, each ends up waiting for a lock
  the other one holds — a circular wait, i.e. a deadlock.
- **Why it's not just a hang forever:** Postgres runs a periodic deadlock check. When it finds a
  cycle like this, it picks one of the transactions as the "victim," cancels it with an error, and
  releases its locks so the other transaction can proceed.
- **How to avoid it in the app:**
  - Always acquire locks (update rows) in a **consistent order** across all code paths — e.g.
    always update the lower task ID first, or always go through the same service method rather
    than composing updates ad hoc.
  - Keep transactions **short** — don't hold a transaction open while waiting on user input, an
    external API call, etc.
  - If a deadlock is possible, the calling code should be ready to catch it and retry the whole
    transaction, since one side of it is always rolled back automatically.

