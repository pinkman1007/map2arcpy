"""
ArcGIS Pro documents -> MapSpec.

Handles the CIM (Cartographic Information Model) JSON that ArcGIS Pro uses:

* ``.lyrx``  — a layer file: JSON text, ``layerDefinitions`` array
* ``.mapx``  — a map file:   JSON text, ``mapDefinition`` + layer definitions
* ``.aprx``  — a project *package*: a ZIP whose entries include CIM JSON
               documents; we walk every JSON entry and harvest layer
               definitions from the first map found.

Only reading is done here — pure stdlib (json + zipfile), no arcpy.
"""
from __future__ import annotations

import json
import os
import zipfile
from typing import Any, Dict, List, Optional

from ..spec import MapSpec, Layer, Renderer, Layout


def parse(path: str) -> MapSpec:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".aprx":
        docs = _aprx_docs(path)
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            docs = [json.load(f)]

    spec = MapSpec(source_kind=ext.lstrip("."))
    spec.layout.title = os.path.splitext(os.path.basename(path))[0].replace("_", " ").title()
    spec.layout.export = os.path.splitext(os.path.basename(path))[0] + ".pdf"

    layer_defs: List[Dict[str, Any]] = []
    map_def: Optional[Dict[str, Any]] = None
    for doc in docs:
        layer_defs.extend(doc.get("layerDefinitions") or [])
        if not map_def:
            md = doc.get("mapDefinition") or (
                doc if doc.get("type") == "CIMMap" else None)
            if md:
                map_def = md

    if map_def:
        if map_def.get("name"):
            spec.layout.title = map_def["name"]
        epsg = _epsg_from_sr(map_def.get("spatialReference"))
        if epsg:
            spec.crs_epsg = epsg

    if not layer_defs:
        spec.notes.append("no CIM layerDefinitions found in this document — "
                          "is it a valid ArcGIS Pro file?")

    for ld in layer_defs:
        lyr = _layer(ld)
        if lyr:
            spec.layers.append(lyr)

    if spec.crs_epsg == 4326:
        for ld in layer_defs:  # fall back to any layer's SR
            epsg = _epsg_from_sr((ld.get("featureTable") or {}).get("spatialReference"))
            if epsg:
                spec.crs_epsg = epsg
                break
    return spec


# ---------------------------------------------------------------------------
def _aprx_docs(path: str) -> List[Dict[str, Any]]:
    docs = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.lower().endswith((".json", ".mapx")) or "/" not in name:
                try:
                    with z.open(name) as f:
                        raw = f.read()
                    docs.append(json.loads(raw.decode("utf-8-sig")))
                except (ValueError, UnicodeDecodeError):
                    continue
    if not docs:
        raise ValueError(f"{path}: no CIM JSON documents found inside the .aprx")
    return docs


def _epsg_from_sr(sr: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(sr, dict):
        return None
    for key in ("latestWkid", "wkid"):
        v = sr.get(key)
        if isinstance(v, int) and v > 0:
            return v
    return None


def _layer(ld: Dict[str, Any]) -> Optional[Layer]:
    t = ld.get("type", "")
    name = ld.get("name") or "layer"
    if t == "CIMFeatureLayer":
        lyr = Layer(name=_safe(name), kind="vector")
        ft = ld.get("featureTable") or {}
        lyr.source = _dataset_path(ft.get("dataConnection") or {})
        if not lyr.source:
            lyr.source = "TODO_SET_PATH"
            lyr.notes.append(f"data connection for '{name}' could not be resolved — set the path")
        lyr.definition_query = ft.get("definitionExpression") or None
        lyr.renderer = _renderer(ld.get("renderer") or {})
        lyr.visible = bool(ld.get("visibility", True))
        for lc in ld.get("labelClasses") or []:
            expr = (lc.get("expression") or "").strip()
            if expr:
                lyr.label_field = expr.strip("[]$feature. ")
                break
        return lyr
    if t in ("CIMRasterLayer", "CIMTiledServiceLayer", "CIMVectorTileLayer"):
        kind = "raster" if t == "CIMRasterLayer" else "service"
        src = _dataset_path(ld.get("dataConnection") or {})
        lyr = Layer(name=_safe(name), kind=kind, source=src or "TODO_SET_PATH",
                    renderer=Renderer(type="stretch" if kind == "raster" else "simple"))
        if not src:
            lyr.notes.append(f"source for '{name}' not resolved from CIM — set the path/URL")
        return lyr
    if t == "CIMGroupLayer":
        return None  # members appear as their own layerDefinitions
    if t:
        return Layer(name=_safe(name), kind="vector", source="TODO_SET_PATH",
                     notes=[f"unhandled CIM layer type {t} — re-point manually"])
    return None


def _dataset_path(dc: Dict[str, Any]) -> str:
    """CIMStandardDataConnection -> filesystem path (or service URL)."""
    if not dc:
        return ""
    if dc.get("type") == "CIMAGSServiceConnection":
        return (dc.get("serverConnection") or {}).get("url", "") or dc.get("objectName", "")
    ws = dc.get("workspaceConnectionString", "")           # "DATABASE=C:\\data\\x.gdb"
    ds = dc.get("dataset", "")
    base = ""
    for part in ws.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip().upper() in ("DATABASE", "FOLDER", "URL"):
                base = v.strip()
                break
    if base and ds:
        return base.rstrip("/\\") + "/" + ds
    return ds or base


def _renderer(r: Dict[str, Any]) -> Renderer:
    t = r.get("type", "")
    if t == "CIMUniqueValueRenderer":
        field = (r.get("fields") or [None])[0]
        cmap: Dict[str, str] = {}
        for grp in r.get("groups") or []:
            for cls in grp.get("classes") or []:
                vals = cls.get("values") or []
                v = None
                if vals and (vals[0].get("fieldValues") or []):
                    v = vals[0]["fieldValues"][0]
                hexc = _symbol_hex(cls.get("symbol") or {})
                if v is not None and hexc:
                    cmap[str(v)] = hexc
        return Renderer(type="unique", field=field, color_map=cmap)
    if t == "CIMClassBreaksRenderer":
        breaks, ramp = [], []
        for cb in r.get("breaks") or []:
            if cb.get("upperBound") is not None:
                breaks.append(cb["upperBound"])
            hexc = _symbol_hex(cb.get("symbol") or {})
            if hexc:
                ramp.append(hexc)
        return Renderer(type="graduated", field=r.get("field"), breaks=breaks, ramp=ramp)
    if t == "CIMSimpleRenderer":
        return Renderer(type="simple", color=_symbol_hex(r.get("symbol") or {}))
    return Renderer(type="simple")


def _symbol_hex(symref: Dict[str, Any]) -> Optional[str]:
    """CIMSymbolReference -> first fill/marker colour as hex."""
    sym = symref.get("symbol") or symref
    for sl in sym.get("symbolLayers") or []:
        col = sl.get("color") or (sl.get("fillColor") if isinstance(sl.get("fillColor"), dict) else None)
        hexc = _cim_color_hex(col)
        if hexc:
            return hexc
        inner = sl.get("markerGraphics")
        if inner:
            for g in inner:
                hexc = _symbol_hex({"symbol": g.get("symbol") or {}})
                if hexc:
                    return hexc
    return _cim_color_hex(sym.get("color"))


def _cim_color_hex(col: Any) -> Optional[str]:
    if not isinstance(col, dict):
        return None
    vals = col.get("values") or []
    t = col.get("type", "")
    try:
        if t == "CIMRGBColor" and len(vals) >= 3:
            r, g, b = (int(round(v)) for v in vals[:3])
        elif t == "CIMHSVColor" and len(vals) >= 3:
            import colorsys
            rf, gf, bf = colorsys.hsv_to_rgb(vals[0] / 360.0, vals[1] / 100.0, vals[2] / 100.0)
            r, g, b = int(rf * 255), int(gf * 255), int(bf * 255)
        elif t == "CIMCMYKColor" and len(vals) >= 4:
            c, m, y, k = (v / 100.0 for v in vals[:4])
            r = int(255 * (1 - c) * (1 - k))
            g = int(255 * (1 - m) * (1 - k))
            b = int(255 * (1 - y) * (1 - k))
        else:
            return None
        return "#%02X%02X%02X" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    except (TypeError, ValueError):
        return None


def _safe(name: str) -> str:
    import re
    return re.sub(r"\W+", "_", name.strip()).strip("_") or "layer"
