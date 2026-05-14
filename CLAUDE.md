# AquaTrack — Water Dispensing System

FastAPI + HTMX + Alpine.js + SQLite. Admin UI for resident/station management
and a hardware API for ESP8266 stations. PhilSys QR auth goes through the
MOSIP testbed.

## Local development

Use Python **3.12**, not 3.14. The Homebrew Python 3.14 on this Mac has a
broken `pyexpat` (libexpat symbol mismatch) that causes `pip` itself to crash.

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py        # one-time demo data
python main.py        # uvicorn on :8000
```

Default admin: `admin` / `admin123` (override with `ADMIN_USERNAME` /
`ADMIN_PASSWORD` env vars; `SECRET_KEY` ditto).

## Secrets — `.mosip_keys/`

`mosip.py` lazy-loads `.mosip_keys/config.toml`, which references the partner
PEM and the two PKCS12 keystores in the same directory. Layout:

```
.mosip_keys/
  config.toml
  pdec_ida_partner.pem
  keystore.p12
  keystore-signed.p12
```

Everything in there is gitignored (`.gitignore` covers `config.toml`, `*.p12`,
`*.pem`). The server still starts without these files — `mosip.py` falls back
to a "MOSIP not configured" response on `/api/auth`.

## MOSIP testbed access

The testbed (`api-internal.pdec.mosip.net`, AWS VPC `172.31.0.0/16`) is only
reachable through the project's WireGuard tunnel. Config is in
`wireguard-config.txt` (also gitignored).

The peer config is **single-identity**: only one device (laptop or prod
server) can be on the tunnel at a time. Bring it down on the laptop before
the server is supposed to talk to MOSIP, and vice versa.

## Production: `idro`

SSH alias `idro` → `root@178.128.99.170` (Digital Ocean droplet, Ubuntu 24).
Identity file `~/.ssh/id_idro`.

| Layout                   | Path                                              |
|--------------------------|---------------------------------------------------|
| App                      | `/root/water_dispensing`                          |
| venv (Python 3.12)       | `/root/water_dispensing/.venv`                    |
| Secrets                  | `/root/water_dispensing/.mosip_keys/`             |
| Systemd unit             | `/etc/systemd/system/water-dispensing.service`    |
| WireGuard                | `/etc/wireguard/wg0.conf` + `wg-quick@wg0.service`|
| Public URL (HTTPS)       | `https://178-128-99-170.nip.io`                   |
| Public URL (direct)      | `http://178.128.99.170:8000`                      |
| Reverse proxy            | `/etc/caddy/Caddyfile` (Caddy 2)                  |

Service is enabled on boot and depends on `wg-quick@wg0.service`, so MOSIP
routing is up before uvicorn starts.

### Common ops

```bash
# Status / logs
ssh idro 'systemctl status water-dispensing --no-pager'
ssh idro 'journalctl -u water-dispensing -n 100 --no-pager'

# Restart
ssh idro 'systemctl restart water-dispensing'

# WG state
ssh idro 'wg show wg0'

# Redeploy code (from this repo, working tree)
rsync -az --delete \
  --exclude='.venv/' --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='*.db' --exclude='.git/' --exclude='.DS_Store' \
  --exclude='QR Codes/' --exclude='credentials-18.txt' --exclude='wireguard-config.txt' \
  --exclude='team-18-uins.txt' \
  ./ idro:/root/water_dispensing/
ssh idro 'cd /root/water_dispensing && .venv/bin/pip install -q -r requirements.txt && systemctl restart water-dispensing'
```

`.mosip_keys/` is gitignored *and* rsync-included by default — confirm it
exists on the server after a fresh checkout-style deploy.

### Initial provisioning (already done; reference only)

```bash
ssh idro 'apt-get update && apt-get install -y wireguard wireguard-tools python3.12-venv git rsync'
scp wireguard-config.txt idro:/etc/wireguard/wg0.conf
ssh idro 'chmod 600 /etc/wireguard/wg0.conf && wg-quick up wg0 && systemctl enable wg-quick@wg0'
# rsync the working tree, then:
ssh idro 'cd /root/water_dispensing && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python seed.py'
# install /etc/systemd/system/water-dispensing.service, then:
ssh idro 'systemctl daemon-reload && systemctl enable --now water-dispensing'
```

UFW is inactive on the droplet, so port 8000 is open by default. If UFW is
turned on later: `ufw allow 8000/tcp`.

## Architecture quick map

- `main.py` — FastAPI app + lifespan that creates tables on startup.
- `routers/admin.py` — admin UI (cookie-session auth via HMAC of username).
- `routers/resident.py` — resident self-service: `/resident/login` (camera
  QR scan → MOSIP verify), `/resident/portal` (monthly quota + monthly log),
  `/resident/logout`. Cookie-session auth via HMAC of `philsys_id`. Monthly
  quota is computed as `daily_limit_ml * days_in_current_month`.
- `routers/api_station.py` — hardware API: `/api/auth`, `/api/dispense`,
  `/api/station/heartbeat`, `/api/station/{id}/status`. Auth = `X-API-Key`
  matched against `Station.api_key`.
- `routers/api_resident.py` — JSON CRUD for residents (admin-only).
- `routers/sse.py` — SSE streams for the public homepage station grid, the
  recent-activity feed, and the admin dashboard stats.
- `routers/pages.py` — public homepage and history search.
- `events.py` — in-process pub/sub used by SSE.
- `models.py` — SQLAlchemy: `Resident`, `Station`, `DispensingRecord`.
  `Station.is_online_effective` returns `True` only if `is_online` *and* the
  last heartbeat is within `STATION_OFFLINE_THRESHOLD_SECONDS` (default 60).
- `mosip.py` — lazy `MOSIPAuthenticator`; degrades gracefully when keys
  missing.

### TLS

Caddy fronts the app on `:443` with a Let's Encrypt cert for
`178-128-99-170.nip.io` (auto-renewed). Port `:8000` is still open
unencrypted so existing ESP8266 stations can keep posting heartbeats /
dispense events without any client-side change. Resident QR scanning works
over the HTTPS hostname (the camera API requires HTTPS).

`SECRET_KEY` (config.py) signs the resident session cookie. Without an env
override it's randomized per process, so cookies become invalid on every
restart — set `SECRET_KEY` in the systemd unit's `Environment=` if you need
sessions to persist across deploys.
