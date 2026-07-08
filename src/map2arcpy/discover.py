"""
Discover — "what maps can I make from this data?"

Given a parsed MapSpec (from uploaded data), enumerate the concrete maps that
this data supports: choropleths for each numeric field, category maps for each
low-cardinality text field, point/heat maps for point layers, continuous
surfaces for rasters, a time-series + change map + behaviour archetype when
year-tagged rasters are present, and thematic archetype maps when field/layer
names hint at a theme (carbon, rainfall, flood, elevation…).

Each suggestion is ready to run: it carries a `depict` instruction (goes in
the input box) and optional `style`/`systems` so the dashboard can generate it
in one click. Suggestions that need an extension (Spatial Analyst) are flagged
and, if a Pro profile is present, filtered to what the machine actually has.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .spec import MapSpec

_ID_RE = re.compile(r"\b(id|fid|oid|objectid|code|uid|gid)\b", re.I)
_LABELISH = re.compile(r"(name|label|title|ward|zone|village|town|city|ulb)", re.I)

#: field/layer name hints -> thematic archetype depict phrasing + ramp
_THEME_HINTS = [
    (r"carbon|biomass|agb|co2c", "carbon storage map", "greens"),
    (r"emission|co2e|ghg", "emissions map", "reds"),
    (r"rain|precip|persiann|imd", "rainfall map", "blues"),
    (r"flood|inundat|water.?log", "flood map", "blues"),
    (r"ndvi|vegetation|greenness", "vegetation NDVI map", "red_yellow_green"),
    (r"dem|elev|srtm|terrain|slope|hgt", "terrain map", "terrain"),
    (r"lst|temperature|heat", "temperature map", "magma"),
    (r"lulc|landuse|land_use|land_cover", "LULC map", None),
    (r"population|popn|pop_dens|density|densit", "population density map", "oranges"),
    (r"hazard|risk|vulnerab", "hazard risk map", "reds"),
]


def suggest(spec: MapSpec, profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sa = _has_spatial_analyst(profile)

    vector = [l for l in spec.layers if l.kind == "vector" and l.source]
    rasters = [l for l in spec.layers if l.kind == "raster"]

    # ---- vector layers ----------------------------------------------------
    for l in vector:
        fields = l.extra.get("fields") or []
        numeric = [f["name"] for f in fields if f["type"] == "numeric"
                   and not _ID_RE.search(f["name"])]
        text = [f["name"] for f in fields if f["type"] == "text"]
        labelish = next((f["name"] for f in fields if _LABELISH.search(f["name"])), None)
        geom = l.geometry or "polygon"

        for nf in numeric[:8]:
            out.append(_s(f"Choropleth of {nf}",
                          f"graduated colours of '{nf}' across {l.name}",
                          f"choropleth of {nf}"
                          + (f", label by {labelish}" if labelish else ""),
                          why=f"numeric field '{nf}' in {l.name}"))
        for tf in text[:6]:
            # a pure name/identifier field is a label, not a category; but
            # ward/zone/class-type text fields are legitimate categories
            if not re.search(r"^(name|label|title)$|_name$|_label$", tf, re.I):
                out.append(_s(f"Categories by {tf}",
                              f"one colour per class of '{tf}'",
                              f"unique values by {tf}",
                              why=f"categorical field '{tf}' in {l.name}"))
        if geom == "point":
            out.append(_s(f"Point map — {l.name}",
                          "plot the points, sized markers",
                          f"map of {l.name}"
                          + (f" labeled with {labelish}" if labelish else ""),
                          why=f"{l.name} is point data"))
            out.append(_s(f"Service-area buffers — {l.name}",
                          "buffer rings around the points",
                          f"buffer {l.name} by 500 m",
                          why="points support proximity/service-area analysis"))
        elif geom == "polygon":
            out.append(_s(f"Boundary map — {l.name}",
                          "clean outline of the polygons",
                          f"map of {l.name}",
                          style={"transparency": 60, "outline": "#1F4E5F"},
                          why=f"{l.name} is polygon data"))
        elif geom == "line":
            out.append(_s(f"Network map — {l.name}",
                          "draw the lines",
                          f"map of {l.name}",
                          why=f"{l.name} is line data"))

    # ---- raster layers ----------------------------------------------------
    years = _years(rasters)
    if len(years) >= 3:
        y0, y1 = years[0], years[-1]
        out.append(_s(f"Rainfall/stock time series ({y0}-{y1})",
                      f"the {len(years)} epochs as a consistent series + the "
                      "behaviour archetype computed at run time",
                      f"time series map {y0}-{y1}",
                      systems=True,
                      why=f"{len(years)} year-tagged rasters form a temporal series"))
    # a change map needs only TWO epochs (its canonical case) — offer it
    # whenever >=2 year-tagged rasters exist and Spatial Analyst is available
    if len(years) >= 2 and sa:
        y0, y1 = years[0], years[-1]
        out.append(_s(f"Change map {y1} minus {y0}",
                      "difference of the last vs first epoch (diverging ramp)",
                      f"change map between {y0} and {y1}",
                      style={"ramp": "red_blue"}, systems=True,
                      requires="Spatial Analyst",
                      why="the rasters must be co-registered (same CRS + cell "
                          "grid); the script/user should verify this before "
                          "differencing"))
    for l in rasters:
        out.append(_s(f"Continuous surface — {l.name}",
                      "stretched raster display",
                      f"map of {l.name}",
                      why=f"{l.name} is a raster"))
        if sa and re.search(r"dem|elev|srtm|terrain|hgt", l.name + str(l.source), re.I):
            out.append(_s(f"Slope & hillshade — {l.name}",
                          "terrain derivatives from the DEM",
                          f"terrain slope hillshade map from {l.name}",
                          requires="Spatial Analyst",
                          why="a DEM supports slope/hillshade (Spatial Analyst)"))

    # ---- thematic archetype hints (from field / layer names) --------------
    blob = " ".join(l.name + " " + str(l.source) + " " +
                    " ".join(f["name"] for f in (l.extra.get("fields") or []))
                    for l in spec.layers).lower()
    seen_theme = set()
    for pat, depict, ramp in _THEME_HINTS:
        # leading-boundary so 'rain' doesn't fire on 'drainage', 'emission'
        # on 'transmission', etc.
        if re.search(r"(?<![a-z0-9])(?:" + pat + ")", blob) and depict not in seen_theme:
            seen_theme.add(depict)
            out.append(_s(f"Thematic: {depict}",
                          "apply this map type's cartographic conventions",
                          depict, style=({"ramp": ramp} if ramp else None),
                          systems=True, badge="theme",
                          why=f"names suggest a {depict.replace(' map','')}"))

    # de-dup by depict, cap
    uniq, keep = set(), []
    for s in out:
        if s["depict"] not in uniq:
            uniq.add(s["depict"])
            keep.append(s)
    return keep[:40]


# ---------------------------------------------------------------------------
def _s(title, description, depict, why="", style=None, systems=False,
       requires=None, badge=None):
    d: Dict[str, Any] = {"title": title, "description": description,
                         "depict": depict, "why": why}
    if style:
        d["style"] = style
    if systems:
        d["systems"] = True
    if requires:
        d["requires"] = requires
    if badge:
        d["badge"] = badge
    return d


def _years(rasters):
    ys = set()
    for l in rasters:
        for m in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", l.name + " " + str(l.source)):
            ys.add(int(m.group(0)))
    return sorted(ys)


def _has_spatial_analyst(profile):
    if not profile:
        return True                    # unknown -> offer it, script checks out the licence
    exts = profile.get("extensions") or {}
    return bool(exts.get("Spatial Analyst", True))
