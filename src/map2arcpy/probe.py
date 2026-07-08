"""
The ArcGIS Pro environment handshake.

map2arcpy generates scripts BLIND unless it knows the Pro it targets. The
probe fixes that: `map2arcpy probe` writes a tiny self-contained script,
the user runs it ONCE inside ArcGIS Pro (Python window or notebook), and it
saves a machine profile to ``~/map2arcpy_data/pro_profile.json``:

* Pro version + product + license level
* which extensions are actually available (Spatial Analyst, 3D, …)
* whether a portal is signed in (decides if basemaps will resolve)
* the open project: path, default gdb, maps and their layers

Every subsequent generation auto-loads this profile and adapts — classic
tools on old Pro, basemaps commented out when there is no portal,
``aprx_template`` pre-filled with the real project for propy runs, and
honest warnings when the profile says something will not work.

Profile location override: the ``MAP2ARCPY_PROFILE`` environment variable.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

PROFILE_SCHEMA = 1


def profile_path() -> str:
    env = os.environ.get("MAP2ARCPY_PROFILE")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), "map2arcpy_data",
                        "pro_profile.json")


def load_profile(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Saved profile dict, or None (missing/unreadable never raises)."""
    p = path or profile_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            prof = json.load(f)
        return prof if isinstance(prof, dict) and prof.get("pro_version") else None
    except (OSError, ValueError):
        return None


def pro_version(profile: Optional[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    """(major, minor) from a profile, or None."""
    if not profile:
        return None
    try:
        parts = str(profile.get("pro_version", "")).split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None


def use_classic_tools(profile: Optional[Dict[str, Any]]) -> bool:
    """Pairwise* geoprocessing arrived in Pro 2.7 — fall back before that."""
    v = pro_version(profile)
    return bool(v and (v[0] < 2 or (v[0] == 2 and v[1] < 7)))


def summary(profile: Optional[Dict[str, Any]]) -> Optional[str]:
    if not profile:
        return None
    exts = [k for k, v in (profile.get("extensions") or {}).items() if v]
    portal = "portal signed in" if profile.get("portal_signed_in") else "no portal"
    proj = (profile.get("project") or {}).get("path")
    bits = [f"ArcGIS Pro {profile.get('pro_version')}",
            str(profile.get("license") or "").strip() or None,
            portal,
            f"{len(exts)} extensions" if exts else "no extensions",
            os.path.basename(proj) if proj else None]
    return " · ".join(b for b in bits if b)


def probe_script(out_path: Optional[str] = None) -> str:
    """The self-contained script the user runs once inside ArcGIS Pro."""
    out = out_path or profile_path()
    return _PROBE_TEMPLATE.replace("__OUT_PATH__", repr(out))


_PROBE_TEMPLATE = '''# -*- coding: utf-8 -*-
"""map2arcpy environment probe — run this ONCE inside ArcGIS Pro.

How: ArcGIS Pro -> Analysis -> Python window (or a notebook cell) ->
    exec(open(r'this_file.py').read())        # or:  %run this_file.py

It only READS your environment and writes one small JSON profile so
map2arcpy can generate scripts matched to this machine. Re-run it after
upgrading Pro, changing licenses, or switching portals.
"""
import datetime
import json
import os
import sys

profile = {
    "profile_schema": 1,
    "captured": datetime.datetime.now().isoformat(timespec="seconds"),
    "python": sys.version.split()[0],
}

try:
    import arcpy
except ImportError:
    raise SystemExit("arcpy not found — run this inside ArcGIS Pro, not plain Python.")

info = arcpy.GetInstallInfo()
profile["pro_version"] = info.get("Version")
profile["product"] = info.get("ProductName")
try:
    profile["license"] = {"ArcInfo": "Advanced", "ArcEditor": "Standard",
                          "ArcView": "Basic"}.get(arcpy.ProductInfo(),
                                                  arcpy.ProductInfo())
except Exception:
    profile["license"] = None

exts = {}
for code, name in [("Spatial", "Spatial Analyst"), ("3D", "3D Analyst"),
                   ("Network", "Network Analyst"), ("ImageAnalyst", "Image Analyst"),
                   ("GeoStats", "Geostatistical Analyst")]:
    try:
        exts[name] = arcpy.CheckExtension(code) == "Available"
    except Exception:
        exts[name] = False
profile["extensions"] = exts

try:
    profile["portal_url"] = arcpy.GetActivePortalURL()
    profile["portal_signed_in"] = bool(arcpy.GetSigninToken())
except Exception:
    profile["portal_url"] = None
    profile["portal_signed_in"] = False

try:
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    profile["project"] = {
        "path": aprx.filePath,
        "default_gdb": aprx.defaultGeodatabase,
        "maps": [{"name": m.name,
                  "layers": [l.name for l in m.listLayers()][:50]}
                 for m in aprx.listMaps()[:10]],
    }
except Exception:
    profile["project"] = None       # fine: probably running via propy.bat

out = __OUT_PATH__
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(profile, f, indent=2)

print("=" * 60)
print("map2arcpy profile written -> " + out)
print("  Pro " + str(profile["pro_version"]) + "  (" + str(profile["license"]) + ")")
print("  portal signed in: " + str(profile["portal_signed_in"]))
print("  extensions available: " +
      (", ".join(k for k, v in exts.items() if v) or "none"))
if profile["project"]:
    print("  project: " + str(profile["project"]["path"]))
print("map2arcpy will now generate scripts matched to this machine.")
print("=" * 60)
'''
