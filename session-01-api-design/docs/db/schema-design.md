# TaskFlow — Database Schema Design

This document explains the database design for TaskFlow. It covers the entities we are
starting with (user, project, task) and the relationships between them.

This is a design only PR. The migrations will come in a follow up PR once this is
approved.

The diagram is in `ERD.png` (exported from dbdiagram.io) and the source is in `ERD.dbml`
so it can be edited and re rendered later.

## Overview

For this first version we have four tables:

- **user** — people on the team. A user can own projects, be a member of projects, and
  be assigned tasks.
- **project** — a table that groups related tasks. Every project has one owner.
- **task** — the actual unit of work. Every task belongs to a project and can optionally
  be assigned to one user.
- **project_user** — the membership link between users and projects (many to many).

The relationships are:

- One user owns many projects. Each project has exactly one owner (`project.owner_id`).
- One project has many tasks. Each task belongs to exactly one project.
- One user can be assigned many tasks. Each task has at most one assignee (or none).
- Users and projects have a many to many membership: a user can be on many projects, and
  a project can have many members. This is handled by the `project_user` table.

## Tables

### user

| Column     | Type         | Constraints             | Notes                               |
|------------|--------------|-------------------------|-------------------------------------|
| id         | integer      | PK, auto increment      | Primary key                         |
| name       | varchar(100) | not null                | Display name                        |
| email      | varchar(255) | not null, unique        | Used to identify the user, auth purposes |
| is_active  | boolean      | not null, default true  | Lets us deactivate without deleting |
| created_at | timestamptz  | not null, default now() | Set on insert                       |
| updated_at | timestamptz  | not null, default now() | Refreshed on every update           |

Email is unique so we never end up with two accounts on the same address. I kept it as a
plain `varchar` with a unique constraint for now.

`is_active` is there so we can turn a user off instead of hard deleting them.


### project

| Column      | Type         | Constraints                                 | Notes                      |
|-------------|--------------|---------------------------------------------|----------------------------|
| id          | integer      | PK, auto increment                          | Primary key                |
| name        | varchar(150) | not null                                    | Project name               |
| description | text         | nullable                                    | Optional description       |
| owner_id    | integer      | FK -> user.id, not null, ON DELETE RESTRICT | Every project has an owner |
| created_at  | timestamptz  | not null, default now()                     | Set on insert              |
| updated_at  | timestamptz  | not null, default now()                     | Refreshed on update        |

`owner_id` is required — a project can't exist without an owner. The delete rule is
RESTRICT, which means you can't delete a user while they still own projects. This is
intentional: it stops us from accidentally orphaning projects by removing one account.

### task

| Column      | Type          | Constraints                                  | Notes                            |
|-------------|---------------|----------------------------------------------|----------------------------------|
| id          | integer       | PK, auto increment                           | Primary key                      |
| title       | varchar(255)  | not null                                     | Required, short title          |
| description | text          | nullable                                     | Optional details                 |
| status      | task_status   | not null, default 'todo'                     | Enum: todo, in_progress, done    |
| priority    | task_priority | not null, default 'medium'                   | Enum: low, medium, high          |
| due_date    | date          | nullable                                     | Optional deadline                |
| project_id  | integer       | FK -> project.id, not null, ON DELETE CASCADE | The project this task belongs to |
| assignee_id | integer       | FK -> user.id, nullable, ON DELETE SET NULL   | Who's working on it (optional)   |
| created_at  | timestamptz   | not null, default now()                      | Set on insert                    |
| updated_at  | timestamptz   | not null, default now()                      | Refreshed on update              |

**status and priority as enums.** I modelled these as native database enum types
(`task_status` and `task_priority`) rather than plain strings. This makes the set of
allowed values part of the column's type itself, so the database enforces them directly.

**project_id is required and cascades.** A task always belongs to a project, so
`project_id` is not null. If a project is deleted, its tasks go with it (CASCADE) —
there's no meaning to a task without a project, so we don't want them left behind.

**assignee_id is optional and sets null.** The task can be created without an assignee
and assigned later, so this column is nullable. The delete rule is SET NULL, not CASCADE
— if we remove a user, we do NOT want to delete all the tasks they were working on.
Instead the tasks stay and just become unassigned, so the work isn't lost.

### project_user

| Column     | Type         | Constraints             | Notes                              |
|------------|--------------|-------------------------|------------------------------------|
| project_id | integer      | PK, FK -> project.id, ON DELETE CASCADE | Part of composite key  |
| user_id    | integer      | PK, FK -> user.id, ON DELETE CASCADE    | Part of composite key  |
| role       | project_role | not null, default 'member' | Enum: admin, member             |
| joined_at  | timestamptz  | not null, default now() | When the user joined the project   |

This is the join table that implements the many to many membership between users and
projects. Each row means "this user is a member of this project," with a role.

The primary key is the composite `(project_id, user_id)`, which guarantees a user can't
be added to the same project twice. Both foreign keys use ON DELETE CASCADE — a
membership row is only meaningful while both the user and the project exist, so if either
is deleted the membership row is removed (this deletes only the link, not the user's
tasks or anything else).


**About the owner and membership.** The project owner (`project.owner_id`) is also a
member of the project. When a project is created, the owner should be added to
`project_user` with role `admin`. — `owner_id` records the single lead, while `project_user` records full team
membership including the owner.

