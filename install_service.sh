#!/usr/bin/env bash
# Installs and starts the verification document crawler systemd service.
# Run once on the Pi from ~/GithubCrawler:
#
#   chmod +x install_service.sh
#   ./install_service.sh

set -euo pipefail

SERVICE_NAME="githubcrawler"
SERVICE_FILE="$(cd "$(dirname "$0")" && pwd)/githubcrawler.service"
DEST="/etc/systemd/system/${SERVICE_NAME}.service"
VENV="/home/nayab/GithubCrawler/.venv"
ENV_FILE="/home/nayab/GithubCrawler/.env"
SUPERVISOR="/home/nayab/GithubCrawler/supervisor.py"

echo "=== Verification Document Crawler — systemd install ==="
echo ""

# ── pre-flight checks ──────────────────────────────────────────────────────

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "  Copy .env.example to .env and fill in your values first."
    exit 1
fi

if [ ! -f "$SUPERVISOR" ]; then
    echo "ERROR: supervisor.py not found at $SUPERVISOR"
    exit 1
fi

if [ ! -f "$VENV/bin/python3" ]; then
    echo "ERROR: virtualenv not found at $VENV"
    echo "  Create it with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# ── stop existing unit if running ─────────────────────────────────────────

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "  Stopping existing $SERVICE_NAME service …"
    sudo systemctl stop "$SERVICE_NAME"
fi

# ── install service file ──────────────────────────────────────────────────

echo "  Installing $DEST"
sudo cp "$SERVICE_FILE" "$DEST"
sudo chmod 644 "$DEST"

# ── reload, enable, start ─────────────────────────────────────────────────

echo "  Running: sudo systemctl daemon-reload"
sudo systemctl daemon-reload

echo "  Running: sudo systemctl enable $SERVICE_NAME"
sudo systemctl enable "$SERVICE_NAME"

echo "  Running: sudo systemctl start $SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# ── wait a moment and report status ──────────────────────────────────────

sleep 3

echo ""
echo "=== Service status ==="
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
# Check it's actually running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✓  $SERVICE_NAME is active (running)"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status $SERVICE_NAME"
    echo "  sudo systemctl stop   $SERVICE_NAME"
    echo "  sudo systemctl restart $SERVICE_NAME"
    echo "  tail -f /home/nayab/GithubCrawler/supervisor.log"
    echo "  tail -f /home/nayab/GithubCrawler/crawl.log"
    echo "  journalctl -u $SERVICE_NAME -f"
else
    echo "✗  $SERVICE_NAME did NOT start — check logs above"
    echo "  journalctl -u $SERVICE_NAME --no-pager -n 40"
    exit 1
fi
