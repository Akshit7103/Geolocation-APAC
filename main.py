"""ProPosition location-enrichment API.

A single synchronous endpoint that takes coordinates (either a single lat/lng
pair or an uploaded Excel/CSV of many), enriches each one via Google Maps, and
returns a ZIP of the generated assets. Stateless by design: nothing is stored
between requests, so it scales safely across multiple Gunicorn workers.
"""
import io
import os
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import maps2

# ── Configuration (from environment / .env) ───────────────────────────
load_dotenv()

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not API_KEY:
    raise RuntimeError("GOOGLE_MAPS_API_KEY not set.")

# Prefix for the returned ZIP filename: {prefix}_{timestamp}_{id}.zip
ZIP_NAME_PREFIX = os.getenv("ZIP_NAME_PREFIX", "proposition")

# Wire the keys into the processing module.
maps2.API_KEY = API_KEY
maps2.BROWSER_API_KEY = os.getenv("GOOGLE_MAPS_BROWSER_KEY") or API_KEY

ALLOWED_EXTENSIONS = ("xlsx", "xls", "csv")

app = FastAPI(
    title="ProPosition Location API",
    description=(
        "Enrich geographic coordinates with Google Maps data. POST a single "
        "lat/lng or an Excel/CSV of many, and receive a ZIP containing a static "
        "map, a Street View image, and a 360° viewer for each location."
    ),
    version="1.0.0",
)

# Open CORS: this runs on an internal network and the consumer integrates from
# their own systems. Rate limiting / access control are handled upstream.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_zip(file_dict: dict) -> io.BytesIO:
    """Pack the per-location generated files into an in-memory ZIP."""
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, files in file_dict.items():
            for name, content in files.items():
                zf.writestr(f"{folder}/{name}", content.getvalue())
    zip_io.seek(0)
    return zip_io


def _dataframe_from_upload(file: UploadFile) -> pd.DataFrame:
    """Read an uploaded Excel/CSV into a DataFrame, validating the extension."""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Use one of: {', '.join(ALLOWED_EXTENSIONS)}.",
        )
    contents = file.file.read()
    try:
        if ext == "csv":
            return pd.read_csv(io.BytesIO(contents))
        return pd.read_excel(io.BytesIO(contents))
    except Exception as e:  # malformed file, bad encoding, etc.
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")


@app.get("/health")
def health():
    """Liveness probe for load balancers / orchestration."""
    return {"status": "ok"}


@app.post("/api/get_data")
def get_data(
    file: Optional[UploadFile] = File(
        default=None, description="Excel/CSV with lat & lng columns (bulk)."
    ),
    lat: Optional[float] = Query(default=None, description="Latitude (single coordinate)."),
    lng: Optional[float] = Query(default=None, description="Longitude (single coordinate)."),
):
    """Enrich one or more coordinates and return a ZIP of generated assets.

    Provide **either** an uploaded `file` **or** the `lat` & `lng` query
    parameters. The response is `application/zip`; the filename carries a unique
    identifier so the caller can route/store each result distinctly.
    """
    if file is not None and file.filename:
        df = _dataframe_from_upload(file)
    elif lat is not None and lng is not None:
        df = pd.DataFrame([{"lat": lat, "lng": lng}])
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either an uploaded file or both 'lat' and 'lng' query parameters.",
        )

    try:
        _results, file_dict = maps2.process_dataframe(df)
    except ValueError as e:  # e.g. missing lat/lng columns in the file
        raise HTTPException(status_code=400, detail=str(e))

    zip_io = _build_zip(file_dict)

    unique_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    zip_name = f"{ZIP_NAME_PREFIX}_{unique_id}.zip"

    return StreamingResponse(
        zip_io,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
