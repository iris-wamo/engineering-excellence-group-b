#!/bin/sh
# Runs once, when the Postgres data directory is first created (official image:
# /docker-entrypoint-initdb.d). Creates the database the test suite uses, which is the
# app database name plus "_test" (see tests/fixtures/database.py).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE \"${POSTGRES_DB}_test\" OWNER \"$POSTGRES_USER\""
