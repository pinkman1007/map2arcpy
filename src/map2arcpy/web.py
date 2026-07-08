"""
Web-aware generation (opt-in via ``--web``) — still zero dependencies.

With ``--web``, a natural-language description can lean on three public,
key-free services, all called with plain stdlib ``urllib``:

* **Nominatim** (OpenStreetMap) — geocode a place name to a bounding box,
  which becomes the map extent and picks the correct UTM EPSG automatically.
* **Overpass API** (OpenStreetMap) — download real features ("hospitals
  from OSM in Visakhapatnam") as a GeoJSON file saved next to the generated
  script; the script converts and symbolises it.
* **ArcGIS Online search** — "find a flood layer online" discovers public
  feature services and adds the best match as a service layer, with the
  runners-up recorded in notes.

Design rules:
* OFFLINE BY DEFAULT — nothing here runs unless the caller passes
  ``web=True``; the core stays usable on locked-down machines.
* Deterministic wiring, honest failures — a dead service or empty result
  becomes a spec note, never a crash or a silent guess.
* All HTTP goes through ``_fetch_json`` so tests can inject a fake and CI
  never touches the network.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .spec import MapSpec, Layer, Renderer

USER_AGENT = "map2arcpy/0.2 (+https://github.com/pinkman1007/map2arcpy)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
AGOL_SEARCH_URL = "https://www.arcgis.com/sharing/rest/search"
TIMEOUT = 30

#: NL keyword -> Overpass tag filter
OSM_FEATURES = {
    "hospitals": '["amenity"="hospital"]',
    "clinics": '["amenity"="clinic"]',
    "pharmacies": '["amenity"="pharmacy"]',
    "schools": '["amenity"="school"]',
    "colleges": '["amenity"="college"]',
    "universities": '["amenity"="university"]',
    "parks": '["leisure"="park"]',
    "playgrounds": '["leisure"="playground"]',
    "hotels": '["tourism"="hotel"]',
    "banks": '["amenity"="bank"]',
    "atms": '["amenity"="atm"]',
    "temples": '["amenity"="place_of_worship"]',
    "police stations": '["amenity"="police"]',
    "fire stations": '["amenity"="fire_station"]',
    "bus stops": '["highway"="bus_stop"]',
    "fuel stations": '["amenity"="fuel"]',
    "markets": '["amenity"="marketplace"]',
    "roads": '["highway"]',
    "buildings": '["building"]',
    "water bodies": '["natural"="water"]',
}

_AREA_TAGS = ("building", "leisure", "landuse", "natural", "amenity", "area")

_OSM_RE = re.compile(
    r"\b(%s)\s+(?:from|via|using)\s+(?:osm|openstreetmap)\b"
    % "|".join(re.escape(k) for k in OSM_FEATURES), re.I)
_PLACE_RE = re.compile(
    r"\b(?:in|around|for|near)\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,3})")
_ONLINE_RE = re.compile(
    r"\b(?:find|search(?:\s+for)?|add)\s+(?:an?\s+)?([\w ]{3,40}?)\s+"
    r"(?:layer|service|data)\s+online\b", re.I)


# ---------------------------------------------------------------------------
# transport (tests monkeypatch this)
# ---------------------------------------------------------------------------
def _fetch_json(url: str, params: Dict[str, str]) -> Any:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + q, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# building blocks (pure logic over the transport)
# ---------------------------------------------------------------------------
def geocode(place: str) -> Optional[Dict[str, Any]]:
    """Place name -> {name, lat, lon, bbox:[xmin,ymin,xmax,ymax] in WGS84}."""
    rows = _fetch_json(NOMINATIM_URL, {"q": place, "format": "json", "limit": "1"})
    if not rows:
        return None
    r = rows[0]
    s, n, w, e = (float(v) for v in r["boundingbox"])       # lat_s, lat_n, lon_w, lon_e
    return {"name": r.get("display_name", place),
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "bbox": [w, s, e, n]}


def utm_epsg(lat: float, lon: float) -> int:
    """WGS84 UTM zone EPSG for a point (326xx north / 327xx south)."""
    zone = int((lon + 180) // 6) + 1
    zone = min(60, max(1, zone))
    return (32600 if lat >= 0 else 32700) + zone


def overpass_geojson(feature_key: str, bbox: List[float]) -> Dict[str, Any]:
    """Download OSM features in bbox and return a GeoJSON FeatureCollection."""
    tag = OSM_FEATURES[feature_key]
    w, s, e, n = bbox
    bb = f"({s},{w},{n},{e})"
    query = f"[out:json][timeout:{TIMEOUT}];(node{tag}{bb};way{tag}{bb};);out geom;"
    doc = _fetch_json(OVERPASS_URL, {"data": query})
    feats = []
    for el in doc.get("elements", []):
        geom = _osm_geometry(el)
        if geom:
            props = dict(el.get("tags") or {})
            props["osm_id"] = el.get("id")
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def _osm_geometry(el: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if el.get("type") == "node":
        return {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
    if el.get("type") == "way" and el.get("geometry"):
        coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
        if len(coords) < 2:
            return None
        closed = coords[0] == coords[-1] and len(coords) >= 4
        tags = el.get("tags") or {}
        is_area = closed and (any(t in tags for t in _AREA_TAGS)
                              or tags.get("area") == "yes")
        if is_area:
            return {"type": "Polygon", "coordinates": [coords]}
        return {"type": "LineString", "coordinates": coords}
    return None


def agol_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Public ArcGIS Online feature services matching a query."""
    doc = _fetch_json(AGOL_SEARCH_URL, {
        "q": f'{query} type:"Feature Service"',
        "f": "json", "num": str(max_results)})
    out = []
    for item in doc.get("results", []):
        if item.get("url"):
            out.append({"title": item.get("title", "layer"),
                        "url": item["url"].rstrip("/") + "/0",
                        "owner": item.get("owner", "?")})
    return out


# ---------------------------------------------------------------------------
# the enrichment pass
# ---------------------------------------------------------------------------
def enrich(spec: MapSpec, text: str, out_dir: str = ".") -> MapSpec:
    """Run the web pass over an NL-parsed spec. Every step degrades to a
    note on failure; the spec always comes back generable."""
    import os

    # 1. place -> extent + projected CRS
    bbox = None
    m = _PLACE_RE.search(text)
    if m:
        place = m.group(1).strip()
        try:
            g = geocode(place)
        except Exception as e:                                # noqa: BLE001
            g = None
            spec.notes.append(f"web: geocoding '{place}' failed ({e}) — "
                              "set the extent manually")
        else:
            if not g:
                spec.notes.append(f"web: no geocoding result for '{place}'")
        if g:
            bbox = g["bbox"]
            spec.extent = bbox
            spec.notes.append(f"web: extent set from Nominatim match '{g['name']}'")
            if spec.crs_epsg == 4326:                          # only replace the default
                spec.crs_epsg = utm_epsg(g["lat"], g["lon"])
                spec.notes.append(f"web: projected CRS auto-selected — "
                                  f"EPSG:{spec.crs_epsg} (UTM) for this location")

    # 2. "<features> from osm" -> download GeoJSON next to the script
    for m in _OSM_RE.finditer(text):
        key = m.group(1).lower()
        if not bbox:
            spec.notes.append(f"web: '{key} from OSM' needs a place "
                              "(add e.g. 'in Visakhapatnam') — skipped")
            continue
        try:
            fc = overpass_geojson(key, bbox)
        except Exception as e:                                # noqa: BLE001
            spec.notes.append(f"web: Overpass download for '{key}' failed ({e})")
            continue
        if not fc["features"]:
            spec.notes.append(f"web: OSM returned no '{key}' in this extent")
            continue
        fname = re.sub(r"\W+", "_", key) + "_osm.geojson"
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f)
        lyr = _profile_geojson_layer(fc, path)
        # avoid clobbering an existing name
        if any(l.name == lyr.name for l in spec.layers):
            lyr.name += "_osm"
        spec.layers.append(lyr)
        spec.notes.append(f"web: {len(fc['features'])} OSM '{key}' features "
                          f"saved to {fname} (ODbL attribution: "
                          f"(c) OpenStreetMap contributors)")

    # 3. "find X layer online" -> ArcGIS Online service layer
    for m in _ONLINE_RE.finditer(text):
        theme = m.group(1).strip()
        try:
            hits = agol_search(theme)
        except Exception as e:                                # noqa: BLE001
            spec.notes.append(f"web: ArcGIS Online search for '{theme}' failed ({e})")
            continue
        if not hits:
            spec.notes.append(f"web: no public ArcGIS Online layer found for '{theme}'")
            continue
        best = hits[0]
        spec.layers.append(Layer(
            name=re.sub(r"\W+", "_", best["title"]).strip("_") or "online_layer",
            kind="service", source=best["url"],
            renderer=Renderer(type="simple"),
            notes=[f"from ArcGIS Online search '{theme}' (owner: {best['owner']})"]))
        if len(hits) > 1:
            alts = "; ".join(f"{h['title']} <{h['url']}>" for h in hits[1:])
            spec.notes.append(f"web: other candidates for '{theme}': {alts}")

    return spec


def _profile_geojson_layer(fc: Dict[str, Any], path: str) -> Layer:
    """Reuse the data parser's profiling so OSM layers get the same
    field-driven symbology suggestions as user-supplied GeoJSON."""
    from .parsers import data as data_parser
    sub = data_parser._geojson(fc, path)
    lyr = sub.layers[0]
    lyr.source = path
    return lyr
