# engineering-excellence-group-b
A production-minded FastAPI backend demonstrating clean REST API design, validation, consistent response models, pagination, filtering, and maintainable architecture.

This repo is organized as a series of engineering exercises, one directory per session, each building on the last.

## Sessions

### Session 01 — API Design ([`session-01-api-design/`](session-01-api-design/))

Build the base version of TaskFlow — a team work-management backend — with clean API contracts. This session established:

- A layered architecture (`endpoint → service → repository → model`) with a shared error envelope for every error response.
- SQLAlchemy models and Alembic migrations for the core data model: `user`, `project`, `task`, and the `project_user` membership join.
- CRUD APIs for Users, Projects, and Tasks, each with validation, pagination, and consistent error handling.

See [`session-01-api-design/README.md`](session-01-api-design/README.md) for setup instructions.

### Session 02 — Dockerization & Code Quality ([`session-02-dockerization-and-code-quality/`](session-02-dockerization-and-code-quality/))

Take the Session 01 API and harden it for production use. This session covers:

- Migrating the database layer from synchronous to async SQLAlchemy, so the API is non-blocking end-to-end.
- Dockerizing the application.
- Code-quality tooling: mypy type checking, pre-commit hooks, and a Makefile for common project commands.
- Reviewing and tightening exception handling for environment-specific behavior.

See [`session-02-dockerization-and-code-quality/README.md`](session-02-dockerization-and-code-quality/README.md) for setup instructions.


### Session 03 — Database Correctness, Transactions, Migrations, and Query Performance ([`session-03-db-transactions-migrations/`](session-03-db-transactions-migrations/))

Take the Session 02 API forward with a focus on database correctness, transactions, migrations, and query performance.

See [`session-03-db-transactions-migrations/README.md`](session-03-db-transactions-migrations/README.md) for setup instructions.


## Pull request description format

Every PR in this repository must use the following structure. This applies to every directory/project in this repo, not just the one it's introduced in.

```markdown
## Summary
- Bullet list of concrete changes made

## Why
1-2 sentences on the motivation/context, not just a restatement of the summary

## Assumptions Taken (if any)
- Any assumption made where requirements were ambiguous or unspecified

## Test plan
- [x] Actual command run and its real outcome (e.g. `uv run ruff check .` — passes)
- [x] Actual command run and its real outcome (e.g. `uv run pytest` — runs cleanly, 3 passed)
```

Test plan items must reflect commands that were actually run, with their real results — not unchecked TODO placeholders.
