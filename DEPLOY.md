# Deploying PulseTrace to a DigitalOcean Droplet

## Droplet sizing

| Plan          | RAM | vCPU | OK? |
|---------------|-----|------|-----|
| Basic 2GB     | 2GB | 1    | tight — 1 worker only, no concurrent runs |
| **Basic 4GB** | 4GB | 2    | **recommended** |
| CPU-Opt 4GB   | 4GB | 2    | best if scraping heavy |
| 8GB+          | 8GB | 4    | needed if Ollama backend or 3+ concurrent runs |

Image: **Ubuntu 22.04 LTS**, region near your users, add SSH key.

## One-time host setup

```bash
ssh root@<droplet-ip>

# Docker + compose plugin
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin git ufw

# Firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Optional: swap (recommended on 2GB droplets)
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## Deploy

```bash
git clone <your-repo-url> /opt/pulsetrace
cd /opt/pulsetrace
cp .env.example .env
nano .env   # set DOCS_ADMIN_TOKEN, REDDIT_*, GEMINI_API_KEY, etc.

# (optional) place Facebook cookies for FB connector
mkdir -p info && nano info/cookies.json

docker compose up -d --build
docker compose logs -f
```

Server live at `http://<droplet-ip>/`. /docs at `http://<droplet-ip>/docs`.

## TLS (free Let's Encrypt via Caddy sidecar)

Add to `docker-compose.yml`:

```yaml
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80","443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
volumes:
  caddy_data:
```

Change `pulsetrace.ports` to `expose: ["5000"]`. Create `Caddyfile`:

```
your-domain.com {
  reverse_proxy pulsetrace:5000
}
```

DNS A record → droplet IP. Caddy auto-fetches TLS cert.

## Update

```bash
cd /opt/pulsetrace
git pull
docker compose up -d --build
```

## Persistence

Host-mounted volumes:
- `./data` — run artifacts, screenshots, docs config
- `./info` — Facebook cookies, IG/X session files

Back up: `tar czf pulsetrace-backup-$(date +%F).tgz data info .env`.

## 2GB droplet tweaks

In `docker-compose.yml`:
- `mem_limit: 1800m`
- `shm_size: "512m"`

In `Dockerfile` CMD, drop to 1 worker:
```
CMD ["gunicorn","-k","gthread","-w","1","--threads","8","--timeout","600","-b","0.0.0.0:5000","server:app"]
```

## /docs visibility

Default window: **2026-06-10 00:00 → 2026-06-14 23:59**. Outside window → 403.

Flip immediately:
1. Visit `http://<droplet-ip>/docs/admin`
2. Token = `DOCS_ADMIN_TOKEN` from `.env`
3. Check **Override schedule (always on)** → Save

Or edit `data/docs_config.json` directly + `docker compose restart`.
