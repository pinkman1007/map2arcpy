"""Decide which parser handles a given input."""
from __future__ import annotations

import json
import os

from .spec import MapSpec
from .parsers import nl, cim, data, image

_CIM_EXT = (".aprx", ".lyrx", ".mapx")
_DATA_EXT = (".geojson", ".shp", ".gpkg", ".kml", ".kmz", ".gpx", ".csv",
             ".dxf", ".dwg", ".dgn")
_IMAGE_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".pdf",
              ".asc", ".agr", ".flt", ".bil", ".bip", ".bsq", ".hgt",
              ".nc", ".adf", ".jp2", ".ecw", ".sid", ".dem", ".img")
_TEXT_EXT = (".txt", ".md")


def detect_kind(inp: str) -> str:
    """'nl' | 'cim' | 'data' | 'image' | 'spec' for a path or a description."""
    if os.path.isdir(inp) and os.path.exists(os.path.join(inp, "hdr.adf")):
        return "image"                                 # binary ArcGrid folder
    if os.path.exists(inp) and not os.path.isdir(inp):
        ext = os.path.splitext(inp)[1].lower()
        if ext in _CIM_EXT:
            return "cim"
        if ext in _DATA_EXT:
            return "data"
        if ext in _IMAGE_EXT:
            return "image"
        if ext == ".json":
            try:
                with open(inp, "r", encoding="utf-8-sig") as f:
                    doc = json.load(f)
            except (ValueError, OSError):
                return "nl"
            if isinstance(doc, dict):
                if doc.get("schema_version") and "layers" in doc:
                    return "spec"                      # our own saved MapSpec
                if "operationalLayers" in doc or doc.get("type") in (
                        "FeatureCollection", "Feature"):
                    return "data"
                if "layerDefinitions" in doc or doc.get("type") == "CIMMap":
                    return "cim"
            return "data"
        if ext in _TEXT_EXT:
            return "nl"
        raise ValueError(f"unsupported file type: {ext or inp}")
    # looks like a file reference but doesn't exist -> fail loudly, don't
    # silently reinterpret a typo'd path as a map description
    ext = os.path.splitext(inp)[1].lower()
    if " " not in inp and ext in (_CIM_EXT + _DATA_EXT + _IMAGE_EXT + (".json",)):
        raise FileNotFoundError(f"input file not found: {inp}")
    # not a file -> treat the string itself as a description
    return "nl"


def parse_any(inp: str) -> MapSpec:
    kind = detect_kind(inp)
    if kind == "cim":
        return cim.parse(inp)
    if kind == "data":
        return data.parse(inp)
    if kind == "image":
        return image.parse(inp)
    if kind == "spec":
        with open(inp, "r", encoding="utf-8-sig") as f:
            return MapSpec.from_json(f.read())
    if os.path.exists(inp):
        with open(inp, "r", encoding="utf-8-sig") as f:
            text = f.read()
        hint = os.path.splitext(os.path.basename(inp))[0]
        return nl.parse(text, name_hint=hint)
    return nl.parse(inp)
