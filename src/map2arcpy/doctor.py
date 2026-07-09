"""
The log doctor — paste an ArcGIS Pro run log (or a run_report.json), get a
diagnosis: what succeeded, what each warning means, and the one-line fix.

Deterministic rule table over the log lines the runtime itself emits — the
generated scripts log every decision, so the doctor reads their own
vocabulary back. No LLM; every finding cites the matched line.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

#: (pattern, severity, what it means, the fix)
_RULES = [
    (r"Missing inputs", "error",
     "one or more input datasets do not exist at the configured paths",
     "fix the paths in CONFIG['sources'] (the lines under this message name "
     "each missing file)"),
    (r"no rasters matched", "error",
     "the raster wildcard/folder matched nothing at run time",
     "check the pattern in the cell_statistics step — folder spelling, "
     "extension (.tif vs ArcGrid folders), and that the drive is attached"),
    (r"needs the Spatial Analyst|Spatial Analyst.*not available", "error",
     "the analysis requires the Spatial Analyst extension and it could not "
     "be checked out",
     "ArcGIS Pro -> Settings -> Licensing -> enable Spatial Analyst (or ask "
     "your license administrator)"),
    (r"layout section needs Pro (\d)", "error",
     "programmatic layouts need ArcGIS Pro 3.x",
     "the map and analysis still ran — update Pro, or assemble the layout "
     "manually from the built map"),
    (r"field '([\w ]+)' not found", "warn",
     "a field named in the instruction does not exist on that layer",
     "use the exact field name — the dashboard's data card lists every "
     "field (click one to insert it)"),
    (r"not matched in Pro styles|no Pro ramp matched", "warn",
     "the intended colour ramp has no match in your Pro style set — the "
     "default stretch was kept",
     "cosmetic only; pick a different ramp ('using blues') or apply one in "
     "the Symbology pane"),
    (r"export suspiciously small", "warn",
     "the exported file is under 20 KB — the layout may be empty",
     "check the map frame actually contains the layers (extent may be off — "
     "set CONFIG['extent'])"),
    (r"no active map detected", "info",
     "no map view was active, so outputs were not copied to your map",
     "click your map view (not Catalog) before running; the outputs are "
     "still on the script's own map"),
    (r"could not add '([\w ]+)' to your open map", "warn",
     "an output layer failed to copy onto your open map",
     "add it manually from the script's map, or from results.gdb next to "
     "the script"),
    (r"CRS was undefined on '([\w ]+)'", "info",
     "a dataset had no coordinate system; the script defined CONFIG['epsg'] "
     "on it (metadata only, no reprojection)",
     "verify that EPSG code is the data's TRUE CRS — a wrong define places "
     "data in the wrong location"),
    (r"createMap unavailable", "warn",
     "this Pro version could not create a fresh map — the first existing "
     "map was used (layers were NOT removed)",
     "update ArcGIS Pro for clean fresh-map behaviour"),
    (r"labels skipped", "warn",
     "the label class could not be configured",
     "set labels manually: Layer -> Labeling -> expression"),
    (r"systems: mean of .* failed", "warn",
     "one epoch's raster mean could not be computed for the systems series",
     "if it is NetCDF, make a raster layer of the variable first"),
    (r"KML converted but no feature classes", "warn",
     "the KML produced no feature classes",
     "open the .gdb the log names and check what KMLToLayer created"),
    (r"cell_statistics done", "good",
     "the raster averaging/statistics step completed", ""),
    (r"output layer '([\w ]+)' added to your open map", "good",
     "the analysis output landed on your open map", ""),
    (r"EXPORT OK -> (.+?) \(", "good", "the layout exported successfully", ""),
    (r"Spatial Analyst checked out", "good",
     "the Spatial Analyst extension was available", ""),
]

_DONE_RE = re.compile(r"\bALL DONE\b")
_ERR_TAIL_RE = re.compile(
    r"^(?:\w+Error|SystemExit|RuntimeError|FileNotFoundError)[:\s]", re.M)


def diagnose(text: str) -> Dict[str, Any]:
    """Diagnose a pasted Pro log or a run_report.json's contents."""
    text = (text or "").strip()
    if not text:
        return {"success": None, "findings": [],
                "summary": "nothing to diagnose — paste the run output"}
    # a run_report.json pastes fine too: pull its event lines out
    if text.startswith("{"):
        try:
            doc = json.loads(text)
            if isinstance(doc, dict) and doc.get("events"):
                text = "\n".join(str(e) for e in doc["events"])
        except ValueError:
            pass

    findings: List[Dict[str, str]] = []
    seen = set()
    for line in text.splitlines():
        for pat, sev, what, fix in _RULES:
            m = re.search(pat, line)
            if m and (pat, m.group(0)) not in seen:
                seen.add((pat, m.group(0)))
                f = {"severity": sev, "what": what, "line": line.strip()[:200]}
                if fix:
                    f["fix"] = fix
                findings.append(f)
    # an uncaught traceback tail that our rules didn't classify
    if _ERR_TAIL_RE.search(text) and not any(f["severity"] == "error"
                                             for f in findings):
        tail = [ln for ln in text.splitlines() if _ERR_TAIL_RE.match(ln)]
        findings.append({"severity": "error",
                         "what": "the run raised an error the rules don't "
                                 "recognise yet",
                         "line": (tail[-1] if tail else "")[:200],
                         "fix": "read the traceback above this line; the "
                                "failing tool is named in it"})

    done = bool(_DONE_RE.search(text))
    errors = [f for f in findings if f["severity"] == "error"]
    warns = [f for f in findings if f["severity"] == "warn"]
    if done and not errors:
        summary = ("run COMPLETED"
                   + (f" with {len(warns)} warning(s) — see below" if warns
                      else " cleanly — nothing to fix"))
        success = True
    elif errors:
        summary = f"run FAILED — {errors[0]['what']}"
        success = False
    else:
        summary = ("no 'ALL DONE' in this log — the run may have stopped "
                   "early; paste the FULL output including the end")
        success = None

    order = {"error": 0, "warn": 1, "info": 2, "good": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    return {"success": success, "findings": findings, "summary": summary}
