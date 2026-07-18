#!/usr/bin/env sh

set -eu

if [ "$#" -eq 0 ]; then
    exec uv run uvicorn stocks_trading.api.app:app \
        --host 0.0.0.0 \
        --port "${STOCKS_APP_PORT:-21235}"
fi

exec uv run stocks "$@"
