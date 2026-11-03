#!/usr/bin/env bash
# ==============================================================================
# Paper Daily - Local macOS Runner for launchd & n8n
# Uses local CPA (Gemini 3.8 Flash), local proxy, and local Python pipeline
# ==============================================================================
set -euo pipefail

# 1. Environment and PATH initialization (portable, no hardcoded user paths)
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/daily_$(date +'%Y-%m-%d').log"
exec >> "$LOG_FILE" 2>&1

echo "================================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Paper Daily Local Run"
echo "================================================================="

cd "$PROJECT_DIR"

# 2. Check local CPA daemon (cli-proxy-api) on port 8317 if installed
if ! /usr/bin/nc -z 127.0.0.1 8317 2>/dev/null; then
    CPA_BIN="$(command -v cli-proxy-api || echo "$HOME/.local/bin/cli-proxy-api")"
    if [ -x "$CPA_BIN" ]; then
        CPA_CONFIG_PATH="${CPA_CONFIG:-$HOME/.cli-proxy-api/config.yaml}"
        if [ -f "$CPA_CONFIG_PATH" ]; then
            echo "[INFO] Starting local cli-proxy-api daemon in background..."
            nohup "$CPA_BIN" -config "$CPA_CONFIG_PATH" > "$LOG_DIR/cpa.log" 2>&1 &
            sleep 2
        fi
    fi
fi

# 3. Execute paper-daily pipeline
uv run paper-daily "$@"

EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Paper Daily finished with exit code: $EXIT_CODE"
exit $EXIT_CODE
