#!/usr/bin/env bash
# Launch the coordinator from the Raspberry Pi.
#
# Make executable: chmod +x run_crawl.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Remind the user to configure .env if it doesn't exist
# ---------------------------------------------------------------------------
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "  *** WARNING: .env file not found in $SCRIPT_DIR ***"
    echo ""
    echo "  Create a .env file with the following variables before running:"
    echo ""
    echo "    PC_IPS=192.168.1.101,192.168.1.102,..."
    echo "    PC_USER=student"
    echo "    QUERIES_FILE=./queries.txt"
    echo "    RESULTS_DIR=./results"
    echo "    OUTPUT_FILE=./final_leads.csv"
    echo "    LOCAL_DOC_DIRS=/abs/path/specs,/abs/path/logs"
    echo ""
    echo "  Aborting."
    exit 1
fi

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
echo "[$(date '+%H:%M:%S')] Starting coordinator ..."
echo ""

python3 "$SCRIPT_DIR/coordinator.py"
