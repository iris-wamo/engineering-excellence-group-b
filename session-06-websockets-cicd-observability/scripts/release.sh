#!/usr/bin/env bash
# Deploy, promote and roll back an already-built TaskFlow image on the local release stacks
# (compose.release.yaml). Build once, deploy many: every command runs an existing image,
# pinned by digest; nothing is built here. See docs/session-06/ci-cd.md (Release).
#
#   scripts/release.sh deploy <staging|production> <image>   migrate, start, smoke test
#   scripts/release.sh promote                               staging's last good digest -> production
#   scripts/release.sh rollback <env> [--downgrade-to REV]   previous good digest, no upgrade
#   scripts/release.sh status [env]
#   scripts/release.sh down <env>                            stop the stack (volumes are kept)
#
# <image> is anything `docker pull`/`docker run` accepts, e.g. ghcr.io/iris-wamo/taskflow-api:sha-<sha>.
#
# State lives in .release/<env>/ (git-ignored):
#   running   the image the stack was last started with (smoke passed or not)
#   good      every image that passed the smoke test there, oldest first
set -euo pipefail

cd "$(dirname "$0")/.."

STATE_DIR=.release
WAIT_TIMEOUT=${WAIT_TIMEOUT:-180}

die() { echo "error: $*" >&2; exit 1; }
log() { printf '\n==> %s\n' "$*"; }

check_env() {
  case "${1:-}" in
    staging | production) ;;
    *) die "environment must be 'staging' or 'production', got '${1:-}'" ;;
  esac
  [ -f ".env.$1" ] || die ".env.$1 not found. Create it: cp .env.$1.example .env.$1 (then set real secrets)"
}

# Reads one KEY from .env.<env> without sourcing it (values may contain shell characters).
env_value() {
  grep -E "^$2=" ".env.$1" | tail -n1 | cut -d= -f2-
}

compose() {
  local env=$1
  shift
  docker compose -p "taskflow-$env" -f compose.release.yaml --env-file ".env.$env" "$@"
}

# Prints the immutable reference for an image: repo@sha256:... when it came from a registry,
# else the local image id (a locally built tag has no registry digest).
resolve() {
  local ref=$1
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    docker pull --quiet "$ref" >/dev/null || die "cannot pull $ref"
  fi
  # Repository without tag or digest. Only a colon in the last path segment is a tag
  # ("localhost:5000/x:tag" -> "localhost:5000/x").
  local repo=${ref%@*}
  case "${repo##*/}" in *:*) repo=${repo%:*} ;; esac
  local digest
  digest=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$ref" \
    | grep -F "$repo@" | head -n1 || true)
  if [ -n "$digest" ]; then echo "$digest"; else docker image inspect --format '{{.Id}}' "$ref"; fi
}

image_git_sha() {
  docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" \
    | sed -n 's/^GIT_SHA=//p'
}

last_good() { [ -f "$STATE_DIR/$1/good" ] && tail -n1 "$STATE_DIR/$1/good" || true; }
running() { cat "$STATE_DIR/$1/running" 2>/dev/null || true; }

smoke() {
  local env=$1 image=$2
  local port email password url sha project_id
  port=$(env_value "$env" API_PORT)
  email=$(env_value "$env" SMOKE_EMAIL)
  password=$(env_value "$env" SMOKE_PASSWORD)
  url="http://127.0.0.1:$port"
  sha=$(image_git_sha "$image")

  SMOKE_EMAIL=$email SMOKE_PASSWORD=$password python3 scripts/smoke_test.py signup --url "$url"
  project_id=$(compose "$env" exec -T db sh -c 'psql -qtA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v email="$0"' "$email" \
    < docker/release/smoke-fixture.sql | sed -n 's/^SMOKE_PROJECT_ID=//p')
  [ -n "$project_id" ] || die "smoke fixture did not return a project id"
  SMOKE_EMAIL=$email SMOKE_PASSWORD=$password python3 scripts/smoke_test.py check \
    --url "$url" --project-id "$project_id" ${sha:+--expect-sha "$sha"}
}

# deploy <env> <image> [--no-migrate]
deploy() {
  local env=$1 ref=$2 migrate=${3:-}
  check_env "$env"
  local image
  image=$(resolve "$ref")
  mkdir -p "$STATE_DIR/$env"
  export IMAGE=$image

  log "[$env] deploying $image (git sha: $(image_git_sha "$image" || echo unknown))"
  # Any failure from here on (a failing command under set -e, or die) exits the script;
  # the trap records it and prints how to roll back.
  trap 'on_failure "$env"' EXIT

  compose "$env" up -d --wait --wait-timeout "$WAIT_TIMEOUT" db mongo redis
  if [ "$migrate" = "--no-migrate" ]; then
    log "[$env] skipping migrations (rollback: this image may not know the newest revision)"
  else
    log "[$env] alembic upgrade head"
    compose "$env" run --rm migrate
  fi

  log "[$env] starting api, celery-worker, celery-beat"
  echo "$image" > "$STATE_DIR/$env/running"
  # --wait needs a healthcheck: only the api has one (the workers serve no HTTP)
  compose "$env" up -d --wait --wait-timeout "$WAIT_TIMEOUT" api
  compose "$env" up -d celery-worker celery-beat

  log "[$env] smoke test"
  smoke "$env" "$image"
  trap - EXIT

  if [ "$(last_good "$env")" != "$image" ]; then
    echo "$image" >> "$STATE_DIR/$env/good"
  fi
  echo "$(date -u +%FT%TZ) $env ok $image" >> "$STATE_DIR/history.log"
  log "[$env] released $image"
}

on_failure() {
  local status=$? env=$1
  [ "$status" -ne 0 ] || return 0
  echo "$(date -u +%FT%TZ) $env FAILED ${IMAGE:-?}" >> "$STATE_DIR/history.log"
  cat >&2 <<EOF

==> [$env] DEPLOY FAILED: ${IMAGE:-?} is running but did not pass.
    Last good release: $(last_good "$env" || true)
    Roll back:  make rollback ENV=$env
    Logs:       docker compose -p taskflow-$env -f compose.release.yaml logs api
EOF
}

promote() {
  local image
  image=$(last_good staging)
  [ -n "$image" ] || die "staging has no release that passed the smoke test; deploy one first"
  log "promoting staging's last good release to production: $image"
  deploy production "$image"
}

rollback() {
  local env=$1
  shift
  local downgrade_to=""
  if [ "${1:-}" = "--downgrade-to" ]; then
    downgrade_to=${2:?--downgrade-to needs an Alembic revision}
  fi
  check_env "$env"
  local current good target
  current=$(running "$env")
  good=$(last_good "$env")

  if [ -n "$current" ] && [ "$current" = "$good" ]; then
    # The running release passed its smoke test but is bad: go back to the one before it,
    # and drop it from the good list so promote and later rollbacks never pick it again.
    target=$(tail -n2 "$STATE_DIR/$env/good" | sed -n '1{N;P;}')
    [ -n "$target" ] || die "no earlier good release recorded for $env"
    sed -i.bak '$d' "$STATE_DIR/$env/good" && rm -f "$STATE_DIR/$env/good.bak"
  else
    # The running release never passed: the last good one is the way back.
    target=$good
    [ -n "$target" ] || die "no good release recorded for $env"
  fi

  if [ -n "$downgrade_to" ]; then
    # Only the newer image contains the migration's downgrade(); the older one can't run it.
    log "[$env] alembic downgrade $downgrade_to, using the running image $current"
    IMAGE=$current compose "$env" run --rm migrate alembic downgrade "$downgrade_to"
  fi
  log "[$env] rolling back from ${current:-nothing} to $target"
  deploy "$env" "$target" --no-migrate
}

status() {
  local envs=${1:-"staging production"} env port
  for env in $envs; do
    printf '\n[%s]\n  running:   %s\n  last good: %s\n' "$env" "$(running "$env")" "$(last_good "$env")"
    if [ -f ".env.$env" ]; then
      port=$(env_value "$env" API_PORT)
      printf '  /version:  %s\n' "$(curl -fsS --max-time 3 "http://127.0.0.1:$port/version" 2>/dev/null || echo 'not answering')"
    fi
  done
}

case "${1:-}" in
  deploy) [ $# -eq 3 ] || die "usage: $0 deploy <env> <image>"; deploy "$2" "$3" ;;
  promote) promote ;;
  rollback) [ $# -ge 2 ] || die "usage: $0 rollback <env> [--downgrade-to REV]"; rollback "${@:2}" ;;
  status) status "${2:-}" ;;
  down) check_env "${2:-}"; IMAGE=unused compose "$2" down ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
