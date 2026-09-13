#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
echo "Starting SOPAL Smart Core Warehouse demo..."
echo "Backend and frontend will run in this terminal group."
./start_backend.sh &
BACK_PID=$!
sleep 3
./start_frontend.sh &
FRONT_PID=$!
trap 'kill $BACK_PID $FRONT_PID 2>/dev/null || true' INT TERM EXIT
wait
