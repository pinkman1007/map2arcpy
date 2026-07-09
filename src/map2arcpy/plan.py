"""
The plan — "what I understood", stated BEFORE anything is generated.

describe(spec) turns a parsed MapSpec into a human-readable execution plan:
numbered intentions (geoprocessing steps, symbology, layout/export), a
summary of the attached data (layers, fields, detected years, gaps), and
plain warnings. The dashboard calls this live as the user types, so the
tool's understanding is VISIBLE before Generate — an empty instruction on
attached data says loudly "this will only display the data" instead of
silently producing a display map.

Pure function of the spec — no arcpy, no I/O — so it is fully testable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .spec import MapSpec, Operation, RASTER_OPS

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


# ---------------------------------------------------------------------------
def describe(spec: MapSpec, instruction_given: bool = True,
             profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    intentions: List[str] = []
    warnings: List[str] = []

    # ---- geoprocessing steps ------------------------------------------------
    for op in spec.operations:
        intentions.append(_op_phrase(op))

    # ---- symbology ------------------------------------------------------------
    op_outputs = {o.output for o in spec.operations if o.output}
    for l in spec.layers:
        if l.kind == "basemap" or not l.visible:
            continue
        r = l.renderer
        if r.type == "graduated" and r.field:
            intentions.append(f"draw '{l.name}' as a choropleth of "
                              f"{r.field}" + (f" ({r.ramp_name})" if r.ramp_name else ""))
        elif r.type == "unique" and r.field:
            intentions.append(f"draw '{l.name}' with one colour per class "
                              f"of {r.field}")
        elif r.type == "stretch":
            intentions.append(f"draw '{l.name}' as a continuous surface"
                              + (f" ({r.ramp_name})" if r.ramp_name else " (default stretch)"))
        elif l.source or l.name in op_outputs:
            intentions.append(f"draw '{l.name}'"
                              + (f" in {r.color}" if r.color else ""))
        if l.label_field:
            intentions.append(f"label '{l.name}' by {l.label_field}")

    # ---- layout / export ------------------------------------------------------
    lay = spec.layout
    fmt = lay.export.rsplit(".", 1)[-1].upper()
    intentions.append(f"layout: '{lay.title}' on {lay.page}, export {fmt} "
                      f"at {lay.dpi} dpi")
    off = [k.replace("_", " ") for k in ("legend", "north_arrow", "scale_bar")
           if not getattr(lay, k)]
    if off:
        intentions.append("without " + ", ".join(off))

    # ---- data inspector ---------------------------------------------------------
    data = _data_summary(spec)

    # ---- warnings ----------------------------------------------------------------
    has_data = any(l.source for l in spec.layers if l.kind != "basemap")
    if has_data and not spec.operations and not instruction_given:
        warnings.append(
            "NO INSTRUCTION — this will only DISPLAY the data. Type what to "
            "make of it (e.g. 'decadal average rainfall map', 'choropleth of "
            "<field>').")
    for n in spec.notes:
        if "NOT UNDERSTOOD" in n:
            warnings.append(n)
        elif "averaging step is missing" in n:
            warnings.append(n)
    if data.get("year_gaps"):
        warnings.append("year-tagged series has gaps: missing "
                        + ", ".join(str(y) for y in data["year_gaps"])
                        + " — averages/series will span the available years only")
    needs_sa = any(op.tool in RASTER_OPS for op in spec.operations)
    if needs_sa:
        licensed = _sa_available(profile)
        if licensed is False:
            warnings.append("this plan needs the Spatial Analyst extension, "
                            "which your Pro profile reports as NOT available")
        else:
            intentions.append("(needs Spatial Analyst — the script checks it "
                              "out automatically)")
    for l in spec.layers:
        for note in l.notes:
            if "no EPSG" in note or "CRS" in note and "undefined" in note.lower():
                warnings.append(f"[{l.name}] {note}")

    # methodology lines are the star — surface them separately
    methods = [n for n in spec.notes if n.startswith("ANALYSIS METHOD")]

    checks = _preflight(spec, instruction_given, has_data, needs_sa, profile,
                        data)

    return {"intentions": intentions, "data": data, "warnings": warnings,
            "methods": methods, "checks": checks,
            "will_analyse": bool(spec.operations),
            "source_kind": spec.source_kind}


def _preflight(spec: MapSpec, instruction_given: bool, has_data: bool,
               needs_sa: bool, profile, data) -> List[Dict[str, str]]:
    """Traffic lights: ok | warn | na, each with a one-line detail."""
    checks: List[Dict[str, str]] = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    add("instruction", "ok" if instruction_given else "warn",
        "instruction given" if instruction_given
        else "no instruction — display-only run")
    if has_data:
        n = f"{data.get('n_rasters', 0)} raster(s), {data.get('n_vectors', 0)} vector(s)"
        add("data", "ok", n)
    else:
        add("data", "ok" if spec.source_kind == "natural-language" or
            spec.operations or any(l.source for l in spec.layers) else "warn",
            "described from scratch" if not has_data else "")
    bad_steps = sum(1 for x in spec.notes if "NOT UNDERSTOOD" in x)
    add("understood", "warn" if bad_steps else "ok",
        f"{bad_steps} step(s) not understood" if bad_steps
        else "everything parsed")
    if spec.operations:
        add("analysis", "ok", f"{len(spec.operations)} geoprocessing step(s)")
    else:
        add("analysis", "na", "no analysis — display only")
    if needs_sa:
        lic = _sa_available(profile)
        add("spatial analyst",
            "warn" if lic is False else "ok",
            "NOT available per your Pro profile" if lic is False
            else ("licensed" if lic else "assumed — script checks at run time"))
    crs_flagged = any("no EPSG" in n or "CRS" in n and "undefined" in n.lower()
                      for l in spec.layers for n in l.notes)
    add("crs", "warn" if crs_flagged else "ok",
        "a dataset has no CRS code — verify CONFIG['epsg']" if crs_flagged
        else f"EPSG:{spec.crs_epsg}")
    return checks


# ---------------------------------------------------------------------------
def _op_phrase(op: Operation) -> str:
    p = op.params
    ins = ", ".join(str(i) for i in op.inputs[:3]) + \
          (f" (+{len(op.inputs) - 3} more)" if len(op.inputs) > 3 else "")
    if op.tool == "cell_statistics":
        n = f"{len(op.inputs)} rasters" if len(op.inputs) > 1 else \
            (f"rasters matching {p.get('pattern')}" if p.get("pattern") else ins)
        return (f"ANALYSE: Cell Statistics {p.get('stat', 'MEAN')} over {n} "
                f"→ '{op.output}'")
    if op.tool == "buffer":
        return f"ANALYSE: buffer {ins} by {p.get('distance', '500 Meters')} → '{op.output}'"
    if op.tool == "clip":
        return f"ANALYSE: clip {op.inputs[0]} to {op.inputs[-1]} → '{op.output}'"
    if op.tool == "erase":
        return f"ANALYSE: erase {op.inputs[-1]} from {op.inputs[0]} → '{op.output}'"
    if op.tool == "dissolve":
        return (f"ANALYSE: dissolve {ins}"
                + (f" by {p['field']}" if p.get("field") else "") + f" → '{op.output}'")
    if op.tool == "select":
        return f"ANALYSE: select where {p.get('where', '?')!r} → '{op.output}'"
    if op.tool == "slope":
        return f"ANALYSE: slope from {ins} → '{op.output}'"
    if op.tool == "hillshade":
        return f"ANALYSE: hillshade from {ins} → '{op.output}'"
    if op.tool == "euc_distance":
        return f"ANALYSE: distance surface from {ins} → '{op.output}'"
    if op.tool == "zonal_stats":
        return (f"ANALYSE: zonal statistics of {op.inputs[-1]} across "
                f"{op.inputs[0]} → table '{op.output}'")
    return f"ANALYSE: {op.tool} {ins} → '{op.output}'"


def _data_summary(spec: MapSpec) -> Dict[str, Any]:
    layers = []
    years = set()
    for l in spec.layers:
        if l.kind == "basemap" or not l.source:   # op outputs are results, not data
            continue
        d: Dict[str, Any] = {"name": l.name, "kind": l.kind}
        if l.geometry:
            d["geometry"] = l.geometry
        fields = l.extra.get("fields") if isinstance(l.extra, dict) else None
        if fields:
            d["fields"] = [f["name"] for f in fields][:24]
        m = _YEAR_RE.search(l.name + " " + str(l.source or ""))
        if m and l.kind == "raster":
            d["year"] = int(m.group(0))
            years.add(int(m.group(0)))
        layers.append(d)
    out: Dict[str, Any] = {"layers": layers,
                           "n_rasters": sum(1 for l in layers if l["kind"] == "raster"),
                           "n_vectors": sum(1 for l in layers if l["kind"] == "vector")}
    if years:
        ys = sorted(years)
        out["years"] = ys
        gaps = [y for y in range(ys[0], ys[-1] + 1) if y not in years]
        if gaps:
            out["year_gaps"] = gaps
    return out


def _sa_available(profile: Optional[Dict[str, Any]]):
    """True/False from the Pro probe profile; None when unknown."""
    if not profile:
        return None
    exts = profile.get("extensions") or {}
    if "Spatial Analyst" in exts:
        return bool(exts["Spatial Analyst"])
    return None
