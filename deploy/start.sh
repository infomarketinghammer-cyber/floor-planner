#!/bin/bash
# Runs the API (localhost only) and the gateway (public, on $PORT) in one container. If either
# stops, the container exits so the host restarts it, instead of serving errors half-up.
set -u

cd /app/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
api=$!

cd /app/gateway
node src/server.js &
gateway=$!

trap 'kill -TERM "$api" "$gateway" 2>/dev/null' TERM INT
wait -n "$api" "$gateway"
status=$?
kill -TERM "$api" "$gateway" 2>/dev/null
wait
exit "$status"
