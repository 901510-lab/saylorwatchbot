#!/usr/bin/env bash
set -e

echo "Installing missing dependencies..."
pip install --no-cache-dir inputimeout==1.0.4

echo "Starting SaylorWatchBot..."
python main.py
