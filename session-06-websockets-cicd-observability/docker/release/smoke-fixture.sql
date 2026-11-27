-- Gives the smoke-test user a project it owns, so the smoke test can create, assign and move
-- a task over the API. Run by scripts/release.sh after the smoke user has signed up; safe to
-- repeat. Creating a project needs the admin role, and a fresh database has no admin, so this
-- one step is done in SQL. The project is only ever touched by the smoke test.
--
-- psql variables: :'email' (the smoke user's email). Workspace 1 is created by migrations.
\set ON_ERROR_STOP on

INSERT INTO project (name, slug, description, workspace_id)
SELECT 'Release smoke test', 'release-smoke-test',
       'Created by the release smoke test (scripts/smoke_test.py). Safe to ignore.', 1
WHERE NOT EXISTS (
    SELECT FROM project WHERE workspace_id = 1 AND slug = 'release-smoke-test'
);

INSERT INTO project_user (project_id, user_id, role)
SELECT p.id, u.id, 'owner'
FROM project p, "user" u
WHERE p.workspace_id = 1 AND p.slug = 'release-smoke-test' AND u.email = :'email'
ON CONFLICT DO NOTHING;

SELECT p.id AS smoke_project_id
FROM project p
WHERE p.workspace_id = 1 AND p.slug = 'release-smoke-test' \gset
\echo SMOKE_PROJECT_ID=:smoke_project_id
