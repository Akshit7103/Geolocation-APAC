"""Gunicorn configuration for the ProPosition API.

Uvicorn's own server is single-process and dev-only; Gunicorn manages multiple
Uvicorn workers for production. All knobs are env-driven so the client can tune
them via .env without touching code.
"""
import multiprocessing
import os

# Bind inside the container; the host port is mapped in docker-compose.yaml.
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# ASGI worker so FastAPI runs under Gunicorn's process manager.
worker_class = "uvicorn.workers.UvicornWorker"

# Default to the common (2 * cores + 1) heuristic; override with WORKERS.
workers = int(os.getenv("WORKERS", multiprocessing.cpu_count() * 2 + 1))

# Some coordinates can take a while across several Google API calls.
timeout = int(os.getenv("TIMEOUT", "120"))

# Log to stdout/stderr so `docker compose logs` shows everything.
accesslog = "-"
errorlog = "-"
