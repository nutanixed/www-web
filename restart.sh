#!/bin/bash
# File Manager Dashboard Restart Script
# This script kills any running dashboard instances and starts a fresh one with a watchdog loop

echo "🔄 Restarting File Manager Dashboard..."

# Kill any existing dashboard watchdog loops and processes
echo "🛑 Stopping existing dashboard processes..."
# Kill the watchdog loop
pkill -f "bash -c while true.*web-www" 2>/dev/null || true
# Kill Gunicorn processes associated with this specific directory and port
pkill -f "/home/ubuntu/web-www/.venv/bin/gunicorn.*5000" 2>/dev/null || true

# Wait a moment for processes to terminate
sleep 2

# Verify processes are stopped
if pgrep -f "web-www.*gunicorn" > /dev/null; then
    echo "⚠️  Force killing remaining dashboard processes..."
    pkill -9 -f "web-www.*gunicorn" 2>/dev/null || true
    sleep 1
fi

# Change to the dashboard directory
cd /home/ubuntu/web-www

# Start the watchdog loop in the background
echo "🚀 Starting Flask application with watchdog loop..."
nohup bash -c 'while true; do 
    source .venv/bin/activate && \
    gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 300 \
    --error-logfile /tmp/file-manager-error.log \
    app:app >> /tmp/file-manager-dashboard.log 2>&1
    echo "[$(date)] Dashboard crashed with exit code $?. Restarting..." >> /tmp/file-manager-dashboard.log
    sleep 1
done' > /dev/null 2>&1 &

WATCHDOG_PID=$!

# Wait a moment for watchdog to start
sleep 2

# Check if watchdog is running
if ps -p $WATCHDOG_PID > /dev/null; then
    echo "✅ Dashboard started successfully with self-healing loop"
    echo "📝 Logs: tail -f /tmp/file-manager-dashboard.log"
    echo "🌐 Dashboard: http://10.142.155.173:5000"
    echo ""
    echo "To stop: pkill -f 'web-www.*loop'"
else
    echo "❌ Failed to start dashboard. Check /tmp/file-manager-dashboard.log for errors."
    exit 1
fi
