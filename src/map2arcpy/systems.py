"""
Systems-thinking layer (opt-in) — the causal graph from docs/ARCHETYPE_STUDY.md
turned into deterministic map advice.

OFF by default. When enabled (CLI --systems, dashboard toggle, API
"systems": true), it inspects the archetype the map depicts and adds,
without ever overriding the user:

* a CAUSAL CONTEXT note — the drivers of this theme and which the user
  supplied data for (matched against layer names)
* stock/flow DISCIPLINE — flags a signed flow (change/difference map) that
  isn't using a diverging ramp; notes stock-vs-flow classification
* a BOUNDARY critique — flow-type themes clipped to administrative units get
  a "use the natural system boundary (watershed/airshed)" note
* a SYSTEMS CONTEXT block — the feedback loops this theme sits inside, for
  the generated script header and DPR narrative

Everything is a note or a header block; no analysis is invented and no
renderer the user chose is changed. Pure, testable, offline.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .spec import MapSpec
from . import archetypes

#: SD classification per archetype name (see the study, §0)
SD_CLASS = {
    "carbon storage": "stock",
    "carbon/GHG emissions": "flow",
    "eco-sensitive zones": "state/regulation",
    "LULC / land use": "state",
    "change / loss-gain": "flow",
    "flood / inundation": "state<-flows",
    "hazard / risk": "composite index",
    "vegetation / NDVI": "state/indicator",
    "terrain / elevation": "driver",
    "rainfall / precipitation": "flow (inflow)",
    "temperature / heat": "state",
    "density": "state/driver",
}

#: drivers of each theme: (driver label, sign, keywords to detect in layers)
CAUSAL_GRAPH: Dict[str, List[Dict[str, Any]]] = {
    "flood / inundation": [
        {"driver": "rainfall", "sign": "+", "kw": ["rain", "precip", "persiann"]},
        {"driver": "slope/terrain", "sign": "+", "kw": ["slope", "dem", "terrain", "elev"]},
        {"driver": "built-up/imperviousness (density)", "sign": "+",
         "kw": ["built", "density", "urban", "impervious", "lulc"]},
        {"driver": "drainage capacity", "sign": "-", "kw": ["drain", "stream", "canal", "nala"]},
        {"driver": "vegetation/green cover", "sign": "-", "kw": ["ndvi", "veg", "green", "forest"]},
    ],
    "temperature / heat": [
        {"driver": "built-up density", "sign": "+", "kw": ["built", "density", "urban", "lulc"]},
        {"driver": "vegetation (evapotranspiration)", "sign": "-", "kw": ["ndvi", "veg", "green", "forest"]},
        {"driver": "water bodies", "sign": "-", "kw": ["water", "lake", "tank", "river"]},
    ],
    "carbon storage": [
        {"driver": "land use / land cover", "sign": "+", "kw": ["lulc", "land", "forest", "veg", "ndvi"]},
        {"driver": "LULC change (loss)", "sign": "-", "kw": ["change", "loss", "deforest"]},
    ],
    "carbon/GHG emissions": [
        {"driver": "LULC change (land emissions)", "sign": "+", "kw": ["change", "lulc", "deforest"]},
        {"driver": "density / transport", "sign": "+", "kw": ["density", "road", "traffic", "built"]},
        {"driver": "waste mass", "sign": "+", "kw": ["waste", "dump", "landfill"]},
    ],
    "hazard / risk": [
        {"driver": "hazard (flood/slope/rainfall)", "sign": "+", "kw": ["flood", "slope", "rain", "hazard"]},
        {"driver": "exposure (density/assets)", "sign": "+", "kw": ["density", "built", "population", "asset"]},
        {"driver": "vulnerability", "sign": "+", "kw": ["vulnerab", "poverty", "fragil"]},
    ],
    "vegetation / NDVI": [
        {"driver": "rainfall", "sign": "+", "kw": ["rain", "precip"]},
        {"driver": "land use", "sign": "+", "kw": ["lulc", "land", "forest"]},
    ],
    "change / loss-gain": [
        {"driver": "density (urban pressure)", "sign": "+", "kw": ["density", "built", "urban"]},
    ],
}

#: feedback loops per theme, for the SYSTEMS CONTEXT header block
LOOPS: Dict[str, List[str]] = {
    "flood / inundation": [
        "Reinforcing (urban flood): built-up up -> impervious up -> runoff up "
        "-> flooding up -> more hard drainage -> downstream flooding up.",
        "Balancing: green/permeable cover up -> infiltration up -> runoff down.",
    ],
    "temperature / heat": [
        "Reinforcing (urban heat island): built-up up -> heat up -> AC demand up "
        "-> waste heat + power emissions up -> heat up.",
        "Balancing: vegetation up -> evapotranspiration cooling -> heat down.",
    ],
    "carbon storage": [
        "Reinforcing (deforestation-climate): vegetation loss -> carbon stock down "
        "-> CO2 up -> warming -> drought/fire risk up -> further vegetation loss.",
        "Balancing (weak): CO2 up -> some fertilisation of growth -> uptake up.",
    ],
    "carbon/GHG emissions": [
        "Reinforcing (climate): emissions up -> warming -> impacts up.",
        "Balancing (policy): emissions mapped -> regulation -> emissions down.",
    ],
    "change / loss-gain": [
        "Reinforcing (urbanisation): built-up up -> land value up -> more "
        "conversion; conversion is often irreversible on planning timescales.",
    ],
    "eco-sensitive zones": [
        "Balancing (regulation): ESZ restricts development, resisting the "
        "urbanisation loop's pressure on the ecology stock.",
    ],
    "LULC / land use": [
        "Central driver node: built-up up -> impervious up (runoff, heat up); "
        "forest down -> carbon and biodiversity down.",
    ],
}

#: administrative-boundary keywords, for the boundary critique
_ADMIN_KW = ["ward", "zone", "boundary", "admin", "block", "mandal", "district",
             "municipal", "corporation", "ulb", "gp", "panchayat", "city"]
#: themes whose flow nature makes admin clipping a systems error
_FLOW_THEMES = {"flood / inundation", "rainfall / precipitation",
                "carbon/GHG emissions", "change / loss-gain"}


def apply(spec: MapSpec, depict_text: str = "") -> MapSpec:
    """Add systems-thinking notes + a header block. Returns spec unchanged in
    substance (renderers/ops untouched); only notes and spec.systems_context
    are populated."""
    text = " ".join((depict_text or "").split()) + " " + (spec.layout.title or "")
    # a "change/difference" cue anywhere wins over the LULC match it contains
    if re.search(r"\b(change|loss.?gain|difference|delta)\b", text, re.I):
        arch = next(a for a in archetypes.ARCHETYPES if a["name"] == "change / loss-gain")
    else:
        arch = (archetypes.detect(depict_text or "") or archetypes.detect(text)
                or archetypes.detect(_layer_blob(spec)))
    if not arch:
        spec.notes.append("systems: no thematic archetype detected — enable a "
                          "map type (e.g. 'flood map', 'carbon map') to get "
                          "causal context")
        return spec
    name = arch["name"]
    lines: List[str] = []

    sd = SD_CLASS.get(name, "state")
    lines.append(f"This map depicts a {sd.upper()} ({name}).")

    # --- causal drivers + coverage -----------------------------------------
    layer_blob = _layer_blob(spec).lower()
    drivers = CAUSAL_GRAPH.get(name)
    if drivers:
        have, miss = [], []
        for d in drivers:
            present = any(k in layer_blob for k in d["kw"])
            tag = f"{d['driver']} ({d['sign']})"
            (have if present else miss).append(tag)
        lines.append("Drivers in this system: "
                     + "; ".join(f"{d['driver']} ({d['sign']})" for d in drivers) + ".")
        lines.append(f"Data present for {len(have)} of {len(drivers)}: "
                     + (", ".join(have) or "none") + ".")
        if miss:
            lines.append("Consider mapping alongside: " + ", ".join(miss) + ".")
        spec.notes.append(f"systems: {name} is driven by {len(drivers)} factors — "
                          f"you have {len(have)} ({', '.join(have) or 'none'}); "
                          f"missing {', '.join(miss) or 'none'}")

    # --- stock/flow ramp discipline ----------------------------------------
    if sd.startswith("flow"):
        signed = _is_signed_flow(name, text)
        for l in spec.layers:
            if l.renderer.type in ("graduated", "stretch"):
                diverging = _looks_diverging(l.renderer.ramp)
                if signed and l.renderer.ramp and not diverging:
                    spec.notes.append(
                        f"systems: '{l.name}' is a SIGNED FLOW (gain/loss) but its "
                        "ramp is sequential — a diverging ramp (e.g. red_blue) "
                        "reads loss vs gain correctly")
        lines.append("Flow discipline: signed flows (change/difference) use a "
                     "DIVERGING ramp through a neutral zero; one-signed flows "
                     "(emissions, rainfall) stay sequential.")

    # --- boundary critique --------------------------------------------------
    if name in _FLOW_THEMES:
        clipped_admin = any(o.tool == "clip" for o in spec.operations) and \
            any(k in layer_blob for k in _ADMIN_KW)
        nat = ("watershed/catchment" if name in ("flood / inundation",
               "rainfall / precipitation") else "airshed/functional region")
        if clipped_admin:
            spec.notes.append(
                f"systems: this is a FLOW theme clipped to an administrative "
                f"boundary — flows don't respect ward/zone lines; the natural "
                f"system boundary here is the {nat}")
        lines.append(f"Boundary: as a flow, its natural system boundary is the "
                     f"{nat}, not administrative units.")

    # --- feedback loops -----------------------------------------------------
    loops = LOOPS.get(name)
    if loops:
        lines.append("Feedback loops:")
        lines.extend("  - " + lp for lp in loops)

    # --- temporal series -> behaviour-archetype hook -----------------------
    years = _detect_years(spec)
    if len(years) >= 3:
        lines.append(f"Temporal series detected: {len(years)} epochs "
                     f"({years[0]}-{years[-1]}). This stock over time can be "
                     "classified against the behaviour archetypes (Limits to "
                     "Growth, Overshoot, etc.): compute the per-epoch metric "
                     "(zonal sum / class area) in Pro, then run "
                     f"`map2arcpy dynamics \"v1,v2,...,vN\"`.")
        spec.notes.append(f"systems: {len(years)} time epochs found "
                          f"({years[0]}-{years[-1]}) — after computing the "
                          "per-year metric, classify its behaviour with "
                          "`map2arcpy dynamics`")

    spec.systems_context = lines
    spec.notes.append(f"systems: context added for '{name}' — see the SYSTEMS "
                      "CONTEXT block in the script header")
    return spec


def _detect_years(spec: MapSpec) -> List[int]:
    yrs = set()
    for l in spec.layers:
        # digit-boundaries, not \b — a year after '_' or a letter (rain_2015,
        # PERSIANN_1y2015) has no word boundary before the digits
        for m in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)",
                             l.name + " " + str(l.source)):
            yrs.add(int(m.group(0)))
    return sorted(yrs)


# ---------------------------------------------------------------------------
def _layer_blob(spec: MapSpec) -> str:
    parts = [l.name for l in spec.layers] + \
            [str(l.source) for l in spec.layers] + \
            [l.renderer.field or "" for l in spec.layers]
    return " ".join(parts)


def _is_signed_flow(name: str, text: str) -> bool:
    if name == "change / loss-gain":
        return True
    low = text.lower()
    return bool(re.search(r"\b(change|difference|loss|gain|net|delta|trend)\b", low))


def _looks_diverging(ramp: List[str]) -> bool:
    """A diverging ramp has a light/neutral middle between two dark ends."""
    if not ramp or len(ramp) < 3:
        return False
    mid = ramp[len(ramp) // 2].lstrip("#")
    try:
        r, g, b = int(mid[0:2], 16), int(mid[2:4], 16), int(mid[4:6], 16)
        return min(r, g, b) > 200          # near-white/neutral centre
    except (ValueError, IndexError):
        return False
