#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="file-manager-dashboard.service"
APP_URL="http://127.0.0.1:5000/"

echo "Restarting ${SERVICE_NAME}..."
sudo systemctl daemon-reload
sudo systemctl restart "${SERVICE_NAME}"

echo
echo "Service state:"
sudo systemctl is-active "${SERVICE_NAME}"

echo
echo "Health check:"
if curl -fsS -I "${APP_URL}" >/dev/null; then
  echo "OK - app is responding at ${APP_URL}"
else
  echo "FAILED - app is not responding at ${APP_URL}"
  echo "Recent logs:"
  sudo journalctl -u "${SERVICE_NAME}" -n 40 --no-pager
  exit 1
fi

echo
echo "Useful commands:"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
