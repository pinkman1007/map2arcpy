"""
Thematic map archetypes — "make a CARBON map / an ECO-SENSITIVE ZONES map".

Naming a map TYPE carries conventions a cartographer would apply without
being told: carbon storage is a green sequential ramp, change maps diverge
through white, eco-sensitive zoning means graded buffer rings around the
protected features. This module encodes those conventions as deterministic
recipes, triggered by the words in a description or depict instruction and
applied WITHOUT overriding anything the user said explicitly (an explicit
"using blues" always wins; style overrides win over everything).

Every applied archetype leaves a note explaining what convention was used
and what to adjust.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .spec import MapSpec, Layer, Operation, Renderer
from .palettes import RAMPS

#: archetype-specific ramps (join the shared vocabulary)
RAMPS.setdefault("sensitivity", ["#D7191C", "#FDAE61", "#FFFFBF", "#A6D96A", "#1A9641"])
RAMPS.setdefault("ndvi", ["#8C510A", "#D8B365", "#F6E8C3", "#A6D96A", "#1A9641"])
RAMPS.setdefault("terrain", ["#276419", "#7FBC41", "#E6F5D0", "#DFC27D", "#8C510A"])
RAMPS.setdefault("thermal", ["#FFFFB2", "#FED976", "#FD8D3C", "#E31A1C", "#800026"])

ARCHETYPES: List[Dict[str, Any]] = [
    {"name": "carbon storage",
     "trigger": r"\bcarbon\s+(?:stock|storage|sequestr\w+|density)\b|\bbiomass\b",
     "ramp": "greens",
     "note": "carbon-storage convention: green sequential ramp, low->high "
             "(units usually Mg C/ha — state them in the subtitle)"},
    {"name": "carbon/GHG emissions",
     "trigger": r"\b(?:carbon|co2|ghg)\s+emissions?\b|\bemissions?\s+map\b",
     "ramp": "reds",
     "note": "emissions convention: red sequential ramp, low->high "
             "(state units, e.g. tCO2e/yr, in the subtitle)"},
    {"name": "eco-sensitive zones",
     "trigger": r"\beco[- ]?sensitiv\w+\b|\besz\b|\bbuffer\s+zones?\s+around\b",
     "ramp": "sensitivity",
     "ops": "esz",
     "note": "eco-sensitive-zone convention: graded buffer rings at 1/5/10 km "
             "around the protected features (edit 'distances' in the script), "
             "red = most sensitive. LEGAL CAVEAT: these fixed rings are a "
             "starting scaffold, NOT a legal rule — the Supreme Court (WP(C) "
             "202/1995, 26-Apr-2023) struck down the uniform 1 km ESZ; the "
             "site-specific MoEFCC gazette notification prevails. Verify against "
             "it. The buffer must run in a PROJECTED CRS (metres), not degrees."},
    {"name": "LULC / land use",
     "trigger": r"\blulc\b|\bland\s*(?:use|cover)\b",
     "renderer": "unique",
     "note": "LULC convention: categorical (unique values) symbology — if the "
             "class field wasn't detected, name it: 'unique values by LU_CLASS'"},
    {"name": "change / loss-gain",
     "trigger": r"\bchange\s+(?:detection|map)\b|\bloss(?:es)?\s+(?:and|&)?\s*gains?\b|\bdifference\s+map\b",
     "ramp": "red_blue",
     "note": "change-map convention: diverging ramp through white "
             "(loss=red, gain=blue) — class breaks should straddle zero"},
    {"name": "flood / inundation",
     "trigger": r"\bflood\w*\b|\binundat\w+\b|\bwater\s*logg\w+\b",
     "ramp": "blues",
     "note": "flood convention: blue sequential ramp, shallow->deep"},
    {"name": "hazard / risk",
     "trigger": r"\b(?:hazard|risk|vulnerab\w+)\s+(?:map|zones?|index)?\b",
     "ramp": "reds",
     "note": "hazard/risk convention: red sequential ramp, low->high"},
    {"name": "vegetation / NDVI",
     "trigger": r"\bndvi\b|\bvegetation\s+(?:index|health|cover)\b|\bgreenness\b",
     "ramp": "ndvi",
     "note": "vegetation convention: brown->green ramp (bare -> dense)"},
    {"name": "terrain / elevation",
     "trigger": r"\bterrain\b|\belevation\b|\bdem\s+map\b|\bslope\s+map\b|\bhillshade\b",
     "ramp": "terrain",
     "note": "terrain convention: hypsometric green->brown ramp; for slope or "
             "hillshade derivatives Spatial Analyst is required in Pro"},
    {"name": "rainfall / precipitation",
     "trigger": r"\brain\s*fall\b|\bprecipitat\w+\b|\bmonsoon\b",
     "ramp": "blues",
     "note": "rainfall convention: blue sequential ramp, dry->wet"},
    {"name": "temperature / heat",
     "trigger": r"\btemperature\b|\bheat\s*(?:island|map)?\b|\blst\b",
     "ramp": "thermal",
     "note": "temperature convention: thermal yellow->dark-red ramp"},
    {"name": "density",
     "trigger": r"\b(?:population|housing|built[- ]?up)?\s*density\s+map\b",
     "ramp": "oranges",
     "note": "density convention: orange sequential ramp — prefer a normalised "
             "field (per km2 / per capita) over raw counts"},
]


def detect(text: str) -> Optional[Dict[str, Any]]:
    low = " ".join(str(text or "").split()).lower()
    for arch in ARCHETYPES:
        if re.search(arch["trigger"], low):
            return arch
    return None


def apply(spec: MapSpec, text: str) -> MapSpec:
    """Apply the first matching archetype's conventions — gaps only, never
    overriding an explicit user choice already on the spec."""
    arch = detect(text)
    if not arch:
        return spec
    low = str(text).lower()
    user_named_ramp = any(re.search(r"\busing\s+%s\b" % re.escape(r.replace("_", " ")), low)
                          or re.search(r"\busing\s+%s\b" % re.escape(r), low)
                          for r in RAMPS)
    touched: List[str] = []

    ramp_name = arch.get("ramp")
    if ramp_name and not user_named_ramp:
        ramp = list(RAMPS[ramp_name])
        default = list(RAMPS.get("viridis", []))
        for l in spec.layers:
            r = l.renderer
            if r.type == "stretch" and not r.ramp:
                r.ramp = ramp
                r.ramp_name = ramp_name
                touched.append(l.name)
            elif r.type == "graduated" and (not r.ramp or r.ramp == default):
                r.ramp = ramp
                r.ramp_name = ramp_name
                touched.append(l.name)

    if arch.get("renderer") == "unique":
        for l in spec.layers:
            if l.kind == "raster" and l.renderer.type == "stretch":
                l.renderer = Renderer(type="unique", field="Value")
                l.notes.append("archetype set categorical symbology on 'Value' — "
                               "map class values to colours in the script")
                touched.append(l.name)
                break

    if arch.get("ops") == "esz":
        rings_op = next((o for o in spec.operations if o.tool == "multi_buffer"), None)
        if rings_op is None:
            target = next((l for l in spec.layers
                           if l.kind == "vector" and l.source), None)
            if target is not None:
                rings_op = Operation(
                    tool="multi_buffer", inputs=[target.name], output="esz_rings",
                    params={"distances": [1, 5, 10], "unit": "Kilometers"})
                spec.operations.append(rings_op)
            else:
                spec.notes.append("archetype 'eco-sensitive zones' needs a vector "
                                  "layer of protected features — none found")
        if rings_op is not None:
            out = rings_op.output or "esz_rings"
            rings_lyr = next((l for l in spec.layers if l.name == out), None)
            renderer = Renderer(type="graduated", field="distance",
                                ramp=list(RAMPS["sensitivity"]), ramp_name="sensitivity")
            if rings_lyr is None:
                spec.layers.append(Layer(name=out, source="", kind="vector",
                                         renderer=renderer))
                touched.append(out)
            elif not user_named_ramp:          # gaps-only: don't override "using X"
                rings_lyr.renderer = renderer
                touched.append(out)
        # projected-CRS gate — a distance buffer on EPSG:4326 (degrees) is
        # wrong-by-design; warn when the CRS looks geographic
        if spec.crs_epsg in (4326, 4269) or 4000 <= spec.crs_epsg < 5000:
            spec.notes.append("eco-sensitive zones: the ring buffers need a "
                              f"PROJECTED CRS in metres, but CONFIG epsg is "
                              f"{spec.crs_epsg} (geographic) — set a projected "
                              "EPSG (e.g. a UTM zone) or the km distances are wrong")

    spec.notes.append(f"archetype '{arch['name']}' applied"
                      + (f" to {', '.join(dict.fromkeys(touched))}" if touched else "")
                      + f" — {arch['note']}")
    return spec
