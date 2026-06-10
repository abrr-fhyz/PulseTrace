#!/usr/bin/env bash
# One-time droplet provisioning for PulseTrace behind host nginx + TLS.
#
# Run ON the droplet, from the project dir, as root (or via sudo).
# Assumes code is already cloned and secrets are in place (see PRECHECK below).
#
#   sudo DOMAIN=pulsetrace.example.com EMAIL=you@example.com ./scripts/droplet_setup.sh
#
# Idempotent: safe to re-run. Skips steps already done.
set -euo pipefail

DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
APP_PORT="${APP_PORT:-5000}"          # must match docker-compose host bind (127.0.0.1:5000)
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENABLE_TLS="${ENABLE_TLS:-1}"         # set 0 to skip certbot (HTTP only)

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo)."
[[ -n "$DOMAIN" ]] || die "set DOMAIN=your-domain.com"

# ---------------------------------------------------------------------------
# PRECHECK: secrets must exist (gitignored — transferred out-of-band).
# ---------------------------------------------------------------------------
log "Precheck: required secret files"
[[ -f "$PROJECT_DIR/.env" ]] || die "missing $PROJECT_DIR/.env — copy it from your machine first."
[[ -f "$PROJECT_DIR/info/cookies.json" ]] || \
  echo "WARN: no info/cookies.json — Facebook connector will be disabled."
# .env.api_keys is optional now (.env carries the canonical keys). Warn if it
# is a directory (the broken-mount footgun) so the compose mount stays sane.
if [[ -d "$PROJECT_DIR/.env.api_keys" ]]; then
  echo "WARN: .env.api_keys is a DIRECTORY — remove it; .env already holds the keys."
fi

# ---------------------------------------------------------------------------
# Docker + compose plugin
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  log "Installing docker compose plugin"
  apt-get update && apt-get install -y docker-compose-plugin
fi

# ---------------------------------------------------------------------------
# Firewall
# ---------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
  log "Configuring firewall (OpenSSH, 80, 443)"
  ufw allow OpenSSH    >/dev/null 2>&1 || true
  ufw allow 80/tcp     >/dev/null 2>&1 || true
  ufw allow 443/tcp    >/dev/null 2>&1 || true
  ufw --force enable   >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# nginx reverse proxy
# ---------------------------------------------------------------------------
log "Installing + configuring nginx"
command -v nginx >/dev/null 2>&1 || { apt-get update && apt-get install -y nginx; }

SITE="/etc/nginx/sites-available/pulsetrace"
cat > "$SITE" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # SSE: stream live agent events without buffering; long-lived connections.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
NGINX

ln -sf "$SITE" /etc/nginx/sites-enabled/pulsetrace
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ---------------------------------------------------------------------------
# TLS via certbot (Let's Encrypt)
# ---------------------------------------------------------------------------
if [[ "$ENABLE_TLS" == "1" ]]; then
  [[ -n "$EMAIL" ]] || die "set EMAIL=you@example.com for Let's Encrypt (or ENABLE_TLS=0)."
  log "Issuing TLS cert via certbot"
  command -v certbot >/dev/null 2>&1 || apt-get install -y certbot python3-certbot-nginx
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
fi

# ---------------------------------------------------------------------------
# Build + launch the stack
# ---------------------------------------------------------------------------
log "Building + starting containers"
cd "$PROJECT_DIR"
docker compose up -d --build
docker compose ps

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
log "Waiting for health"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$APP_PORT/status" >/dev/null 2>&1; then
    log "Healthy. Live at https://$DOMAIN/"
    exit 0
  fi
  sleep 3
done
die "app did not become healthy — check: docker compose logs -f"
