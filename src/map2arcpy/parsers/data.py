"""
Spatial data -> MapSpec.

* GeoJSON (.geojson / .json FeatureCollection) — pure json
* Shapefile (.shp) — pure-stdlib binary header + .dbf field sniffing + .prj
* ArcGIS web map JSON (exported webmap / item data with operationalLayers)

The parser inspects the data (geometry type, attribute fields) and proposes
sensible cartography: a numeric field -> graduated choropleth candidate; a
short-text field -> unique-value candidate; otherwise a clean single-symbol
layer. Suggestions are recorded as notes so the user can see the reasoning.
"""
from __future__ import annotations

import json
import os
import re
import struct
from typing import Any, Dict, List, Optional, Tuple

from ..spec import MapSpec, Layer, Renderer
from ..palettes import RAMPS, DEFAULT_RAMP, GEOMETRY_DEFAULTS, categorical_palette

_SHP_GEOM = {0: None, 1: "point", 3: "line", 5: "polygon", 8: "point",
             11: "point", 13: "line", 15: "polygon", 21: "point",
             23: "line", 25: "polygon", 28: "point", 31: "polygon"}


# ---------------------------------------------------------------------------
def parse(path: str) -> MapSpec:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".shp":
        return _shapefile(path)
    if ext == ".gpkg":
        return _geopackage(path)
    if ext in (".kml", ".kmz"):
        return _kml(path)
    if ext == ".gpx":
        return _gpx(path)
    if ext == ".csv":
        return _csv_xy(path)
    if ext in (".dxf", ".dwg", ".dgn"):
        return _cad(path)
    with open(path, "r", encoding="utf-8-sig") as f:
        doc = json.load(f)
    if isinstance(doc, dict) and "operationalLayers" in doc:
        return _webmap(doc, path)
    if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
        return _geojson(doc, path)
    if isinstance(doc, dict) and doc.get("type") in ("Feature", "Point", "LineString",
                                                     "Polygon", "MultiPoint",
                                                     "MultiLineString", "MultiPolygon"):
        return _geojson({"type": "FeatureCollection",
                         "features": [doc] if doc.get("type") == "Feature"
                         else [{"type": "Feature", "geometry": doc, "properties": {}}]}, path)
    raise ValueError(f"{path}: JSON is neither GeoJSON nor an ArcGIS web map")


# ---------------------------------------------------------------------------
def _stem(path: str) -> str:
    return re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_") or "layer"


def _geojson(doc: Dict[str, Any], path: str) -> MapSpec:
    spec = MapSpec(source_kind="geojson")
    feats = doc.get("features") or []
    geom = _majority_geometry(feats)
    lyr = Layer(name=_stem(path), source=path, kind="vector", geometry=geom)

    # GeoJSON is WGS84 by spec (RFC 7946); honour a legacy crs member if present
    spec.crs_epsg = 4326
    crs = doc.get("crs")
    if isinstance(crs, dict):
        m = re.search(r"EPSG[:]{1,2}(\d+)", str((crs.get("properties") or {}).get("name", "")))
        if m:
            spec.crs_epsg = int(m.group(1))
    if spec.crs_epsg == 4326:
        spec.notes.append("GeoJSON is geographic (EPSG:4326) — set 'epsg' in CONFIG to a "
                          "projected CRS if you need buffers/areas in metres")

    lyr.renderer, why = _suggest_renderer(feats, geom)
    if why:
        spec.notes.append(why)
    label = _suggest_label(feats)
    if label:
        lyr.label_field = label
    spec.layers.append(lyr)
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


def _majority_geometry(feats: List[Dict[str, Any]]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for f in feats[:500]:
        g = (f.get("geometry") or {}).get("type", "")
        base = {"Point": "point", "MultiPoint": "point", "LineString": "line",
                "MultiLineString": "line", "Polygon": "polygon",
                "MultiPolygon": "polygon"}.get(g)
        if base:
            counts[base] = counts.get(base, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _suggest_renderer(feats: List[Dict[str, Any]], geom: Optional[str]) -> Tuple[Renderer, Optional[str]]:
    """Numeric field -> graduated; low-cardinality text -> unique; else simple."""
    props = [f.get("properties") or {} for f in feats[:500]]
    if props:
        fields: Dict[str, set] = {}
        for p in props:
            for k, v in p.items():
                fields.setdefault(k, set()).add(type(v).__name__ if v is not None else "none")
        # numeric candidates (skip obvious identifiers)
        for k, kinds in fields.items():
            if kinds <= {"int", "float", "none"} and not re.search(r"\b(id|fid|code|objectid)\b", k, re.I):
                vals = [p.get(k) for p in props if isinstance(p.get(k), (int, float))]
                if len(set(vals)) > 5:
                    return (Renderer(type="graduated", field=k, ramp=RAMPS[DEFAULT_RAMP]),
                            f"numeric field '{k}' found — proposed a graduated (choropleth) renderer; "
                            f"swap the field in CONFIG if another attribute suits better")
        for k, kinds in fields.items():
            if kinds <= {"str", "none"}:
                vals = {p.get(k) for p in props if p.get(k)}
                if 2 <= len(vals) <= 12:
                    pal = categorical_palette(len(vals))
                    cmap = {str(v): c for v, c in zip(sorted(vals), pal)}
                    return (Renderer(type="unique", field=k, color_map=cmap),
                            f"categorical field '{k}' ({len(vals)} classes) — proposed unique-value symbology")
    col = GEOMETRY_DEFAULTS.get(geom or "polygon")
    return Renderer(type="simple", color=col), None


def _suggest_label(feats: List[Dict[str, Any]]) -> Optional[str]:
    for f in feats[:50]:
        for k in (f.get("properties") or {}):
            if re.fullmatch(r"(name|label|title|ward|zone)[a-z_]*", k, re.I):
                return k
    return None


# ---------------------------------------------------------------------------
def _shapefile(path: str) -> MapSpec:
    spec = MapSpec(source_kind="shapefile")
    with open(path, "rb") as f:
        header = f.read(100)
    if len(header) < 100 or struct.unpack(">i", header[0:4])[0] != 9994:
        raise ValueError(f"{path}: not a valid shapefile (bad magic)")
    shp_type = struct.unpack("<i", header[32:36])[0]
    geom = _SHP_GEOM.get(shp_type)
    bbox = struct.unpack("<4d", header[36:68])

    lyr = Layer(name=_stem(path), source=path, kind="vector", geometry=geom)

    # CRS from .prj sidecar
    prj = os.path.splitext(path)[0] + ".prj"
    epsg = _epsg_from_prj(prj)
    if epsg:
        spec.crs_epsg = epsg
    else:
        # heuristic: bbox within lon/lat bounds -> geographic
        gx = all(-180.01 <= v <= 180.01 for v in (bbox[0], bbox[2])) and \
             all(-90.01 <= v <= 90.01 for v in (bbox[1], bbox[3]))
        spec.crs_epsg = 4326 if gx else 3857
        spec.notes.append("no readable .prj beside the shapefile — CRS guessed as "
                          f"EPSG:{spec.crs_epsg}; verify and fix 'epsg' in CONFIG")

    # fields from .dbf sidecar
    fields = _dbf_fields(os.path.splitext(path)[0] + ".dbf")
    numeric = [n for n, t in fields if t in ("N", "F") and
               not re.search(r"\b(id|fid|code)\b", n, re.I)]
    text = [n for n, t in fields if t == "C"]
    if numeric:
        lyr.renderer = Renderer(type="graduated", field=numeric[0], ramp=RAMPS[DEFAULT_RAMP])
        spec.notes.append(f"numeric field '{numeric[0]}' found in the .dbf — proposed a "
                          "graduated renderer; change the field if needed")
    else:
        lyr.renderer = Renderer(type="simple", color=GEOMETRY_DEFAULTS.get(geom or "polygon"))
    for n in text:
        if re.fullmatch(r"(name|label|title|ward|zone)[a-z_0-9]*", n, re.I):
            lyr.label_field = n
            break

    spec.layers.append(lyr)
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


def _epsg_from_prj(prj_path: str) -> Optional[int]:
    if not os.path.exists(prj_path):
        return None
    try:
        with open(prj_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            wkt = f.read()
    except OSError:
        return None
    # last AUTHORITY entry in WKT1 is the outermost object's EPSG
    hits = re.findall(r'AUTHORITY\[\s*"EPSG"\s*,\s*"?(\d+)"?\s*\]', wkt, re.I)
    if hits:
        return int(hits[-1])
    m = re.search(r'ID\[\s*"EPSG"\s*,\s*(\d+)\s*\]\s*\]\s*$', wkt.strip())  # WKT2
    if m:
        return int(m.group(1))
    if re.search(r'GEOGCS\["GCS_WGS_1984"', wkt) and "PROJCS" not in wkt:
        return 4326
    return None


def _dbf_fields(dbf_path: str) -> List[Tuple[str, str]]:
    """(name, type) for each column — reads only the 32-byte descriptors."""
    if not os.path.exists(dbf_path):
        return []
    out: List[Tuple[str, str]] = []
    try:
        with open(dbf_path, "rb") as f:
            head = f.read(32)
            if len(head) < 32:
                return []
            header_len = struct.unpack("<H", head[8:10])[0]
            n = (header_len - 33) // 32
            for _ in range(max(0, n)):
                d = f.read(32)
                if len(d) < 32 or d[0:1] == b"\r":
                    break
                name = d[0:11].split(b"\x00")[0].decode("ascii", "ignore")
                ftype = d[11:12].decode("ascii", "ignore")
                if name:
                    out.append((name, ftype))
    except (OSError, struct.error):
        return []
    return out


# ---------------------------------------------------------------------------
def _webmap(doc: Dict[str, Any], path: str) -> MapSpec:
    spec = MapSpec(source_kind="webmap")
    sr = doc.get("spatialReference") or {}
    spec.crs_epsg = int(sr.get("latestWkid") or sr.get("wkid") or 3857)

    bm = (doc.get("baseMap") or {})
    if bm.get("title"):
        spec.layers.append(Layer(name="basemap", kind="basemap",
                                 source=_nearest_basemap(bm["title"])))
    for ol in doc.get("operationalLayers") or []:
        name = re.sub(r"\W+", "_", ol.get("title") or ol.get("id") or "layer").strip("_")
        url = ol.get("url") or ""
        if url:
            lyr = Layer(name=name, kind="service", source=url,
                        renderer=Renderer(type="simple"))
        else:
            lyr = Layer(name=name, kind="vector", source="TODO_SET_PATH",
                        notes=["web-map layer embeds its data (featureCollection) — "
                               "export it to a feature class and set the path"])
        # renderer from drawingInfo if present
        di = ((ol.get("layerDefinition") or {}).get("drawingInfo") or {})
        r = di.get("renderer") or {}
        if r.get("type") == "classBreaks":
            lyr.renderer = Renderer(
                type="graduated", field=r.get("field"),
                breaks=[c.get("classMaxValue") for c in r.get("classBreakInfos", [])
                        if c.get("classMaxValue") is not None],
                ramp=[_esri_hex(c.get("symbol")) for c in r.get("classBreakInfos", [])
                      if _esri_hex(c.get("symbol"))])
        elif r.get("type") == "uniqueValue":
            cmap = {str(u.get("value")): _esri_hex(u.get("symbol"))
                    for u in r.get("uniqueValueInfos", []) if _esri_hex(u.get("symbol"))}
            lyr.renderer = Renderer(type="unique", field=r.get("field1"), color_map=cmap)
        elif r.get("type") == "simple" and _esri_hex(r.get("symbol")):
            lyr.renderer = Renderer(type="simple", color=_esri_hex(r.get("symbol")))
        spec.layers.append(lyr)

    spec.layout.title = (doc.get("title") or _stem(path)).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    spec.notes.append("web-map layers are added by service URL; ArcGIS Pro must be "
                      "signed in to a portal that can reach them")
    return spec


def _nearest_basemap(title: str) -> str:
    t = title.lower()
    if "imagery" in t or "satellite" in t:
        return "Imagery"
    if "dark" in t:
        return "Dark Gray Canvas"
    if "light" in t or "gray" in t or "grey" in t:
        return "Light Gray Canvas"
    if "street" in t or "navigation" in t:
        return "Streets"
    if "topo" in t or "terrain" in t:
        return "Topographic"
    if "osm" in t or "openstreetmap" in t:
        return "OpenStreetMap"
    return "Topographic"


def _esri_hex(sym: Any) -> Optional[str]:
    if not isinstance(sym, dict):
        return None
    col = sym.get("color")
    if isinstance(col, (list, tuple)) and len(col) >= 3:
        return "#%02X%02X%02X" % tuple(int(v) for v in col[:3])
    return None


# ===========================================================================
# additional vector / tabular formats (pure stdlib)
# ===========================================================================
def _geopackage(path: str) -> MapSpec:
    """GeoPackage: a SQLite file — layer catalogue read with stdlib sqlite3."""
    import sqlite3
    spec = MapSpec(source_kind="geopackage")
    try:
        con = sqlite3.connect(path)
        rows = con.execute(
            "SELECT c.table_name, c.data_type, c.srs_id,"
            " (SELECT geometry_type_name FROM gpkg_geometry_columns g"
            "  WHERE g.table_name = c.table_name)"
            " FROM gpkg_contents c").fetchall()
    except sqlite3.Error as e:
        raise ValueError(f"{path}: not a readable GeoPackage ({e})") from e
    geom_map = {"POINT": "point", "MULTIPOINT": "point",
                "LINESTRING": "line", "MULTILINESTRING": "line",
                "POLYGON": "polygon", "MULTIPOLYGON": "polygon",
                "GEOMETRY": None}
    srs_ids = []
    for table, data_type, srs_id, gtype in rows:
        src = f"{path}/main.{table}"                 # ArcGIS gpkg addressing
        if data_type == "features":
            geom = geom_map.get((gtype or "").upper())
            lyr = Layer(name=_stem(table), source=src, kind="vector", geometry=geom)
            lyr.renderer = Renderer(type="simple",
                                    color=GEOMETRY_DEFAULTS.get(geom or "polygon"))
            # field profiling for symbology suggestion
            try:
                cols = con.execute(f'PRAGMA table_info("{table}")').fetchall()
                numeric = [c[1] for c in cols if str(c[2]).upper() in
                           ("REAL", "DOUBLE", "FLOAT", "INTEGER", "INT", "MEDIUMINT")
                           and not re.search(r"\b(id|fid|code)\b", c[1], re.I)]
                if numeric:
                    lyr.renderer = Renderer(type="graduated", field=numeric[0],
                                            ramp=RAMPS[DEFAULT_RAMP])
                    spec.notes.append(f"gpkg '{table}': numeric field "
                                      f"'{numeric[0]}' — proposed graduated renderer")
                for c in cols:
                    if re.fullmatch(r"(name|label|title|ward|zone)[a-z_0-9]*",
                                    c[1], re.I):
                        lyr.label_field = c[1]
                        break
            except sqlite3.Error:
                pass
            spec.layers.append(lyr)
            if srs_id:
                srs_ids.append(srs_id)
        elif data_type in ("tiles", "2d-gridded-coverage"):
            spec.layers.append(Layer(name=_stem(table), source=src, kind="raster",
                                     renderer=Renderer(type="stretch")))
    if srs_ids:
        try:
            row = con.execute(
                "SELECT organization, organization_coordsys_id FROM"
                " gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_ids[0],)).fetchone()
            if row and str(row[0]).upper() == "EPSG":
                spec.crs_epsg = int(row[1])
        except sqlite3.Error:
            pass
    con.close()
    if not spec.layers:
        spec.notes.append("GeoPackage has no feature or tile tables listed in "
                          "gpkg_contents")
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


def _kml(path: str) -> MapSpec:
    """KML/KMZ: placemark census via ElementTree; the generated script runs
    arcpy KMLToLayer (KML is always WGS84)."""
    import xml.etree.ElementTree as ET
    import zipfile as zf
    spec = MapSpec(source_kind="kml")
    spec.crs_epsg = 4326
    try:
        if path.lower().endswith(".kmz"):
            with zf.ZipFile(path) as z:
                kml_name = next((n for n in z.namelist()
                                 if n.lower().endswith(".kml")), None)
                if not kml_name:
                    raise ValueError("KMZ contains no .kml document")
                root = ET.fromstring(z.read(kml_name))
        else:
            root = ET.parse(path).getroot()
    except (ET.ParseError, zf.BadZipFile, OSError, ValueError) as e:
        raise ValueError(f"{path}: not a readable KML/KMZ ({e})") from e

    counts = {"Point": 0, "LineString": 0, "Polygon": 0}
    placemarks = 0
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "Placemark":
            placemarks += 1
        elif tag in counts:
            counts[tag] += 1
    major = max(counts, key=counts.get) if any(counts.values()) else None
    geom = {"Point": "point", "LineString": "line", "Polygon": "polygon"}.get(major)
    lyr = Layer(name=_stem(path), source=path, kind="vector", geometry=geom,
                renderer=Renderer(type="simple",
                                  color=GEOMETRY_DEFAULTS.get(geom or "point")))
    lyr.notes.append("KML converts via arcpy KMLToLayer at run time; the "
                     "resulting Placemarks feature classes are added")
    spec.layers.append(lyr)
    spec.notes.append(f"KML: {placemarks} placemarks "
                      f"({counts['Point']} points, {counts['LineString']} lines, "
                      f"{counts['Polygon']} polygons); KML is always EPSG:4326 — "
                      "set a projected 'epsg' in CONFIG for analysis")
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


def _gpx(path: str) -> MapSpec:
    """GPX tracks/waypoints; the generated script runs arcpy GPXtoFeatures."""
    import xml.etree.ElementTree as ET
    spec = MapSpec(source_kind="gpx")
    spec.crs_epsg = 4326
    wpt = trk = rte = 0
    try:
        for el in ET.parse(path).getroot().iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "wpt":
                wpt += 1
            elif tag == "trk":
                trk += 1
            elif tag == "rte":
                rte += 1
    except (ET.ParseError, OSError) as e:
        raise ValueError(f"{path}: not readable GPX ({e})") from e
    geom = "point" if wpt >= (trk + rte) else "line"
    lyr = Layer(name=_stem(path), source=path, kind="vector", geometry=geom,
                renderer=Renderer(type="simple",
                                  color=GEOMETRY_DEFAULTS.get(geom)))
    spec.layers.append(lyr)
    spec.notes.append(f"GPX: {wpt} waypoints, {trk} tracks, {rte} routes — "
                      "converted with arcpy GPXtoFeatures (WGS84)")
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


_X_NAMES = ("lon", "long", "longitude", "x", "easting", "lng")
_Y_NAMES = ("lat", "latitude", "y", "northing")


def _csv_xy(path: str) -> MapSpec:
    """CSV with coordinate columns -> point layer via XYTableToPoint."""
    import csv as csvmod
    spec = MapSpec(source_kind="csv")
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csvmod.reader(f)
            header = next(reader, [])
            sample = [row for _, row in zip(range(200), reader)]
    except (OSError, csvmod.Error) as e:
        raise ValueError(f"{path}: not readable CSV ({e})") from e
    cols = [h.strip() for h in header]
    low = [c.lower() for c in cols]
    x_field = next((cols[i] for i, c in enumerate(low) if c in _X_NAMES), None)
    y_field = next((cols[i] for i, c in enumerate(low) if c in _Y_NAMES), None)
    lyr = Layer(name=_stem(path), source=path, kind="vector", geometry="point",
                renderer=Renderer(type="simple",
                                  color=GEOMETRY_DEFAULTS.get("point")))
    if x_field and y_field:
        lyr.extra = {"x_field": x_field, "y_field": y_field}
        spec.notes.append(f"CSV: coordinates read from '{x_field}'/'{y_field}' "
                          f"({len(sample)} sampled rows); assumed WGS84 lon/lat — "
                          "fix CONFIG if they are projected coordinates")
        # numeric attribute -> graduated suggestion
        xi, yi = cols.index(x_field), cols.index(y_field)
        for i, c in enumerate(cols):
            if i in (xi, yi) or re.search(r"\b(id|code)\b", c, re.I):
                continue
            vals = [r[i] for r in sample if i < len(r) and r[i]]
            if vals and all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vals[:50]):
                lyr.renderer = Renderer(type="graduated", field=c,
                                        ramp=RAMPS[DEFAULT_RAMP])
                spec.notes.append(f"CSV: numeric column '{c}' — proposed "
                                  "graduated symbology")
                break
    else:
        lyr.extra = {"x_field": "TODO_X_FIELD", "y_field": "TODO_Y_FIELD"}
        spec.notes.append("CSV: no obvious coordinate columns found "
                          f"(headers: {', '.join(cols[:12])}) — set x/y field "
                          "names in the script's add_csv_xy call")
    spec.layers.append(lyr)
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec


def _cad(path: str) -> MapSpec:
    """CAD drawings (.dxf/.dwg/.dgn): arcpy reads them natively as CAD
    datasets; we add the drawing and note the sub-layer addressing."""
    spec = MapSpec(source_kind="cad")
    lyr = Layer(name=_stem(path), source=path, kind="vector",
                renderer=Renderer(type="simple",
                                  color=GEOMETRY_DEFAULTS.get("line")))
    lyr.notes.append("CAD dataset — ArcGIS Pro exposes Point/Polyline/Polygon/"
                     "Annotation sub-layers; re-point the source to e.g. "
                     f"{os.path.basename(path)}/Polyline for a single class")
    spec.layers.append(lyr)
    spec.notes.append("CAD files carry no CRS — set 'epsg' in CONFIG to the "
                      "drawing's real coordinate system (a world/projection "
                      "file beside the drawing helps Pro too)")
    spec.layout.title = _stem(path).replace("_", " ").title()
    spec.layout.export = _stem(path) + ".pdf"
    return spec
