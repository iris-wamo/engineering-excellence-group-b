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

### Seeding Execution Results

#### Standard Local Dev Seed (`make seed`)
```text
$ make seed
uv run python scripts/seed_data.py --reset
Starting seed process (Target: 10 users, 5 projects, 200 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 10 users...
Seeding 5 projects...
Seeding project memberships...
Seeding 200 tasks (batch size: 1000)...
  Inserted tasks 1 to 200...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 0.11 seconds
--------------------------------------------------
Table Name           | Row Count      
--------------------------------------------------
user                 | 10             
project              | 5              
project_user         | 23             
task                 | 200            
==================================================
```

#### Query Performance Benchmarking (`make seed-large`)
```text
$ make seed-large
uv run python scripts/seed_data.py --reset --tasks 10000 --users 100 --projects 25
Starting seed process (Target: 100 users, 25 projects, 10000 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 100 users...
Seeding 25 projects...
Seeding project memberships...
Seeding 10000 tasks (batch size: 1000)...
  Inserted tasks 1 to 1000...
  Inserted tasks 1001 to 2000...
  Inserted tasks 2001 to 3000...
  Inserted tasks 3001 to 4000...
  Inserted tasks 4001 to 5000...
  Inserted tasks 5001 to 6000...
  Inserted tasks 6001 to 7000...
  Inserted tasks 7001 to 8000...
  Inserted tasks 8001 to 9000...
  Inserted tasks 9001 to 10000...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 1.08 seconds
--------------------------------------------------
Table Name           | Row Count      
--------------------------------------------------
user                 | 100            
project              | 25             
project_user         | 786            
task                 | 10000          
==================================================
```

#### Stress Testing Dataset (`make seed-huge`)
```text
$ make seed-huge
uv run python scripts/seed_data.py --reset --tasks 50000 --users 200 --projects 50
Starting seed process (Target: 200 users, 50 projects, 50000 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 200 users...
Seeding 50 projects...
Seeding project memberships...
Seeding 50000 tasks (batch size: 1000)...
  Inserted tasks 1 to 1000...
  ...
  Inserted tasks 49001 to 50000...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 5.01 seconds
--------------------------------------------------
Table Name           | Row Count      
--------------------------------------------------
user                 | 200            
project              | 50             
project_user         | 2699           
task                 | 50000          
==================================================
```


---

## 2. Additional Session 03 SLOs (Overview)

### Correctness SLO
Task assignment operations must be transaction-safe. If any sub-operation (assignee update, assignment history, activity log) fails, the entire transaction rolls back cleanly without partial writes.

### Migration Safety SLO
All Alembic schema migrations must execute cleanly forward (`alembic upgrade head`) and backward (`alembic downgrade -1`) on both empty databases and databases populated with seed data.

### Query Performance SLO
Task filtering queries on large datasets (10,000+ rows) must show measurable performance improvement after adding index strategies, documented via `EXPLAIN ANALYZE`.
