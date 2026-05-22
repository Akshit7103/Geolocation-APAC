# ProPosition Location API

A small, stateless HTTP API that enriches geographic coordinates with Google
Maps data. Send it a single `lat`/`lng` or an Excel/CSV of many, and it returns
a **ZIP** containing, for each location: a static map, a Street View image
(when available), and a 360° Street View viewer.

Built with **FastAPI**, served by **Gunicorn + Uvicorn workers**, packaged with
**Docker Compose**. No database, no background jobs — each request is processed
synchronously and the result is returned in the response.

---

## Quick start (Docker)

```bash
# 1. Configure
cp .env.example .env
#   then edit .env and set GOOGLE_MAPS_API_KEY

# 2. Run (detached / background)
docker compose up -d --build

# 3. Verify
curl http://localhost:8000/health        # -> {"status":"ok"}
```

Stop the service:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f
```

> The container listens on **8000**. `docker-compose.yaml` maps it to the host
> port set by `HOST_PORT` in `.env` (default `8000`).

---

## The endpoint

### `POST /api/get_data`

Provide **either** an uploaded file **or** `lat` + `lng` query parameters.

**Returns:** `application/zip`. The filename is unique per request:
`{ZIP_NAME_PREFIX}_{UTC-timestamp}_{random}.zip` (prefix set in `.env`).

#### A. Single coordinate (real-time)

```bash
curl -OJ "http://localhost:8000/api/get_data?lat=19.0760&lng=72.8777"
```

#### B. Bulk file upload

CSV/XLS/XLSX with latitude & longitude columns. Column names are flexible and
case-insensitive — latitude: `lat` / `latitude`; longitude: `lng` / `long` /
`longitude`.

```bash
curl -OJ -F "file=@coords.csv" "http://localhost:8000/api/get_data"
```

#### ZIP layout

One numbered folder per location:

```
1/map.png        1/street.jpg (if available)   1/360.html
2/map.png        2/street.jpg                   2/360.html
```

### `GET /health`

Liveness probe — returns `{"status": "ok"}`.

### Interactive docs

FastAPI serves Swagger UI at **`/docs`** and the OpenAPI schema at
`/openapi.json`. Use `/docs` to try the endpoint from a browser.

---

## How the consumer reaches it

Once deployed on a host (e.g. an internal Linux box at `172.16.0.4`), the
endpoint URL is:

```
http://172.16.0.4:8000/api/get_data
```

CORS is open and Gunicorn binds `0.0.0.0`, so the service is reachable from
other machines on the network. **Rate limiting and access control are expected
to be handled upstream** (e.g. an nginx reverse proxy) by the hosting team.

---

## Configuration (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_MAPS_API_KEY` | yes | — | Server-side key. Needs Geocoding, Places, Maps Static, Street View Static (+ Maps JavaScript for 360.html). |
| `GOOGLE_MAPS_BROWSER_KEY` | no | falls back to `GOOGLE_MAPS_API_KEY` | Key embedded in the generated `360.html`. Use a separate, HTTP-referrer-restricted key so the server key never leaves the host. |
| `ZIP_NAME_PREFIX` | no | `proposition` | Prefix of the returned ZIP filename. |
| `HOST_PORT` | no | `8000` | Host port mapped to the container. |
| `WORKERS` | no | `2*cores + 1` | Gunicorn worker processes. |
| `TIMEOUT` | no | `120` | Per-request worker timeout (seconds). |

---

## Local development (without Docker)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Windows  (source .venv/bin/activate on *nix)
pip install -r requirements.txt

# dev server with auto-reload + Swagger at http://127.0.0.1:8000/docs
uvicorn main:app --reload
```

Use Gunicorn (as in production) only on Linux/macOS:

```bash
gunicorn main:app -c gunicorn.conf.py
```

---

## Project layout

```
.
├── main.py              # FastAPI app + the /api/get_data endpoint
├── maps2.py             # Google Maps calls + per-coordinate processing
├── gunicorn.conf.py     # Production server config (env-driven)
├── Dockerfile           # python:3.12-slim image
├── docker-compose.yaml  # one-command run
├── requirements.txt     # pinned dependencies
├── .env.example         # copy to .env and fill in
└── README.md
```

---

## Notes

- **Stateless:** nothing is persisted between requests, so running multiple
  Gunicorn workers is safe (no shared in-process state).
- **Google API costs:** each location triggers several billed Google API calls.
  There is intentionally no rate limiting in this service — control usage at the
  proxy/key level.
