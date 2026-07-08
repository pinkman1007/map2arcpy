"""
User style overrides — "how should the map look?"

Parsers PROPOSE cartography; this module lets the user OVERRIDE it without
touching the spec by hand. A style dict rides along with a generate/inspect
request (dashboard panel, CLI flags, or API "style" key) and is applied on
top of the parsed MapSpec:

    {"title": "...", "subtitle": "...",
     "ramp": "blues",                 # graduated/stretch layers
     "color": "#1A9641",              # simple-rendered vector layers
     "basemap": "Imagery" | "none",
     "page": "A3L", "dpi": 300, "format": "pdf",
     "legend": true, "north_arrow": false, "scale_bar": true}

Unknown/invalid values are skipped with a note — a style never breaks a
generation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .spec import MapSpec, Layer, VALID_PAGES
from .palettes import RAMPS, BASEMAPS

_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")
_FORMATS = ("pdf", "png", "jpg")


def apply_style(spec: MapSpec, style: Dict[str, Any]) -> MapSpec:
    if not style:
        return spec
    applied: List[str] = []
    skipped: List[str] = []
    lay = spec.layout

    t = style.get("title")
    if t and str(t).strip():
        lay.title = str(t).strip()[:120]
        lay.export = _slug(lay.title) + _ext(lay.export)
        applied.append("title")
    s = style.get("subtitle")
    if s is not None and str(s).strip():
        lay.subtitle = str(s).strip()[:200]
        applied.append("subtitle")

    page = style.get("page")
    if page:
        if page in VALID_PAGES:
            lay.page = page
            applied.append(f"page={page}")
        else:
            skipped.append(f"page '{page}' (use one of {', '.join(VALID_PAGES)})")

    dpi = style.get("dpi")
    if dpi:
        try:
            d = int(dpi)
            if 72 <= d <= 1200:
                lay.dpi = d
                applied.append(f"dpi={d}")
            else:
                skipped.append(f"dpi {d} (72-1200)")
        except (TypeError, ValueError):
            skipped.append(f"dpi '{dpi}'")

    fmt = style.get("format")
    if fmt:
        f = str(fmt).lower().lstrip(".")
        if f in _FORMATS:
            lay.export = lay.export.rsplit(".", 1)[0] + "." + f
            applied.append(f"format={f}")
        else:
            skipped.append(f"format '{fmt}' (pdf/png/jpg)")

    for key in ("legend", "north_arrow", "scale_bar"):
        if key in style and style[key] is not None:
            setattr(lay, key, bool(style[key]))
            applied.append(f"{key}={'on' if style[key] else 'off'}")

    ramp = style.get("ramp")
    if ramp:
        if ramp in RAMPS:
            n = 0
            for l in spec.layers:
                if l.renderer.type in ("graduated", "stretch"):
                    l.renderer.ramp = list(RAMPS[ramp])
                    n += 1
            applied.append(f"ramp={ramp} ({n} layers)")
        else:
            skipped.append(f"ramp '{ramp}' (use one of {', '.join(RAMPS)})")

    color = style.get("color")
    if color:
        c = str(color).strip()
        if _HEX.match(c):
            c = "#" + c.lstrip("#").upper()
            n = 0
            for l in spec.layers:
                if l.kind == "vector" and l.renderer.type == "simple":
                    l.renderer.color = c
                    n += 1
            applied.append(f"color={c} ({n} layers)")
        else:
            skipped.append(f"color '{color}' (use #RRGGBB)")

    bm = style.get("basemap")
    if bm:
        name = str(bm).strip()
        if name.lower() in ("none", "off", "no"):
            spec.layers = [l for l in spec.layers if l.kind != "basemap"]
            applied.append("basemap=none")
        else:
            resolved = BASEMAPS.get(name.lower(), name if name in BASEMAPS.values()
                                    else None)
            if resolved:
                spec.layers = [l for l in spec.layers if l.kind != "basemap"]
                spec.layers.insert(0, Layer(name="basemap", kind="basemap",
                                            source=resolved))
                applied.append(f"basemap={resolved}")
            else:
                skipped.append(f"basemap '{bm}' (e.g. {', '.join(sorted(set(BASEMAPS.values()))[:5])}...)")

    if applied:
        spec.notes.append("style overrides applied: " + "; ".join(applied))
    for sk in skipped:
        spec.notes.append("style override skipped: " + sk)
    return spec


def _slug(text: str) -> str:
    return re.sub(r"\W+", "_", text.lower()).strip("_") or "map"


def _ext(export: str) -> str:
    return "." + export.rsplit(".", 1)[-1] if "." in export else ".pdf"
