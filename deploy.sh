#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
readonly UNIVERSE_FILE="data/universe/idx_2025-09-20.csv"

log() {
    printf '[deploy] %s\n' "$*"
}

fail() {
    printf '[deploy] error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

compose() {
    docker compose \
        --project-name stocks-trading \
        --project-directory "${SCRIPT_DIR}" \
        --file "${COMPOSE_FILE}" \
        "$@"
}

wait_for_database() {
    local container_id
    local status
    local attempt

    container_id="$(compose ps --quiet db)"
    [[ -n "${container_id}" ]] || fail "PostgreSQL container was not created"

    for attempt in $(seq 1 60); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
        case "${status}" in
            healthy)
                return 0
                ;;
            unhealthy|exited|dead)
                compose logs db >&2 || true
                fail "PostgreSQL entered state: ${status}"
                ;;
        esac
        sleep 1
    done

    compose logs db >&2 || true
    fail "PostgreSQL did not become healthy within 60 seconds"
}

wait_for_application() {
    local container_id
    local status
    local attempt

    container_id="$(compose ps --quiet app)"
    [[ -n "${container_id}" ]] || fail "application container was not created"

    for attempt in $(seq 1 60); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
        case "${status}" in
            healthy)
                return 0
                ;;
            unhealthy|exited|dead)
                compose logs app >&2 || true
                fail "application entered state: ${status}"
                ;;
        esac
        sleep 1
    done

    compose logs app >&2 || true
    fail "application did not become healthy within 60 seconds"
}

wait_for_frontend() {
    local container_id
    local status
    local attempt

    container_id="$(compose ps --quiet web)"
    [[ -n "${container_id}" ]] || fail "frontend container was not created"

    for attempt in $(seq 1 60); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
        case "${status}" in
            healthy)
                return 0
                ;;
            unhealthy|exited|dead)
                compose logs web >&2 || true
                fail "frontend entered state: ${status}"
                ;;
        esac
        sleep 1
    done

    compose logs web >&2 || true
    fail "frontend did not become healthy within 60 seconds"
}

main() {
    require_command docker
    docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is unavailable"
    docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable or inaccessible"
    [[ -f "${COMPOSE_FILE}" ]] || fail "compose file not found: ${COMPOSE_FILE}"
    [[ -f "${SCRIPT_DIR}/${UNIVERSE_FILE}" ]] || fail "universe file not found: ${UNIVERSE_FILE}"

    log "Building the application image from current source"
    compose build app
    log "Building the frontend image from current source"
    compose build web
    log "Building the scheduler image from current source"
    compose build scheduler

    log "Starting PostgreSQL"
    compose up --detach db
    wait_for_database

    log "Applying database migrations"
    compose run --rm --entrypoint uv app run alembic upgrade head

    local security_count
    security_count="$(
        compose exec --no-TTY db \
            psql --username stocks --dbname stocks --tuples-only --no-align \
            --command 'SELECT COUNT(*) FROM securities;'
    )"
    security_count="${security_count//[[:space:]]/}"
    [[ "${security_count}" =~ ^[0-9]+$ ]] || fail "could not determine securities count"

    if [[ "${security_count}" == "0" ]]; then
        log "Importing the initial IDX universe"
        compose run --rm app universe import --file "${UNIVERSE_FILE}"
    else
        log "Universe already contains ${security_count} securities; skipping seed import"
    fi

    log "Starting the HTTP application on port 21235"
    compose up --detach app
    wait_for_application

    log "Starting the frontend on port 21231"
    compose up --detach web
    wait_for_frontend

    log "Starting the market-calendar-aware pipeline scheduler"
    compose up --detach scheduler

    log "Deployment complete"
    compose ps
    printf '\nApplication:\n'
    printf '  API:  http://localhost:21235\n'
    printf '  Docs: http://localhost:21235/docs\n'
    printf '  Web:  http://localhost:21231\n'
    printf '\nRun CLI commands with:\n'
    printf '  cd %q && docker compose run --rm app market update\n' "${SCRIPT_DIR}"
}

main "$@"
