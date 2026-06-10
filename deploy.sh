#!/usr/bin/env bash
# Push code + secrets + cookies to droplet and rebuild containers.
# Usage: ./deploy.sh
set -euo pipefail

HOST="${HOST:-root@168.144.124.121}"
REMOTE="${REMOTE:-/root/pulsetrace}"

echo "==> rsync $PWD -> $HOST:$REMOTE"
rsync -avzP --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '**/__pycache__' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '.mypy_cache' \
  --exclude '.ruff_cache' \
  --exclude 'data/runs/*' \
  --exclude 'data/fb_debug/*' \
  --exclude 'data/event_logs/*' \
  --exclude 'data/embed_cache.jsonl' \
  --exclude '.env.api_keys' \
  --exclude 'test_artifacts' \
  --exclude 'results' \
  --exclude '.claude' \
  --exclude '.idea' \
  --exclude '.vscode' \
  --exclude '*.log' \
  --exclude 'LOCAL_3080_MODEL_PLAN.md' \
  --exclude 'deploy.sh' \
  ./ "$HOST:$REMOTE/"

echo "==> docker compose up -d --build on $HOST"
ssh "$HOST" "cd $REMOTE && docker compose up -d --build && docker compose ps"

echo "==> tail logs (Ctrl+C to detach; container keeps running)"
ssh "$HOST" "cd $REMOTE && docker compose logs --tail=40"
