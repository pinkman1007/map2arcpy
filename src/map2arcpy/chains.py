"""
Analysis chains — WHICH toolboxes and analyses make a given map product.

The archetype layer (archetypes.py) knows how a product should LOOK
(rainfall = blues, terrain = hypsometric …). This layer knows how a product
is MADE: the geoprocessing methodology — which Spatial Analyst / Analysis
toolset, which tool, in what order — stated explicitly in the spec notes and
carried into the generated script's header as an ANALYSIS METHOD block.

Two behaviours, both deterministic:

1. ADVISE — when a product phrase is recognised ("decadal average rainfall
   map"), the methodology note is attached: toolbox path, tool, why, and the
   grammar phrase that triggers it, so the user can add the missing step.
2. INJECT — in the safe, unambiguous case (a period-average product with
   several year-tagged rasters uploaded and no averaging step yet), the
   cell_statistics MEAN operation is added automatically, targeted at those
   rasters, so "decadal average rainfall map" + ten uploaded rasters is a
   complete instruction.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .spec import MapSpec, Operation, Layer, Renderer

#: (trigger regex, product name, methodology text, grammar hint)
CHAINS = [
    (r"\b(?:decadal|annual|monthly|period|long[- ]term)?\s*(?:average|mean)\s+"
     r"(?:annual\s+)?rain(?:fall)?|\brain(?:fall)?\s+(?:average|mean|normals?)\b",
     "Period-average rainfall",
     "Spatial Analyst > Local > Cell Statistics (MEAN) over the per-year "
     "rasters -> one average surface -> continuous stretch display. All input "
     "rasters must share CRS and cell grid.",
     "average of C:/rain/rain_20*.tif"),
    (r"\bslope\b|\bhillshade\b|\bterrain\s+analysis\b",
     "Terrain derivatives",
     "Spatial Analyst > Surface > Slope (DEGREE) and Hillshade (az 315, "
     "alt 45) from the DEM; drape slope over hillshade for the classic "
     "terrain figure.",
     "terrain slope hillshade map from dem.tif"),
    (r"\b(?:euclidean\s+)?distance\s+(?:to|from)\b|\bproximity\s+(?:map|to)\b",
     "Proximity surface",
     "Spatial Analyst > Distance > Euclidean Distance from the feature "
     "layer -> continuous distance raster (use a projected CRS so distances "
     "are metres).",
     "distance to rivers.shp"),
    (r"\bzonal\s+stat|\bper[- ]ward\s+(?:average|mean|rainfall|value)|"
     r"\b(?:average|mean)\s+.{0,24}\bper\s+(?:ward|zone|district|village)\b",
     "Zonal summary",
     "Spatial Analyst > Zonal > Zonal Statistics as Table (MEAN) of the "
     "value raster across the zone polygons -> join back to the zones for a "
     "choropleth.",
     "zonal statistics of rainfall.tif by wards.shp"),
    (r"\bchange\s+(?:map|detection)\b|\bdifference\s+between\b.*\b(?:19|20)\d{2}\b",
     "Change detection",
     "Spatial Analyst > Map Algebra: newest minus oldest epoch (Raster "
     "Calculator / Minus) -> diverging ramp centred on zero. Rasters must be "
     "co-registered.",
     "change map between 2015 and 2024 (from year-tagged rasters)"),
    (r"\bflood\s+(?:risk|hazard|buffer|zone)\b",
     "Flood-risk zone (screening)",
     "Analysis > Proximity > Buffer around the drainage lines, clipped to "
     "the study area (screening-level; hydraulic modelling is out of scope "
     "for a buffer map and the map should say so).",
     "buffer rivers.shp by 100 m, clip to wards.shp"),
    (r"\bservice\s+area\b|\bwalkab|\bcatchment\b",
     "Service area (screening)",
     "Analysis > Proximity > Buffer (or Multiple Ring Buffer) around the "
     "facilities; true network service areas need the Network Analyst "
     "extension, which this screening buffer approximates.",
     "buffer hospitals.shp by 500 m"),
]

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def apply(spec: MapSpec, text: str) -> List[str]:
    """Attach methodology notes for recognised products; inject the averaging
    op in the unambiguous multi-raster case. Returns what was applied."""
    low = " ".join((text or "").split()).lower()
    applied: List[str] = []
    if not low:
        return applied

    for pat, product, method, hint in CHAINS:
        if re.search(pat, low):
            note = f"ANALYSIS METHOD — {product}: {method}"
            if note not in spec.notes:
                spec.notes.append(note)
                applied.append(product)
            # honest gap note when the method's op is absent and ungeneratable
            if product == "Period-average rainfall" and \
                    not any(o.tool == "cell_statistics" for o in spec.operations):
                injected = _inject_average(spec)
                if injected:
                    applied.append("cell_statistics injected over "
                                   f"{injected} year-tagged rasters")
                else:
                    spec.notes.append(
                        "the averaging step is missing — add a step like "
                        f"'{hint}', or upload the per-year rasters together "
                        "and the MEAN is added automatically")
    return applied


def _inject_average(spec: MapSpec) -> Optional[int]:
    """Several year-tagged rasters + an average-rainfall product and no
    cell_statistics yet -> add the MEAN op over exactly those rasters."""
    yeared = [l for l in spec.layers
              if l.kind == "raster" and l.source and
              _YEAR_RE.search(l.name + " " + str(l.source))]
    if len(yeared) < 2:
        return None
    years = sorted({int(m.group(0)) for l in yeared
                    for m in [_YEAR_RE.search(l.name + " " + str(l.source))] if m})
    out = "period_average"
    spec.operations.insert(0, Operation(
        tool="cell_statistics", inputs=[l.name for l in yeared],
        output=out, params={"stat": "MEAN"}))
    # declare the output as a stretch raster NOW so the archetype pass
    # (which runs after chains) applies the product's conventional ramp
    if not any(l.name == out for l in spec.layers):
        spec.layers.append(Layer(name=out, source="", kind="raster",
                                 renderer=Renderer(type="stretch")))
    for l in yeared:                      # inputs stay loaded but not drawn
        l.visible = False
        l.notes.append("input epoch for the period average (not drawn)")
    spec.notes.append(
        "period average injected: Cell Statistics MEAN over %d rasters "
        "(%s-%s)" % (len(yeared), years[0], years[-1]))
    return len(yeared)
