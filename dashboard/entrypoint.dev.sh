#!/bin/bash
set -e

if [ -f package.json ]; then
    npm install --silent 2>/dev/null
fi

exec "$@"
