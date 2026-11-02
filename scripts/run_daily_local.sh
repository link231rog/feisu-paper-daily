#!/usr/bin/env bash
# ==============================================================================
# Paper Daily - Local macOS Runner for launchd & n8n
# Uses local CPA (Gemini 3.8 Flash), local proxy, and local Python pipeline
# ==============================================================================
set -euo pipefail

# 1. Environment and PATH initialization
export PATH="/Users/huangzixuan/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

PROJECT_DIR="/Users/huangzixuan/Documents/Dev/feisu-paper-daily"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/daily_$(date +'%Y-%m-%d').log"
exec >> "$LOG_FILE" 2>&1

echo "================================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Paper Daily Local Run"
echo "================================================================="

cd "$PROJECT_DIR"

# 2. Check local CPA daemon (cli-proxy-api) on port 8317
if ! /usr/bin/nc -z 127.0.0.1 8317 2>/dev/null; then
    echo "[WARN] CPA daemon is not listening on 127.0.0.1:8317."
    echo "[INFO] Attempting to start cli-proxy-api in background..."
    if [ -x "/Users/huangzixuan/.local/bin/cli-proxy-api" ]; then
        nohup /Users/huangzixuan/.local/bin/cli-proxy-api -config /Users/huangzixuan/.cli-proxy-api/config.yaml > "$LOG_DIR/cpa.log" 2>&1 &
        sleep 2
    fi
fi

# 3. Execute paper-daily pipeline
uv run paper-daily "$@"

EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Paper Daily finished with exit code: $EXIT_CODE"
exit $EXIT_CODE
