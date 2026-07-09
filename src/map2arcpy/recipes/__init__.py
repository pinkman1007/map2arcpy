"""
The recipe library — ready-to-run step-by-step recipes for standard map
products, shipped with the package. Each .txt in this folder is a recipe:
'#' lines are comments (including the "replace X with your data" guidance),
every other line is one grammar step, applied in order.

    map2arcpy recipes                 # list them
    map2arcpy recipes flood_buffer    # print one (edit paths, then generate)
    map2arcpy recipes flood_buffer -o flood.py   # generate its script now

Reproducible cartography as code: a recipe is version-controllable,
shareable, and produces the same script every time.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List

_DIR = os.path.dirname(os.path.abspath(__file__))


def list_recipes() -> List[str]:
    return sorted(os.path.splitext(f)[0] for f in os.listdir(_DIR)
                  if f.endswith(".txt"))


def get(name: str) -> str:
    path = os.path.join(_DIR, os.path.basename(name) + ".txt")
    if not os.path.exists(path):
        raise ValueError(f"unknown recipe '{name}' — available: "
                         + ", ".join(list_recipes()))
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def describe(name: str) -> str:
    """The recipe's one-line description (its first comment line)."""
    for ln in get(name).splitlines():
        s = ln.strip()
        if s.startswith("#"):
            return s.lstrip("# ").strip()
    return name


def catalog() -> Dict[str, Dict[str, str]]:
    """{name: {title, text}} for the API/dashboard."""
    out = {}
    for n in list_recipes():
        out[n] = {"title": describe(n), "text": get(n)}
    return out
