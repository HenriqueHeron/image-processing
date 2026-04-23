# AGENTS

## Quick start
- `docker compose -f docker/docker-compose.yml up -d` – starts `custom‑proxy` (host 8080 → container 80) and `docker‑app‑1` (exposed on 8000 inside Docker). The proxy mounts `/var/run/docker.sock`; keep that mount or scaling will fail.
- `python docker/test_load_balancer.py` – verifies auto‑scaling; run **after** the compose command. The script sends two batches of 10 requests, waits 10 s, and expects a second container to appear.
- `docker compose -f docker/docker-compose.yml down` – stop everything.

## Proxy & auto‑scaling
- Environment variables (set in `docker-compose.yml` or overridden via an `.env` file):
  - `SCALE_THRESHOLD` – average active connections per container that trigger a scale‑up (default 5).
  - `MAX_CONTAINERS` – hard cap for scaling (default 10).
  - `COMPOSE_PROJECT` – Docker‑Compose project name (`docker` by default) used by the proxy to filter containers.
  - `TARGET_SERVICE` – service name to scale (`app` by default).
  - `TARGET_PORT` – port the backend FastAPI service listens on (`8000` by default).
- The proxy discovers backends with the Docker SDK (`docker.from_env()`) filtering containers by label `com.docker.compose.project` and `com.docker.compose.service`.
- Scaling is performed by running inside the proxy container:
  ```
  docker compose -p $COMPOSE_PROJECT -f /app/docker-compose.yml up -d \
      --scale $TARGET_SERVICE=$TARGET_COUNT \
      --no-recreate --no-build
  ```
  The command requires the Docker socket to be mounted read/write.

## Docker specifics
- All Dockerfiles live under `docker/`. `Dockerfile` builds the FastAPI app; `Dockerfile.proxy` builds the reverse‑proxy.
- Named volume `processed_data` is declared and mounted at `/app/data/outputs` inside the app container.
- Network `app‑network` (bridge driver) connects `proxy` and `app`. Do not rename it without updating the proxy code (`networks: app‑network`).

## Testing
- Only test script is `docker/test_load_balancer.py`. No unit tests. Run it directly with Python; it requires `httpx` (installed in the proxy image but also available on the host after `pip install httpx`).
- The script expects the proxy to be reachable at `http://localhost:8080/process`.

## Logging & debugging
- Proxy logs: `docker logs -f custom-proxy`.
- Application logs: `docker logs -f docker-app-1` (or any container whose name starts with `docker-app-`).
- To inspect discovered backends: `docker ps --filter "label=com.docker.compose.project=docker" --filter "label=com.docker.compose.service=app"`.

## Firewall (optional)
- Script: `firewall/setup-firewall.sh`. Must be run as root (`sudo ./firewall/setup-firewall.sh`).
- The script automatically picks the first available tool (`ufw` → `firewalld` → `iptables`). In WSL, it now prepends `/usr/sbin:/sbin` to `PATH`.
- Default rules (from `firewall/iptables.rules`):
  - Drop all inbound traffic by default.
  - Allow SSH (22/tcp), HTTP (80/tcp), HTTPS (443/tcp), and the Docker internal network `172.16.0.0/12`.
- After enabling, verify with `sudo ufw status verbose` or `sudo iptables -L -n -v`.

## Common pitfalls
- **Missing Docker socket** – the proxy cannot scale without `-v /var/run/docker.sock:/var/run/docker.sock`. Ensure the compose file includes this volume.
- **No firewall tools installed** – on WSL the script may not find `ufw`/`firewalld`. Install at least one (`sudo apt-get install -y ufw`) or rely on the iptables fallback.
- **Running the test before services are up** – always start the compose stack first.
- **Port confusion** – the proxy listens on host port 8080 (container port 80). The app listens on internal port 8000; it is *not* exposed to the host.
- **Environment variable overrides** – to change scaling behaviour, create a `.env` file in the repo root with the variable definitions; Docker Compose will pick it up automatically.
- **Running commands from Windows PowerShell** – use Linux‑style paths (`/mnt/c/...`) inside WSL, or run Docker commands directly from PowerShell (Docker Desktop integrates with Windows).
