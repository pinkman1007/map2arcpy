"""
Map images -> MapSpec (best-effort, honest about limits).

Without a vision model, a picture of a map cannot be fully reverse-
engineered — and this tool does not pretend otherwise. What CAN be
extracted deterministically is extracted:

* GeoTIFF        — georeferencing tags parsed straight from the TIFF IFD
                   (ModelPixelScale 33550, ModelTiepoint 33922) and the EPSG
                   code from the GeoKeyDirectory (34735, keys 2048/3072)
* world files    — .tfw/.pgw/.jgw/.wld six-parameter affine
* geospatial PDF — detected via /LGIDict or /Measure /GEO markers

The result is a runnable script that loads the image as a raster layer with
the correct CRS/extent when known, plus a clearly-marked scaffold (layout,
export, symbology hooks) and TODO notes for what a human must confirm.
"""
from __future__ import annotations

import os
import re
import struct
from typing import Any, Dict, Optional, Tuple

from ..spec import MapSpec, Layer, Renderer

_WORLD_EXT = {".tif": (".tfw", ".wld"), ".tiff": (".tfw", ".wld"),
              ".png": (".pgw", ".wld"), ".jpg": (".jgw", ".wld"),
              ".jpeg": (".jgw", ".wld"), ".bmp": (".bpw", ".wld")}


def parse(path: str) -> MapSpec:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _pdf(path)
    spec = MapSpec(source_kind="image")
    stem = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_")
    lyr = Layer(name=stem or "map_image", source=path, kind="raster",
                renderer=Renderer(type="stretch"))

    georef: Dict[str, Any] = {}
    if ext in (".tif", ".tiff"):
        georef = _geotiff(path)
    if not georef.get("affine"):
        world = _world_file(path, ext)
        if world:
            georef["affine"] = world
            georef["via"] = "world file"

    if georef.get("epsg"):
        spec.crs_epsg = int(georef["epsg"])
    if georef.get("affine"):
        a = georef["affine"]
        spec.notes.append(f"georeferencing found via {georef.get('via', 'GeoTIFF tags')}: "
                          f"pixel size ({a[0]:.6g}, {a[3]:.6g}), origin ({a[4]:.6g}, {a[5]:.6g})")
        if not georef.get("epsg"):
            spec.notes.append("image is georeferenced but carries no EPSG code — "
                              "set 'epsg' in CONFIG to the true CRS")
        lyr.notes.append("added as a georeferenced raster; ArcGIS Pro will place it correctly")
    else:
        spec.notes.append("IMAGE INPUT IS EXPERIMENTAL: no georeferencing found — the "
                          "image is added as an unreferenced raster. Georeference it in "
                          "ArcGIS Pro (Imagery > Georeference) or supply a world file, "
                          "then re-run. Layer content (roads, boundaries, symbols) cannot "
                          "be recovered from pixels by a rule-based parser; the script is "
                          "a scaffold to build the map around this image.")
        lyr.notes.append("unreferenced image — georeference before analysis use")

    spec.layers.append(lyr)
    spec.layout.title = (stem or "Map Image").replace("_", " ").title()
    spec.layout.export = (stem or "map_image") + ".pdf"
    return spec


# ---------------------------------------------------------------------------
def _world_file(path: str, ext: str) -> Optional[Tuple[float, ...]]:
    base = os.path.splitext(path)[0]
    for wext in _WORLD_EXT.get(ext, (".wld",)):
        wf = base + wext
        if os.path.exists(wf):
            try:
                with open(wf, "r", encoding="utf-8-sig") as f:
                    vals = [float(x) for x in f.read().split()[:6]]
                if len(vals) == 6:
                    # A D B E C F -> (A, D, B, E, C, F): x-scale, rotations, y-scale, origin
                    return (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
            except (ValueError, OSError):
                continue
    return None


def _geotiff(path: str) -> Dict[str, Any]:
    """Minimal TIFF IFD walk for the three GeoTIFF tags we care about."""
    out: Dict[str, Any] = {}
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return out
            if head[:2] == b"II":
                bo = "<"
            elif head[:2] == b"MM":
                bo = ">"
            else:
                return out
            magic = struct.unpack(bo + "H", head[2:4])[0]
            if magic != 42:                      # BigTIFF (43) not handled
                return out
            ifd_off = struct.unpack(bo + "I", head[4:8])[0]
            f.seek(ifd_off)
            n = struct.unpack(bo + "H", f.read(2))[0]
            tags: Dict[int, Tuple[int, int, bytes]] = {}
            for _ in range(n):
                e = f.read(12)
                tag, ftype, count = struct.unpack(bo + "HHI", e[:8])
                tags[tag] = (ftype, count, e[8:12])

            def _values(tag: int):
                if tag not in tags:
                    return None
                ftype, count, raw = tags[tag]
                size = {3: 2, 4: 4, 12: 8}.get(ftype)
                if not size:
                    return None
                total = size * count
                if total <= 4:
                    data = raw[:total]
                else:
                    off = struct.unpack(bo + "I", raw)[0]
                    f.seek(off)
                    data = f.read(total)
                fmt = {3: "H", 4: "I", 12: "d"}[ftype]
                return struct.unpack(bo + str(count) + fmt, data)

            scale = _values(33550)               # ModelPixelScaleTag
            tie = _values(33922)                 # ModelTiepointTag
            if scale and tie and len(scale) >= 2 and len(tie) >= 6:
                sx, sy = scale[0], scale[1]
                ox, oy = tie[3], tie[4]
                out["affine"] = (sx, 0.0, 0.0, -abs(sy), ox, oy)
                out["via"] = "GeoTIFF tags"
            geokeys = _values(34735)             # GeoKeyDirectoryTag
            if geokeys and len(geokeys) >= 4:
                nkeys = geokeys[3]
                for i in range(nkeys):
                    k = geokeys[4 + i * 4: 8 + i * 4]
                    if len(k) == 4 and k[0] in (2048, 3072) and k[1] == 0 and k[3] not in (0, 32767):
                        out["epsg"] = int(k[3])
                        if k[0] == 3072:         # projected code wins over geographic
                            break
    except (OSError, struct.error):
        return out
    return out


def _pdf(path: str) -> MapSpec:
    spec = MapSpec(source_kind="pdf")
    stem = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_")
    geospatial = False
    try:
        with open(path, "rb") as f:
            blob = f.read(4 * 1024 * 1024)       # markers live in the page dicts
        geospatial = (b"/LGIDict" in blob) or (b"/Measure" in blob and b"/GEO" in blob)
    except OSError:
        pass

    lyr = Layer(name=stem or "map_pdf", source=path, kind="raster",
                renderer=Renderer(type="stretch"))
    if geospatial:
        spec.notes.append("geospatial PDF detected (georeferencing dictionary present) — "
                          "ArcGIS Pro can add it directly; coordinates carry over")
        lyr.notes.append("geospatial PDF — added directly as a layer")
    else:
        spec.notes.append("PDF INPUT IS EXPERIMENTAL: no geospatial markers found. The "
                          "script scaffolds a map around the PDF; export the page as an "
                          "image and georeference it in ArcGIS Pro for analysis use.")
        lyr.notes.append("plain (non-geospatial) PDF — georeference after import")
    spec.layers.append(lyr)
    spec.layout.title = (stem or "Map PDF").replace("_", " ").title()
    spec.layout.export = (stem or "map_pdf") + "_rebuilt.pdf"
    return spec
