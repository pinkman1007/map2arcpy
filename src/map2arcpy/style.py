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

    if style.get("reverse_ramp"):
        n = 0
        for l in spec.layers:
            if l.renderer.ramp:
                l.renderer.ramp = list(reversed(l.renderer.ramp))
                n += 1
        applied.append(f"reverse_ramp ({n} layers)")

    classes = style.get("classes")
    if classes:
        try:
            c = int(classes)
            if 2 <= c <= 12:
                for l in spec.layers:
                    if l.renderer.type == "graduated":
                        l.renderer.class_count = c
                applied.append(f"classes={c}")
            else:
                skipped.append(f"classes {c} (2-12)")
        except (TypeError, ValueError):
            skipped.append(f"classes '{classes}'")

    method = style.get("classify")
    if method:
        m = str(method).lower().replace(" ", "_")
        valid = ("natural_breaks", "quantile", "equal_interval",
                 "geometric", "std_dev", "defined_interval")
        if m in valid:
            for l in spec.layers:
                if l.renderer.type == "graduated":
                    l.renderer.class_method = m
            applied.append(f"classify={m}")
        else:
            skipped.append(f"classify '{method}' (use one of {', '.join(valid)})")

    trans = style.get("transparency")
    if trans is not None and trans != "":
        try:
            tv = int(trans)
            if 0 <= tv <= 100:
                for l in spec.layers:
                    if l.kind != "basemap":
                        l.renderer.transparency = tv
                applied.append(f"transparency={tv}")
            else:
                skipped.append(f"transparency {tv} (0-100)")
        except (TypeError, ValueError):
            skipped.append(f"transparency '{trans}'")

    outline = style.get("outline")
    if outline:
        o = str(outline).strip()
        if _HEX.match(o):
            o = "#" + o.lstrip("#").upper()
            for l in spec.layers:
                if l.kind == "vector":
                    l.renderer.outline = o
            applied.append(f"outline={o}")
        else:
            skipped.append(f"outline '{outline}' (use #RRGGBB)")

    ow = style.get("outline_width")
    if ow is not None and ow != "":
        try:
            w = float(ow)
            if 0 <= w <= 10:
                for l in spec.layers:
                    if l.kind == "vector":
                        l.renderer.outline_width = w
                applied.append(f"outline_width={w}")
            else:
                skipped.append(f"outline_width {w} (0-10 pt)")
        except (TypeError, ValueError):
            skipped.append(f"outline_width '{ow}'")

    ms = style.get("marker_size")
    if ms is not None and ms != "":
        try:
            s = float(ms)
            if 0 < s <= 72:
                for l in spec.layers:
                    if l.geometry == "point" or (l.kind == "vector" and not l.geometry):
                        l.renderer.marker_size = s
                applied.append(f"marker_size={s}")
            else:
                skipped.append(f"marker_size {s} (1-72 pt)")
        except (TypeError, ValueError):
            skipped.append(f"marker_size '{ms}'")

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
