#!/bin/bash
set -e

if [ -f requirements.txt ]; then
    pip install --no-cache-dir -r requirements.txt 2>/dev/null
fi

exec "$@"
