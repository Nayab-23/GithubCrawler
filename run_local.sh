#!/usr/bin/env bash
# Runs the verification document crawler directly on this machine.
# Output goes to /tmp/results_local_run.csv — supervisor.py merges it
# into results_local.csv after each successful run.
#
# Make executable: chmod +x run_local.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "[run_local.sh] WARNING: no .env found — relying on exported environment"
fi

QUERIES_FILE="${QUERIES_FILE:-$SCRIPT_DIR/queries.txt}"
OUTPUT_TMP="/tmp/results_local_run.csv"

# Build JSON array from queries.txt — strip surrounding double-quotes from each line
QUERIES_JSON=$(python3 - <<'PYEOF'
import sys, json

queries_file = __import__('os').environ.get('QUERIES_FILE', './queries.txt')
with open(queries_file, encoding='utf-8') as f:
    lines = f.readlines()

queries = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        continue
    # Remove surrounding quotes added for readability in queries.txt
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    queries.append(stripped)

print(json.dumps(queries))
PYEOF
)

echo "[run_local.sh] Launching crawler with $(echo "$QUERIES_JSON" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))') queries → $OUTPUT_TMP"

python3 "$SCRIPT_DIR/crawler.py" "$QUERIES_JSON" "$OUTPUT_TMP"
