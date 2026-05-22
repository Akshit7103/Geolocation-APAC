from __future__ import annotations
from typing import Tuple, Optional
from io import BytesIO
import io
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed


API_KEY = None  # Server-side key, set externally by main.py
# Browser-side key embedded in the generated 360.html. Falls back to API_KEY
# when unset so output is unchanged out of the box; set it to a referrer-
# restricted key so the powerful server key never lands in downloadable files.
BROWSER_API_KEY = None

# Default values
STATIC_SIZE    = "640x400"
STATIC_ZOOM    = 17
STREET_SIZE    = "640x400"
STREET_HEADING = 0
STREET_PITCH   = 0

# ── Helper functions ──────────────────────────────────────────────────
def _get_json(url: str, params: dict, timeout: int = 10) -> dict:
    r = requests.get(url, params=params, timeout=timeout)
    try:
        return r.json()
    except ValueError as e:
        raise RuntimeError(f"Non-JSON response ({r.status_code})") from e

def reverse_geocode(lat: float, lng: float) -> Tuple[str, str]:
    data = _get_json(
        "https://maps.googleapis.com/maps/api/geocode/json",
        {"latlng": f"{lat},{lng}", "key": API_KEY},
    )
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"Reverse geocode failed: {data.get('status')}")
    top = data["results"][0]
    return top["formatted_address"], top["place_id"]

def place_details(place_id: str) -> dict:
    data = _get_json(
        "https://maps.googleapis.com/maps/api/place/details/json",
        {
            "place_id": place_id,
            "fields": "name,types,business_status,formatted_address",
            "key": API_KEY
        },
    )
    if data.get("status") != "OK":
        raise RuntimeError(f"Place details failed: {data.get('status')}")
    return data["result"]

# ── In-memory file generators ─────────────────────────────────────────
def get_static_map(lat: float, lng: float) -> BytesIO:
    r = requests.get(
        "https://maps.googleapis.com/maps/api/staticmap",
        params={
            "center": f"{lat},{lng}",
            "zoom": STATIC_ZOOM,
            "size": STATIC_SIZE,
            "maptype": "roadmap",
            "markers": f"color:red|{lat},{lng}",
            "key": API_KEY,
        },
        timeout=10,
    )
    r.raise_for_status()
    return io.BytesIO(r.content)

def get_street_view(lat: float, lng: float) -> Optional[BytesIO]:
    r = requests.get(
        "https://maps.googleapis.com/maps/api/streetview",
        params={
            "size": STREET_SIZE,
            "location": f"{lat},{lng}",
            "heading": STREET_HEADING,
            "pitch": STREET_PITCH,
            "key": API_KEY,
        },
        timeout=10,
    )
    if r.status_code == 200 and r.content:
        return io.BytesIO(r.content)
    return None

def get_360_html(lat: float, lng: float) -> BytesIO:
    key = BROWSER_API_KEY or API_KEY
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>Street View 360</title>
<style>html,body,#pano{{height:100%;margin:0}}</style>
<script src="https://maps.googleapis.com/maps/api/js?key={key}"></script>
<script>
function init(){{
  const pos={{lat:{lat},lng:{lng}}};
  new google.maps.StreetViewPanorama(
    document.getElementById('pano'),
    {{position:pos,pov:{{heading:0,pitch:0}},zoom:1}});
}}
window.onload=init;
</script></head><body><div id="pano"></div></body></html>"""
    return io.BytesIO(html.encode("utf-8"))

# ── DataFrame processing ──────────────────────────────────────────────
def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {c.lower(): c for c in df.columns}
    for want, options in {"lat": ["lat", "latitude"], "lng": ["lng", "long", "longitude"]}.items():
        for opt in options:
            if opt in col_map:
                df = df.rename(columns={col_map[opt]: want})
                break
        else:
            raise ValueError(f"Missing column: {want}")
    return df[["lat", "lng"]]

def process_dataframe(df: pd.DataFrame, progress_callback=None) -> Tuple[list, dict]:
    df = _normalize_cols(df)
    results = []
    file_dict = {}
    total = len(df)

    def process_one(idx_row):
        idx, row = idx_row
        lat, lng = row
        folder = str(idx)
        files = {}
        try:
            address, place_id = reverse_geocode(lat, lng)
            details = place_details(place_id)
        except Exception as e:
            return idx, {
                "lat": lat, "lng": lng, "address": "", "status": "error", "note": str(e),
                "static_map": "", "street_img": "", "street360": ""
            }, folder, files
        # Generate files
        map_io = get_static_map(lat, lng)
        street_io = get_street_view(lat, lng)
        html_io = get_360_html(lat, lng)
        map_name = "map.png"
        street_name = "street.jpg" if street_io else ""
        html_name = "360.html"
        files[map_name] = map_io
        if street_io:
            files[street_name] = street_io
        files[html_name] = html_io
        result = {
            "lat": lat,
            "lng": lng,
            "address": details.get("formatted_address", address),
            "place_name": details.get("name", ""),
            "business_status": details.get("business_status", ""),
            "types": "|".join(details.get("types", [])),
            "static_map": f"{folder}/{map_name}",
            "street_img": f"{folder}/{street_name}" if street_io else "",
            "street360": f"{folder}/{html_name}",
            "status": "ok"
        }
        return idx, result, folder, files

    idx_rows = list(enumerate(df.itertuples(index=False), 1))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_one, idx_row): idx_row[0] for idx_row in idx_rows}
        for i, future in enumerate(as_completed(futures), 1):
            idx, result, folder, files = future.result()
            if progress_callback:
                progress_callback(i, total, f"Processing location {i}/{total}...")
            results.append(result)
            file_dict[folder] = files
    return results, file_dict
