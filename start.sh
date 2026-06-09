#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f config.json ]; then
  if [ -f config.json.example ]; then
    echo "config.json not found, copying from config.json.example ..."
    cp config.json.example config.json
    echo "Please edit config.json with your cluster info, then re-run this script."
    exit 1
  else
    echo "config.json not found. Create it first (see config.json.example)."
    exit 1
  fi
fi

echo "Starting Doris Monitor..."
exec python3 app.py
