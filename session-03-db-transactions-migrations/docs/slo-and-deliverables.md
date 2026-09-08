# Session 03 — SLOs and Deliverables

This document defines the Service Level Objectives (SLOs) and key engineering deliverables for Session 03 (Database Correctness, Transactions, Migrations, and Query Performance).

---

## 1. Seed Data Reproducibility SLO

### Objective
Ensure that every developer and reviewer can generate a known, deterministic, and repeatable database state across small and large dataset volumes without embedding demo data into Alembic schema migrations.

### Target Specifications
- **Clean Reset Path**: `make db-reset` or `scripts/seed_data.py --reset` must truncate all user, project, project_user, and task tables cleanly without schema drop/re-create overhead.
- **Data Volume Presets**:
  - **Standard Local Dev (`make seed`)**: Generates ~10 users, 5 projects, and 200 tasks in < 1 second.
  - **Query Performance Benchmarking (`make seed-large`)**: Generates 100 users, 25 projects, and 10,000 tasks in < 3 seconds.
- **Isolation from Migrations**: Database migrations define schema structure only. Data seeding is completely decoupled in `scripts/seed_data.py`.

---

## 2. Additional Session 03 SLOs (Overview)

### Correctness SLO
Task assignment operations must be transaction-safe. If any sub-operation (assignee update, assignment history, activity log) fails, the entire transaction rolls back cleanly without partial writes.

### Migration Safety SLO
All Alembic schema migrations must execute cleanly forward (`alembic upgrade head`) and backward (`alembic downgrade -1`) on both empty databases and databases populated with seed data.

### Query Performance SLO
Task filtering queries on large datasets (10,000+ rows) must show measurable performance improvement after adding index strategies, documented via `EXPLAIN ANALYZE`.
