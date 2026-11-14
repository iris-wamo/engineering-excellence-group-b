#!/bin/sh
# Runs once, when the Postgres data directory is first created (official image:
# /docker-entrypoint-initdb.d). Creates the database the test suite uses.
#
# The name must match tests/fixtures/database.py, which uses the DATABASE_URL database name
# plus "_test". That holds as long as POSTGRES_DB and the DATABASE_URL database name agree
# (they do in .env.example).
set -e

# psql variables (:"name") quote the identifiers safely; they only work on stdin, not -c.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v test_db="${POSTGRES_DB}_test" -v owner="$POSTGRES_USER" <<'SQL'
CREATE DATABASE :"test_db" OWNER :"owner";
SQL
