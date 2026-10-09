#!/usr/bin/env bash
# Boot the Delaxis image on a clean volume and prove the product works:
# health, the Studio, the API, a tool call, a workflow validation and a
# deployment preview. No LLM key is needed for any of these.
#
#   scripts/smoke_docker.sh delaxis:ci
set -euo pipefail

IMAGE="${1:-delaxis:latest}"
PORT="${SMOKE_PORT:-18000}"
NAME="delaxis-smoke-$$"
VOLUME="delaxis-smoke-data-$$"

cleanup() {
  echo "--- container log (tail) ---"
  docker logs --tail 60 "$NAME" 2>&1 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

start() {
  docker run -d --name "$NAME" -p "$PORT:8000" -e ENVIRONMENT=development \
    -v "$VOLUME:/app/data" "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if curl -sf "$base/health" >/dev/null 2>&1; then break; fi
    sleep 2
  done
  curl -sf "$base/health" | grep -q '"healthy"' || { echo "health check failed"; exit 1; }
}

base="http://localhost:$PORT"
start

expect() { # expect <status> <description> <curl args...>
  local want="$1" what="$2"; shift 2
  local got
  got="$(curl -s -o /dev/null -w '%{http_code}' "$@")"
  if [ "$got" != "$want" ]; then
    echo "FAIL $what: expected $want, got $got"
    exit 1
  fi
  echo "ok   $what ($got)"
}

expect 200 "studio is served"        "$base/"
expect 200 "openapi"                 "$base/openapi.json"
expect 200 "workflows"               "$base/api/v1/workflows"
expect 200 "agents"                  "$base/api/v1/agents"
expect 200 "tools"                   "$base/api/v1/tools"
expect 200 "providers"               "$base/api/v1/api-providers"
expect 200 "deployments"             "$base/api/v1/deployments"
expect 200 "rag collections"         "$base/api/v1/rag/collections"
expect 200 "audit verify"            "$base/api/v1/audit/verify"
expect 200 "studio state"            "$base/api/v1/studio/state"
expect 200 "run history"             "$base/api/v1/runs"
expect 200 "validate starter workflow" -X POST "$base/api/v1/workflows/assistant_chat/validate"
expect 200 "deployment preview" -X POST "$base/api/v1/deployments/preview" \
  -H 'Content-Type: application/json' -d '{"workflow_id":"assistant_chat","name":"smoke"}'

result="$(curl -s -X POST "$base/api/v1/tools/calculate/execute" \
  -H 'Content-Type: application/json' -d '{"args":{"expression":"2+2*5"}}')"
echo "$result" | grep -q '"status":"success"' || { echo "FAIL tool execute: $result"; exit 1; }
echo "$result" | grep -q '12' || { echo "FAIL tool result: $result"; exit 1; }
echo "ok   tool execute"

# An edit made through the API must survive the container being recreated:
# the working configs live on the data volume, not in the image.
expect 200 "edit a workflow" -X PUT "$base/api/v1/workflows/assistant_chat" \
  -H 'Content-Type: application/json' -d '{"description":"Edited by the smoke test"}'
docker rm -f "$NAME" >/dev/null
start
curl -s "$base/api/v1/workflows/assistant_chat" | grep -q "Edited by the smoke test" \
  || { echo "FAIL the edit did not survive recreating the container"; exit 1; }
echo "ok   edits survive recreating the container"

echo "smoke test passed"
