#!/usr/bin/env sh
set -e

alembic upgrade head
exec "$@"