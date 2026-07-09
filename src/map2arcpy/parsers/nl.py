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
             ".kml", ".kmz", ".csv", ".lyrx", ".nc", ".asc", ".gpx", ".dxf",
             ".hgt", ".jp2", ".dem", ".flt", ".bil")

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
    r"(?:\s*(?:map\s+)?(?:of|by|on)?\s+([A-Za-z_][\w ]{0,40}?))?(?=[,.;]|\s+(?:using|with|in|on|from|over|against)\b|$)",
    re.I,
)
_UNIQ_RE = re.compile(
    r"\b(?:unique\s+values?|categori[sz]ed?|categorical)\s*(?:map\s+)?(?:of|by|on)\s+([A-Za-z_][\w]{0,40})",
    re.I,
)
_LABEL_RE = re.compile(r"\blabel(?:led|ed)?\s+(?:by|with|using)\s+([A-Za-z_][\w]{0,40})", re.I)
# where-clause: quoted forms win (commas/quotes inside SQL survive), then bare
_WHERE_DQ_RE = re.compile(r"\b(?:select|filter)\s+(?:features\s+)?where\s+\"(.+)\"", re.I)
_WHERE_SQ_RE = re.compile(r"\b(?:select|filter)\s+(?:features\s+)?where\s+'(.+)'", re.I)
_WHERE_RE = re.compile(r"\b(?:select|filter)\s+(?:features\s+)?where\s+(.+?)(?:[,.;]|$)", re.I)
_DISSOLVE_RE = re.compile(r"\bdissolve[d]?\s+(?:by|on)\s+([A-Za-z_][\w]{0,40})", re.I)
_BUFFER_RE = re.compile(r"\bbuffer(?:ed|ing)?\b", re.I)
_CLIP_RE = re.compile(r"\bclip(?:ped|ping)?\s+(?:it\s+|them\s+)?to\s+", re.I)
_ERASE_RE = re.compile(r"\berase\s+(.+?)\s+from\s+(.+?)(?:[,.;]|$)", re.I)
_NO_SURROUND_RE = r"\b(?:no|without(?:\s+(?:a|the|any))?)\s+%s\b"

# ---- raster analysis (Spatial Analyst) --------------------------------------
_STATS_WORDS = {"average": "MEAN", "mean": "MEAN", "sum": "SUM", "total": "SUM",
                "maximum": "MAXIMUM", "max": "MAXIMUM",
                "minimum": "MINIMUM", "min": "MINIMUM"}
_CELLSTAT_RE = re.compile(
    r"\b(?:(decadal|annual|monthly|period)\s+)?"
    r"(average|mean|sum|total|maximum|max|minimum|min)\s+of\s+"
    r"""(?:"([^"]+)"|'([^']+)'|([\w:/\\.\-*?]+))""", re.I)
_SLOPE_RE = re.compile(r"\bslope\b", re.I)
_HILLSHADE_RE = re.compile(r"\bhillshade\b", re.I)
_EUCDIST_RE = re.compile(r"\b(?:euclidean\s+)?distance\s+(?:to|from)\s+", re.I)
_ZONAL_RE = re.compile(r"\bzonal\s+stat(?:istic)?s?\s+of\s+"
                       r"""(?:"([^"]+)"|(\S+))\s+(?:by|per|across)\s+"""
                       r"""(?:"([^"]+)"|(\S+))""", re.I)
_RASTER_EXTS = (".tif", ".tiff", ".img", ".asc", ".hgt", ".jp2", ".dem",
                ".flt", ".bil", ".nc")


def _is_rasterish(tok: str) -> bool:
    low = tok.lower()
    return low.endswith(_RASTER_EXTS) or "*" in tok or "?" in tok


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

    # ---- operations (chained: each step consumes the previous output) ------
    first = next((l.name for l in spec.layers if l.kind != "basemap"), None)
    current = first or "INPUT"                 # head of the processing chain
    diss = _DISSOLVE_RE.search(t)
    if _BUFFER_RE.search(low):
        dist = _distance(low) or "500 Meters"
        if not first:
            spec.notes.append("buffer requested but no data source found — "
                              "set the input path in CONFIG")
        # bare "dissolve" folds into the buffer; "dissolve by FIELD" stays
        # a separate step so the field is honoured
        fold = "ALL" if ("dissolve" in low and not diss) else "NONE"
        spec.operations.append(Operation(
            tool="buffer", inputs=[current], output="buffered",
            params={"distance": dist, "dissolve": fold}))
        current = "buffered"
    if diss:
        spec.operations.append(Operation(tool="dissolve", inputs=[current],
                                         output="dissolved",
                                         params={"field": diss.group(1)}))
        current = "dissolved"
    m = _CLIP_RE.search(t)
    if m:
        clip_to = _first_path_after(t, m.end()) or (paths[1] if len(paths) > 1 else None)
        if clip_to:
            spec.operations.append(Operation(tool="clip", output="clipped",
                                             inputs=[current, _basename(clip_to)]))
            current = "clipped"
        else:
            spec.notes.append("clip requested but the clip boundary could not be "
                              "identified — add it to CONFIG['sources']")
    m = _ERASE_RE.search(t)
    if m:
        erase_feats = _first_path_after(t, m.start(1) - 1)
        base = _first_path_after(t, m.start(2) - 1)
        if erase_feats and base:               # arcpy: Erase(in_features, erase_features)
            spec.operations.append(Operation(tool="erase", output="erased",
                                             inputs=[_basename(base), _basename(erase_feats)]))
            current = "erased"
    if re.search(r"\bintersect", low) and len(paths) >= 2:
        spec.operations.append(Operation(tool="intersect", output="intersected",
                                         inputs=[_basename(paths[0]), _basename(paths[1])]))
        current = "intersected"
    if re.search(r"\b(?:union|merge)\b", low) and len(paths) >= 2:
        tool = "union" if "union" in low else "merge"
        spec.operations.append(Operation(tool=tool, output=f"{tool}ed",
                                         inputs=[_basename(p) for p in paths]))
        current = f"{tool}ed"
    if re.search(r"\bspatial(?:ly)?\s+join", low) and len(paths) >= 2:
        spec.operations.append(Operation(
            tool="spatial_join", output="joined",
            inputs=[_basename(paths[0]), _basename(paths[1])]))
        current = "joined"
    m = _WHERE_DQ_RE.search(t) or _WHERE_SQ_RE.search(t) or _WHERE_RE.search(t)
    if m:
        spec.operations.append(Operation(tool="select", inputs=[current],
                                         output="selected",
                                         params={"where": m.group(1).strip()}))

    # ---- raster analysis (Spatial Analyst) ---------------------------------
    m = _CELLSTAT_RE.search(t)
    if m:
        period = (m.group(1) or "").lower()
        stat = _STATS_WORDS[m.group(2).lower()]
        target = next(g for g in m.groups()[2:] if g)
        if _is_rasterish(target) or os.path.isdir(target):
            out_name = ((period + "_") if period else "") + \
                       ("average" if stat == "MEAN" else stat.lower())
            params = {"stat": stat}
            if "*" in target or "?" in target or os.path.isdir(target):
                params["pattern"] = target      # expanded at run time
            spec.operations.append(Operation(
                tool="cell_statistics", inputs=[target],
                output=out_name, params=params))
            current = out_name
    if _SLOPE_RE.search(low) or _HILLSHADE_RE.search(low):
        dem = next((l.name for l in spec.layers if l.kind == "raster"), None)
        if dem is None:
            spec.notes.append("slope/hillshade requested but no raster (DEM) "
                              "found in the description — name one, e.g. "
                              "'slope from dem.tif'")
        else:
            if _SLOPE_RE.search(low):
                spec.operations.append(Operation(tool="slope", inputs=[dem],
                                                 output="slope_surface"))
                current = "slope_surface"
            if _HILLSHADE_RE.search(low):
                spec.operations.append(Operation(tool="hillshade", inputs=[dem],
                                                 output="hillshade_surface"))
    m = _EUCDIST_RE.search(t)
    if m:
        near_path = _first_path_after(t, m.end())
        src_name = _basename(near_path) if near_path else current
        spec.operations.append(Operation(tool="euc_distance", inputs=[src_name],
                                         output="distance_surface"))
        current = "distance_surface"
    m = _ZONAL_RE.search(t)
    if m:
        val = next(g for g in (m.group(1), m.group(2)) if g)
        zones = next(g for g in (m.group(3), m.group(4)) if g)
        val_n = _basename(val) if _is_rasterish(val) or "." in val else val
        zon_n = _basename(zones) if "." in zones else zones
        spec.operations.append(Operation(
            tool="zonal_stats", inputs=[zon_n, val_n], output="zonal_table",
            params={"stat": "MEAN",
                    "zone_field": "TODO_ZONE_FIELD"}))

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
                                        ramp=RAMPS.get(ramp or DEFAULT_RAMP),
                                        ramp_name=(ramp or DEFAULT_RAMP))
        if not fld:
            final_layer.notes.append("graduated field not named in the description — "
                                     "replace 'VALUE' with the real field")
    else:
        col = _color(low)
        if col and final_layer is not None:
            final_layer.renderer = Renderer(type="simple", color=col)

    # a named ramp ("using blues") applies to raster stretch layers too, not
    # just graduated vectors — otherwise a "rainfall map ... using blues" got
    # a grey default raster
    if ramp:
        for l in spec.layers:
            if l.renderer.type == "stretch":
                l.renderer.ramp = list(RAMPS[ramp])
                l.renderer.ramp_name = ramp

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

    # analysis-chain methodology (which toolboxes/analyses make this product)
    from .. import chains
    chains.apply(spec, t)
    # thematic map-type conventions ("carbon map", "eco-sensitive zones", ...)
    from .. import archetypes
    archetypes.apply(spec, t)
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
    # phrase forms only — a bare "3857"/"4326" inside a where-clause or an
    # attribute value must NOT hijack the CRS (numeric codes go through
    # _EPSG_RE, which requires an 'epsg'/'srid' prefix)
    if "web mercator" in low or re.search(r"\bepsg[:\s]*3857\b", low):
        return 3857, None
    if "wgs84" in low or "wgs 84" in low or "wgs 1984" in low:
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
        # TITLE must not become a layer; a wildcard is a raster-SET for
        # cell_statistics, not a loadable layer
        if "*" in p or "?" in p:
            continue
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
    kind = "raster" if ext in (".tif", ".tiff", ".img", ".nc", ".asc", ".hgt",
                               ".jp2", ".dem", ".flt", ".bil") else "vector"
    lyr = Layer(name=_basename(p), source=p, kind=kind)
    if kind == "raster":
        lyr.renderer = Renderer(type="stretch")
    else:
        default = GEOMETRY_DEFAULTS.get("polygon")
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
    from ..spec import RASTER_OPS
    if spec.operations:
        last = next((o for o in reversed(spec.operations)
                     if o.output and o.tool != "zonal_stats"), None)
        if last:
            for l in spec.layers:
                if l.name == last.output:
                    return l
            if last.tool in RASTER_OPS:          # raster analysis output
                lyr = Layer(name=last.output, source="", kind="raster",
                            renderer=Renderer(type="stretch"))
            else:
                lyr = Layer(name=last.output, source="", kind="vector")
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
    lay.legend = not re.search(_NO_SURROUND_RE % "legend", low)
    lay.north_arrow = not re.search(_NO_SURROUND_RE % "north\\s+arrow", low)
    lay.scale_bar = not re.search(_NO_SURROUND_RE % "scale\\s*bar", low)
    return lay
