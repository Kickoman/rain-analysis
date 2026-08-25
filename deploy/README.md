# Backend deployment

Vendor-agnostic (#221): assumes "some Linux server" with docker and a
reverse proxy. Nothing here references a specific host; per-server values
live in untracked `.env` files.

## Layout

| File | Purpose |
|---|---|
| `bootstrap.sh` | One-shot privileged setup: compose + migrations + nginx |
| `Dockerfile` | Dependencies-only image; code is bind-mounted (#221) |
| `docker-compose.yml` | One backend service, one worker (#421), SQLite file in the mounted repo (#417) |
| `nginx-location.conf.example` | Reverse-proxy location block to adapt |
| `update.sh` | Routine update: pull → build → migrate → restart |

## One-shot bootstrap

With `backend/.env` and `deploy/.env` in place (see below), a single
privileged script does everything — compose build/up, migrations, nginx
snippet + include, smoke test. Idempotent, safe to re-run:

```bash
sudo bash deploy/bootstrap.sh \
    --server-name <your https server_name> \
    --nginx-site /etc/nginx/sites-enabled/<your site config> \
    [--docker-user <user to add to the docker group>] \
    [--public-url https://<host>/<prefix>]
```

## First-time setup on a server (manual steps)

```bash
git clone https://github.com/Kickoman/rain-analysis.git && cd rain-analysis

# App secrets
cp backend/.env.example backend/.env
# edit backend/.env: set API_KEYS_SALT (>=32 chars), CORS_ORIGINS

# Optional per-server overrides for compose
printf 'BACKEND_PORT=7010\nROOT_PATH=/rain-api\n' > deploy/.env

docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml run --rm backend \
    python -m alembic upgrade head

# Bootstrap the first admin key
docker compose -f deploy/docker-compose.yml run --rm backend \
    python scripts/create_admin_key.py <owner> --environment live
```

Then adapt `nginx-location.conf.example` into the HTTPS server block of
your site and reload nginx. The container binds to 127.0.0.1 only; TLS is
the proxy's job.

## Updates

```bash
bash deploy/update.sh
```

## Data

The whole state is two things inside the repo checkout (both gitignored):
`backend/rain_analysis.db` (SQLite — no separate database service, per
#417) and `backend/models/*.pkl`. Backing up the deployment is copying
those files.

## Recurring jobs

The backend never fetches data itself — push jobs feed it (see
`docs/ha-integration.md`). On the server, ground truth wants a daily cron
before the 00:00 UTC ML task, e.g.:

```cron
30 23 * * * cd <repo> && RAIN_BACKEND_KEY=$(cat <keyfile>) \
  .venv/bin/python scripts_utils/push_ground_truth.py \
  --backend-url http://127.0.0.1:7010
```

(or the same via `docker compose run --rm backend` if the host has no
venv).
