#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"

fail() {
    printf '[destroy] error: %s\n' "$*" >&2
    exit 1
}

main() {
    command -v docker >/dev/null 2>&1 || fail "required command not found: docker"
    docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is unavailable"
    docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable or inaccessible"
    [[ -f "${COMPOSE_FILE}" ]] || fail "compose file not found: ${COMPOSE_FILE}"

    printf '[destroy] Removing containers and networks; PostgreSQL data is preserved\n'
    docker compose \
        --project-name stocks-trading \
        --project-directory "${SCRIPT_DIR}" \
        --file "${COMPOSE_FILE}" \
        down --remove-orphans
    printf '[destroy] Destroy complete. Run %s/deploy.sh to redeploy.\n' "${SCRIPT_DIR}"
}

main "$@"
