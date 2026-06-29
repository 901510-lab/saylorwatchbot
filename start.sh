#!/usr/bin/env bash
set -e

echo "Starting SaylorWatchBot..."
cd "$(dirname "$0")"

if [ ! -f main.py ]; then
  echo "ERROR: main.py not found in $(pwd)"
  echo "Upload the full project (see pack_deploy.sh → saylorwatch_deploy.zip)."
  echo "Contents of this directory:"
  ls -la
  exit 1
fi

exec python3 main.py
