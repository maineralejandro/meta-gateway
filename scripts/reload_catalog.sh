#!/usr/bin/env bash
set -euo pipefail

echo "Reloading catalog in running backend..."

source /mnt/c/Mainer-AI/meta-gateway/.env 2>/dev/null || true

AGENT_ID="${AGENT_ID:-1}"
API_URL="${API_URL:-https://api.meta-gateway.localhost}"

RESPONSE=$(curl -sk -X POST \
  -H "Authorization: Bearer ${DASHBOARD_TOKEN}" \
  "${API_URL}/api/agents/${AGENT_ID}/reload" 2>&1)

echo "${RESPONSE}"
