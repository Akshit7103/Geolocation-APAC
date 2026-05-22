# ProPosition API — Technical Reference

This document describes how the service works internally. For setup and usage,
see [README.md](README.md).

## Overview

ProPosition is a stateless **FastAPI** service that enriches geographic
coordinates with Google Maps data and returns the generated assets as a ZIP.
There is no UI, no database, and no background job system: a request comes in,
it is processed synchronously, and the ZIP is returned in the response. This
makes the service safe to run across multiple Gunicorn workers — there is no
shared in-process state.

It replaces an earlier Flask web app that used in-memory job tracking, a
progress-polling UI, and downloadable report pages.

## Architecture

```
client (LOS / system)                    this service
        │                          ┌──────────────────────────┐
        │  POST /api/get_data      │ main.py (FastAPI)         │
        ├─────────────────────────►│  • parse file or lat/lng  │
        │                          │  • build DataFrame        │
        │                          │  • maps2.process_dataframe│──► Google Maps APIs
        │   200  application/zip   │  • zip the assets         │◄──  images / JSON
        │◄─────────────────────────│  • return StreamingResp.  │
        │   {prefix}_{ts}_{id}.zip └──────────────────────────┘
```

- **`main.py`** — the FastAPI app and the single `POST /api/get_data` endpoint,
  plus a `GET /health` probe. Reads config from the environment, wires the
  Google keys into `maps2`, validates input, calls processing, packs the ZIP.
- **`maps2.py`** — all Google Maps interaction and per-coordinate processing.
  Pure of any web-framework concerns; callable as a library.
- **`gunicorn.conf.py`** — env-driven production server config.

## Endpoint contract

### `POST /api/get_data`

Input — **one of**:

| Input | How | Use case |
|---|---|---|
| Single coordinate | `?lat=<float>&lng=<float>` query params | Real-time, one location |
| Bulk | multipart `file=` (CSV/XLS/XLSX) | Many locations in one call |

If neither (or an unreadable file) is supplied, returns **400** with a JSON
`detail` message. Missing `lat`/`lng` columns in an uploaded file → **400**.

Output — **200** `application/zip`. `Content-Disposition` carries a unique
filename: `{ZIP_NAME_PREFIX}_{UTC-YYYYMMDDHHMMSS}_{8-hex}.zip`. The unique id
lets the caller route or store each result distinctly.

ZIP layout — one numbered folder per location (folders are 1-indexed):

```
1/map.png        1/street.jpg   1/360.html
2/map.png        2/street.jpg   2/360.html
```

`street.jpg` is omitted for a location when Google has no Street View imagery
there.

### `GET /health`

Returns `{"status": "ok"}` for load-balancer / orchestration liveness checks.

## Processing pipeline (`maps2.process_dataframe`)

1. **Normalize columns** — map flexible aliases to canonical `lat`/`lng`
   (`latitude`, `long`, `longitude`; case-insensitive). Raises `ValueError` if a
   required column is absent (surfaced by the API as a 400).
2. For each row, concurrently (`ThreadPoolExecutor`, up to 10 workers):
   - **Reverse geocode** → formatted address + `place_id`.
   - **Place Details** for that `place_id` → name, types, business status.
   - **Static map** image (`map.png`).
   - **Street View** image (`street.jpg`) when available.
   - **360° viewer** (`360.html`) — a small page embedding the Maps JavaScript
     `StreetViewPanorama`.
   - On a geocode/details failure, that row is recorded as an error and skipped
     (other rows are unaffected).
3. Returns `(result_rows, file_dict)`. The API uses `file_dict` to build the
   ZIP. (The `result_rows` metadata — addresses, place names, types — is
   computed but not currently returned; the ZIP contents are unchanged from the
   original tool by design.)

Because work runs under `as_completed`, rows may finish out of order, but each
location's files are written to its own numbered folder, so correlation is
preserved inside the ZIP.

## Google Maps APIs used

| Call | Endpoint | Output |
|---|---|---|
| Reverse geocode | `/maps/api/geocode/json` | address, `place_id` |
| Place details | `/maps/api/place/details/json` | name, types, business status |
| Static map | `/maps/api/staticmap` | `map.png` (640×400, zoom 17, red marker) |
| Street View | `/maps/api/streetview` | `street.jpg` (640×400) |
| 360° viewer | Maps JavaScript API (in `360.html`) | client-rendered panorama |

The key(s) required: **Geocoding API, Places API, Maps Static API, Street View
Static API**, and **Maps JavaScript API** if `360.html` is retained.

## Configuration

All configuration is environment-based (loaded from `.env`). See the table in
[README.md](README.md#configuration-env). Key points:

- `GOOGLE_MAPS_API_KEY` (required) is the server-side key used for the
  geocode/places/static/streetview HTTP calls.
- `GOOGLE_MAPS_BROWSER_KEY` (optional) is embedded into `360.html`. It falls
  back to `GOOGLE_MAPS_API_KEY` if unset.

## Deployment

Containerized with `Dockerfile` (python:3.12-slim) and run via
`docker compose up -d --build`. Gunicorn (config in `gunicorn.conf.py`) manages
Uvicorn workers and binds `0.0.0.0:8000` inside the container; the host port is
mapped via `HOST_PORT`. Logs stream to stdout/stderr (`docker compose logs`).

## Security considerations

- **API key in `360.html`** — the 360° page embeds a Maps JS key in plaintext;
  anyone who opens a downloaded `360.html` can read it. Mitigate by setting
  `GOOGLE_MAPS_BROWSER_KEY` to a separate, **HTTP-referrer-restricted** key so
  the server key never leaves the host.
- **No built-in auth or rate limiting** — by design. The service is intended for
  an internal network behind a reverse proxy that enforces access control and
  throttling. Each request triggers several **billed** Google API calls.
- **CORS is fully open** (`allow_origins=["*"]`) so the service is reachable from
  the consumer's systems; restrict at the proxy if a tighter policy is needed.
- **Input validation** is limited to file extension and coordinate parsing.
  Consider adding an upload size / row cap if untrusted callers are possible.

## Quick verification

```bash
# syntax check
python -m compileall main.py maps2.py gunicorn.conf.py

# run locally and open Swagger
uvicorn main:app --reload   # http://127.0.0.1:8000/docs
```
