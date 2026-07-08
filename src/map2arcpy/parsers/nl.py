"""
Natural-language map description -> MapSpec.

A deterministic, rule-based grammar (no LLM, no network, no API key).
It recognises the working vocabulary of ArcGIS map requests:

* data sources    — quoted paths, bare tokens ending in .shp/.geojson/.gdb/...
* operations      — buffer N <unit>, clip to X, dissolve by F, spatial join,
                    select where <expr>, intersect, erase, union, merge
* symbology       — "choropleth/graduated by FIELD", "unique values by FIELD",
                    named colours ("in red"), ramps ("using greens")
* CRS             — "EPSG:32644", "UTM zone 44N", "web mercator", "WGS84"
* layout          — "A3 landscape", "300 dpi", "export to PDF/PNG", a quoted
                    "titled '...'"
* basemap         — "on imagery", "over OSM", "dark gray basemap"

Anything it cannot resolve becomes an explicit TODO note carried into the
generated script — the tool never silently guesses.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from ..spec import MapSpec, Layer, Operation, Renderer, Layout
from ..palettes import NAMED_COLORS, RAMPS, DEFAULT_RAMP, BASEMAPS, GEOMETRY_DEFAULTS

_UNITS = {
    "m": "Meters", "meter": "Meters", "meters": "Meters", "metre": "Meters",
    "metres": "Meters", "km": "Kilometers", "kilometer": "Kilometers",
    "kilometers": "Kilometers", "kilometre": "Kilometers", "kilometres": "Kilometers",
    "mi": "Miles", "mile": "Miles", "miles": "Miles",
    "ft": "Feet", "foot": "Feet", "feet": "Feet",
}

_DATA_EXT = (".shp", ".geojson", ".json", ".gpkg", ".tif", ".tiff", ".img",
             ".kml", ".kmz", ".csv", ".lyrx")

_GDB_RE = re.compile(r"[\w:/\\.\- ]+\.gdb[/\\][\w]+", re.I)
_PATH_RE = re.compile(
    r"""(?:"([^"]+)"|'([^']+)'|(\b[\w:/\\.\-]+(?:%s)\b))""" % "|".join(re.escape(e) for e in _DATA_EXT),
    re.I,
)
_EPSG_RE = re.compile(r"\bepsg[:\s]*(\d{4,6})\b", re.I)
_UTM_RE = re.compile(r"\butm\s*zone\s*(\d{1,2})\s*([ns])\b", re.I)
_DIST_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(%s)\b" % "|".join(_UNITS), re.I)
_DPI_RE = re.compile(r"\b(\d{2,4})\s*dpi\b", re.I)
_TITLE_RE = re.compile(r"""\btitled?\s+["']([^"']+)["']""", re.I)
_GRAD_RE = re.compile(
    r"\b(?:choropleth|graduated|classified|colou?r(?:ed)?\s+by|shade[d]?\s+by|heat\s*map)\b"
    r"(?:\s*(?:map\s+)?(?:of|by|on)?\s+([A-Za-z_][\w ]{0,40}?))?(?=[,.;]|\s+(?:using|with|in|on)\b|$)",
    re.I,
)
_UNIQ_RE = re.compile(
    r"\b(?:unique\s+values?|categori[sz]ed?|categorical)\s*(?:map\s+)?(?:of|by|on)\s+([A-Za-z_][\w]{0,40})",
    re.I,
)
_LABEL_RE = re.compile(r"\blabel(?:led|ed)?\s+(?:by|with|using)\s+([A-Za-z_][\w]{0,40})", re.I)
_WHERE_RE = re.compile(r"\b(?:select|filter)\s+(?:features\s+)?where\s+(.+?)(?:[,.;]|$)", re.I)
_DISSOLVE_RE = re.compile(r"\bdissolve[d]?\s+(?:by|on)\s+([A-Za-z_][\w]{0,40})", re.I)
_BUFFER_RE = re.compile(r"\bbuffer(?:ed|ing)?\b", re.I)
_CLIP_RE = re.compile(r"\bclip(?:ped|ping)?\s+(?:it\s+|them\s+)?to\s+", re.I)


def parse(text: str, name_hint: str = "described map") -> MapSpec:
    spec = MapSpec(source_kind="natural-language")
    t = " ".join(text.split())
    low = t.lower()

    # ---- CRS -------------------------------------------------------------
    spec.crs_epsg, crs_note = _crs(low)
    if crs_note:
        spec.notes.append(crs_note)

    # ---- data sources -> layers -------------------------------------------
    paths = _paths(t)
    for p in paths:
        spec.layers.append(_layer_from_path(p))

    # ---- basemap -----------------------------------------------------------
    bm = _basemap(low)
    if bm:
        spec.layers.insert(0, Layer(name="basemap", source=bm, kind="basemap"))

    # ---- operations --------------------------------------------------------
    first = next((l.name for l in spec.layers if l.kind != "basemap"), None)
    if _BUFFER_RE.search(low):
        dist = _distance(low) or "500 Meters"
        target = first or "INPUT"
        if not first:
            spec.notes.append("buffer requested but no data source found — "
                              "set the input path in CONFIG")
        spec.operations.append(Operation(
            tool="buffer", inputs=[target], output="buffered",
            params={"distance": dist, "dissolve": "ALL" if "dissolve" in low else "NONE"}))
    m = _CLIP_RE.search(t)
    if m:
        clip_to = _first_path_after(t, m.end()) or (paths[1] if len(paths) > 1 else None)
        subject = "buffered" if any(o.tool == "buffer" for o in spec.operations) \
            else (first or "INPUT")
        if clip_to:
            spec.operations.append(Operation(tool="clip", output="clipped",
                                             inputs=[subject, _basename(clip_to)]))
        else:
            spec.notes.append("clip requested but the clip boundary could not be "
                              "identified — add it to CONFIG['sources']")
    m = _DISSOLVE_RE.search(t)
    if m and not _BUFFER_RE.search(low):
        spec.operations.append(Operation(tool="dissolve", inputs=[first or "INPUT"],
                                         output="dissolved", params={"field": m.group(1)}))
    if re.search(r"\bspatial(?:ly)?\s+join", low) and len(paths) >= 2:
        spec.operations.append(Operation(
            tool="spatial_join", output="joined",
            inputs=[_basename(paths[0]), _basename(paths[1])]))
    m = _WHERE_RE.search(t)
    if m:
        spec.operations.append(Operation(tool="select", inputs=[first or "INPUT"],
                                         output="selected", params={"where": m.group(1).strip()}))

    # ---- symbology on the "final" layer -------------------------------------
    final_layer = _final_layer(spec)
    g = _GRAD_RE.search(t)
    u = _UNIQ_RE.search(t)
    ramp = _ramp(low)
    if u and final_layer is not None:
        final_layer.renderer = Renderer(type="unique", field=u.group(1).strip())
        final_layer.notes.append("unique-value colours default per class — "
                                 "edit the mapping in the script if needed")
    elif g and final_layer is not None:
        fld = (g.group(1) or "").strip().split(" using")[0].strip() or None
        final_layer.renderer = Renderer(type="graduated", field=fld or "VALUE",
                                        ramp=RAMPS.get(ramp or DEFAULT_RAMP))
        if not fld:
            final_layer.notes.append("graduated field not named in the description — "
                                     "replace 'VALUE' with the real field")
    else:
        col = _color(low)
        if col and final_layer is not None:
            final_layer.renderer = Renderer(type="simple", color=col)

    lab = _LABEL_RE.search(t)
    if lab and final_layer is not None:
        final_layer.label_field = lab.group(1)

    # ---- layout --------------------------------------------------------------
    spec.layout = _layout(t, low, name_hint)

    if not spec.layers and not spec.operations:
        spec.notes.append("no data sources or operations recognised in the "
                          "description — the script is a scaffold; fill CONFIG")
        spec.layers.append(Layer(name="layer_1", source="TODO_SET_PATH.shp",
                                 kind="vector",
                                 notes=["source not found in description"]))
    return spec


# ---------------------------------------------------------------------------
def _crs(low: str) -> Tuple[int, Optional[str]]:
    m = _EPSG_RE.search(low)
    if m:
        return int(m.group(1)), None
    m = _UTM_RE.search(low)
    if m:
        zone, hemi = int(m.group(1)), m.group(2).lower()
        return (32600 + zone if hemi == "n" else 32700 + zone), None
    if "web mercator" in low or "3857" in low:
        return 3857, None
    if "wgs84" in low or "wgs 84" in low:
        return 4326, None
    return 4326, ("no CRS given — defaulting to EPSG:4326; set 'epsg' in CONFIG "
                  "to your projected CRS for correct buffers/areas")


def _looks_like_data(p: str) -> bool:
    return p.lower().endswith(_DATA_EXT) or ".gdb" in p.lower()


def _paths(t: str) -> List[str]:
    out = []
    for m in _PATH_RE.finditer(t):
        p = next(g for g in m.groups() if g)
        # quoted strings are only data if they look like data — a quoted
        # TITLE must not become a layer
        if _looks_like_data(p) and p not in out:
            out.append(p)
    for m in _GDB_RE.finditer(t):
        if m.group(0) not in out:
            out.append(m.group(0).strip())
    return out


def _first_path_after(t: str, pos: int) -> Optional[str]:
    for m in _PATH_RE.finditer(t, pos):
        p = next(g for g in m.groups() if g)
        if _looks_like_data(p):
            return p
    m = _GDB_RE.search(t, pos)
    return m.group(0).strip() if m else None


def _basename(p: str) -> str:
    stem = os.path.splitext(os.path.basename(p.replace("\\", "/")))[0]
    return re.sub(r"\W+", "_", stem) or "layer"


def _layer_from_path(p: str) -> Layer:
    ext = os.path.splitext(p)[1].lower()
    kind = "raster" if ext in (".tif", ".tiff", ".img") else "vector"
    lyr = Layer(name=_basename(p), source=p, kind=kind)
    default = GEOMETRY_DEFAULTS.get("raster" if kind == "raster" else "polygon")
    if default:
        lyr.renderer = Renderer(type="simple", color=default)
    return lyr


def _basemap(low: str) -> Optional[str]:
    for key, name in sorted(BASEMAPS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"\b(?:on|over|against|atop|basemap[:\s]+)?\s*%s\s+(?:basemap|imagery\b|background)" % re.escape(key), low) \
           or re.search(r"\b(?:on|over)\s+(?:an?\s+|the\s+)?%s\b" % re.escape(key), low):
            return name
    return None


def _distance(low: str) -> Optional[str]:
    m = _DIST_RE.search(low)
    if not m:
        return None
    val = m.group(1)
    unit = _UNITS[m.group(2).lower()]
    val = val[:-2] if val.endswith(".0") else val
    return f"{val} {unit}"


def _color(low: str) -> Optional[str]:
    for name in sorted(NAMED_COLORS, key=len, reverse=True):
        if re.search(r"\bin\s+%s\b" % re.escape(name), low) or \
           re.search(r"\b%s\s+(?:fill|colou?r|symbols?)\b" % re.escape(name), low):
            return NAMED_COLORS[name]
    return None


def _ramp(low: str) -> Optional[str]:
    for name in RAMPS:
        if re.search(r"\b(?:using|with|in)\s+(?:a\s+)?%s(?:\s+ramp|\s+scheme)?\b"
                     % re.escape(name.replace("_", "[ _-]")), low):
            return name
    return None


def _final_layer(spec: MapSpec) -> Optional[Layer]:
    """The layer symbology applies to: the last op output if any, else the
    last data layer. Creates a Layer entry for the op output if missing."""
    if spec.operations:
        out = next((o.output for o in reversed(spec.operations) if o.output), None)
        if out:
            for l in spec.layers:
                if l.name == out:
                    return l
            lyr = Layer(name=out, source="", kind="vector")
            spec.layers.append(lyr)
            return lyr
    for l in reversed(spec.layers):
        if l.kind != "basemap":
            return l
    return None


def _layout(t: str, low: str, name_hint: str) -> Layout:
    lay = Layout()
    m = _TITLE_RE.search(t)
    lay.title = m.group(1) if m else name_hint.replace("_", " ").title()
    page = "A4"
    if re.search(r"\ba3\b", low):
        page = "A3"
    elif "letter" in low:
        page = "Letter"
    orient = "L" if "landscape" in low else "P"
    lay.page = page + orient
    m = _DPI_RE.search(low)
    if m:
        lay.dpi = int(m.group(1))
    ext = ".png" if re.search(r"\b(?:png|image)\b", low) and "pdf" not in low else ".pdf"
    if re.search(r"\bjpe?g\b", low):
        ext = ".jpg"
    lay.export = re.sub(r"\W+", "_", lay.title.lower()).strip("_") + ext
    lay.legend = "no legend" not in low
    lay.north_arrow = "no north arrow" not in low
    lay.scale_bar = "no scale bar" not in low
    return lay
