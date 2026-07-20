# TaskFlow — Database Schema Design

This document explains the database design for the TaskFlow. It covers the three
entities we are starting with (users, projects, tasks)

This is a design only PR. The migrations will come in a follow up PR once this is approved.

The diagram is in `ERD.png` (exported from dbdiagram.io) and the source is in `ERD.dbml`
so it can be edited and re rendered later.

## Overview

For this first version we have three tables:

- **users** — people on the team. A user can own projects and can be assigned tasks.
- **projects** — a table that groups related tasks. Every project has one owner.
- **tasks** — the actual unit of work. Every task belongs to a project and can
  optionally be assigned to one user.

The relationships are:

- One user owns many projects (maybe the superuser will only be able to add the projects later). Each project has exactly one owner.
- One project has many tasks. Each task belongs to exactly one project.
- One user can be assigned many tasks. Each task has at most one assignee (or none).

## Tables

### users

| Column      | Type         | Constraints                    | Notes                                  |
|-------------|--------------|--------------------------------|----------------------------------------|
| id          | integer      | PK, auto increment             | Primary key                  |
| name        | varchar(100) | not null                       | Display name                           |
| email       | varchar(255) | not null, unique               | Used to identify the user, auth purposes |
| is_active   | boolean      | not null, default true         | Lets us deactivate without deleting    |
| created_at  | timestamptz  | not null, default now()        | Set on insert                          |
| updated_at  | timestamptz  | not null, default now()        | Should be refreshed on every update    |

Email is unique so we never end up with two accounts on the same address. I kept it
as a plain `varchar` with a unique constraint for now

`is_active` is there so we can turn a user off instead of hard deleting them.
### projects

| Column      | Type         | Constraints                          | Notes                          |
|-------------|--------------|--------------------------------------|--------------------------------|
| id          | integer      | PK, auto increment                   | Primary key |
| name        | varchar(150) | not null                             | Project name                   |
| description | text         | nullable                             | Optional description    |
| owner_id    | integer      | FK → users.id, not null, ON DELETE RESTRICT | Every project has an owner |
| created_at  | timestamptz  | not null, default now()              | Set on insert                  |
| updated_at  | timestamptz  | not null, default now()              | Refreshed on update            |

`owner_id` is required — a project can't exist without an owner. The delete rule is
RESTRICT, which means you can't delete a user while they still own projects. This is
intentional: it stops us from accidentally orphaning of projects by removing
one account. If we ever need to delete such a user, the projects have to be reassigned
or removed first.

### tasks

| Column      | Type         | Constraints                                | Notes                              |
|-------------|--------------|--------------------------------------------|------------------------------------|
| id          | integer      | PK, auto increment                         | Primary key              |
| title       | varchar(255) | not null                                   | Required, short summary            |
| description | text         | nullable                                   | Optional details                   |
| status      | task_status  | not null, default 'todo'                   | Enum: todo, in_progress, done    |
| priority    | task_priority  | not null, default 'medium'                 | Enum: low, medium, high          |
| due_date    | date         | nullable                                   | Optional deadline                  |
| project_id  | integer      | FK → projects.id, not null, ON DELETE CASCADE | The project this task belongs to |
| assignee_id | integer      | FK → users.id, nullable, ON DELETE SET NULL | Who's working on it (optional)   |
| created_at  | timestamptz  | not null, default now()                    | Set on insert                      |
| updated_at  | timestamptz  | not null, default now()                    | Refreshed on update                |



**status and priority as enums.** I modelled these as native database enum types
(`task_status` and `task_priority`) rather than plain strings. This makes the set of
allowed values part of the column's type itself, so the database enforces them directly.

**project_id is required and cascades.** A task always belongs to a project, so
`project_id` is not null. If a project is deleted, its tasks go with it (CASCADE) —
there's no meaning to a task without a project, so we don't want them left behind.

**assignee_id is optional and sets null.** The task can be created without an assignee
and assigned later, so this column is nullable. The delete rule is SET NULL, not
CASCADE — if we remove a user, we do NOT want to delete all the tasks they were working
on. Instead the tasks stay and just become unassigned, so the work isn't lost.

