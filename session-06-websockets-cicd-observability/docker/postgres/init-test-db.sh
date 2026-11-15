#!/bin/sh
# Creates the database the test suite uses, if it doesn't exist yet. Safe to run any time.
#
# Runs automatically when the Postgres data directory is first created (official image:
# /docker-entrypoint-initdb.d, mounted by compose.override.yaml). For a volume created
# before that, run it by hand with `make docker-test-db`.
#
# The name must match tests/fixtures/database.py, which uses the DATABASE_URL database name
# plus "_test". That holds as long as POSTGRES_DB and the DATABASE_URL database name agree
# (they do in .env.example).
set -e

# psql variables (:'name') quote the values safely; they only work on stdin, not -c.
# CREATE DATABASE has no IF NOT EXISTS, so build it with format(%I) and run it with \gexec
# only when pg_database has no such row.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v test_db="${POSTGRES_DB}_test" -v owner="$POSTGRES_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'test_db', :'owner')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'test_db')\gexec
SQL
