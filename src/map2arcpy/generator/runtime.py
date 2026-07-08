# -*- coding: utf-8 -*-
"""
map2arcpy runtime — the helper block inlined into every generated script.

Everything between the BEGIN/END RUNTIME markers is copied verbatim into
generated scripts so they are single-file and dependency-free inside
ArcGIS Pro. The module also imports cleanly WITHOUT arcpy (lazy import), so
the test suite can exercise the pure parts anywhere.

Patterns here (env setup, QA gates, CIM symbology, programmatic layout,
export verification) are distilled from production ArcGIS Pro figure
pipelines.
"""
# --- BEGIN RUNTIME (map2arcpy) ---
import os
import datetime

try:
    import arcpy
    _HAS_ARCPY = True
except Exception:            # allows byte-compile / linting without ArcGIS Pro
    arcpy = None
    _HAS_ARCPY = False

PAGES = {"A4P": (21.0, 29.7), "A4L": (29.7, 21.0), "A3P": (29.7, 42.0),
         "A3L": (42.0, 29.7), "LetterP": (21.6, 27.9), "LetterL": (27.9, 21.6)}


def log(msg, level="INFO"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print("[%s] %-5s| %s" % (ts, level, msg))
    if _HAS_ARCPY and level in ("WARN", "ERROR"):
        (arcpy.AddWarning if level == "WARN" else arcpy.AddError)(msg)


def banner(title):
    print("\n" + "=" * 72 + "\n " + title + "\n" + "=" * 72)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 100]


def setup_env(work_dir, epsg):
    """scratch.gdb + results.gdb beside the script; CRS locked; perf env."""
    banner("ENVIRONMENT SETUP")
    scratch = os.path.join(work_dir, "scratch.gdb")
    results = os.path.join(work_dir, "results.gdb")
    for gdb in (scratch, results):
        if not arcpy.Exists(gdb):
            arcpy.management.CreateFileGDB(os.path.dirname(gdb), os.path.basename(gdb))
            log("created " + gdb)
    arcpy.env.overwriteOutput = True
    arcpy.env.scratchWorkspace = scratch
    arcpy.env.workspace = results
    sr = arcpy.SpatialReference(int(epsg))
    arcpy.env.outputCoordinateSystem = sr
    arcpy.env.parallelProcessingFactor = "100%"
    arcpy.env.pyramid = "NONE"
    log("target CRS locked to EPSG:%s (%s)" % (epsg, sr.name))
    return scratch, results


def audit_exists(paths):
    """QA gate — one consolidated missing-input failure, before any work."""
    missing = [p for p in paths if p and not str(p).startswith("http")
               and not arcpy.Exists(p) and not os.path.exists(p)]
    if missing:
        raise FileNotFoundError("Missing inputs:\n  - " + "\n  - ".join(missing))
    log("input audit OK (%d datasets)" % len(paths))


def ensure_projected(fc, epsg, out):
    """Reproject a vector dataset to the target CRS if it isn't already."""
    code = arcpy.Describe(fc).spatialReference.factoryCode
    if int(code) == int(epsg):
        return fc
    arcpy.management.Project(fc, out, arcpy.SpatialReference(int(epsg)))
    log("projected %s -> EPSG:%s" % (os.path.basename(str(fc)), epsg))
    return out


def apply_simple(layer, hexc, outline=None, transparency=0):
    try:
        sym = layer.symbology
        if hasattr(sym, "renderer"):
            sym.renderer.symbol.color = {"RGB": hex_to_rgb(hexc)}
            if outline:
                sym.renderer.symbol.outlineColor = {"RGB": hex_to_rgb(outline)}
            layer.symbology = sym
        if transparency:
            layer.transparency = transparency
        log("simple symbology on '%s' (%s)" % (layer.name, hexc))
    except Exception as e:
        log("simple symbology skipped on '%s': %s" % (layer.name, e), "WARN")


def apply_unique(layer, field, mapping):
    """Categorical (unique values) renderer from a {value: hex} mapping."""
    try:
        sym = layer.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        for grp in sym.renderer.groups:
            for itm in grp.items:
                key = itm.values[0][0]
                hexc = mapping.get(key)
                if hexc is None:
                    try:
                        hexc = mapping.get(int(key))
                    except (TypeError, ValueError):
                        hexc = mapping.get(str(key))
                if hexc:
                    itm.symbol.color = {"RGB": hex_to_rgb(hexc)}
        layer.symbology = sym
        log("unique-value symbology on '%s' (%d classes)" % (field, len(mapping)))
    except Exception as e:
        log("unique symbology skipped: %s" % e, "WARN")


def apply_graduated(layer, field, breaks, ramp):
    """Graduated colours with explicit breaks (breaks may be [] -> defaults)."""
    try:
        sym = layer.symbology
        sym.updateRenderer("GraduatedColorsRenderer")
        sym.renderer.classificationField = field
        n = len(breaks) if breaks else len(ramp)
        sym.renderer.breakCount = n
        cbs = sym.renderer.classBreaks
        for i, brk in enumerate(cbs):
            if breaks and i < len(breaks):
                brk.upperBound = breaks[i]
            if i < len(ramp):
                brk.symbol.color = {"RGB": hex_to_rgb(ramp[i])}
        layer.symbology = sym
        log("graduated symbology on '%s', %d classes" % (field, n))
    except Exception as e:
        log("graduated symbology skipped: %s" % e, "WARN")


def apply_stretch(layer, ramp):
    """Continuous raster: leave Pro's stretch, note the intended ramp."""
    log("stretch renderer kept for '%s' (intended ramp: %s)" % (layer.name, ramp))


def build_layout(aprx, the_map, cfg):
    """Programmatic layout: title/subtitle/credits + legend, north arrow,
    scale bar. Returns the Layout. (ArcGIS Pro 3.x arcpy.mp API.)"""
    w, h = PAGES.get(cfg.get("page", "A4P"), PAGES["A4P"])
    layout = aprx.createLayout(w, h, "CENTIMETER", "map2arcpy Layout")
    mf = layout.createMapFrame(
        arcpy.Polygon(arcpy.Array([arcpy.Point(1.0, 3.0), arcpy.Point(1.0, h - 3.0),
                                   arcpy.Point(w - 1.0, h - 3.0), arcpy.Point(w - 1.0, 3.0)])),
        the_map, "MainFrame")
    _text(layout, cfg.get("title", "").upper(), 1.0, h - 2.0, 16, bold=True)
    if cfg.get("subtitle"):
        _text(layout, cfg["subtitle"], 1.0, h - 2.8, 11)
    _text(layout, cfg.get("credits", ""), 1.0, 1.2, 7)
    if cfg.get("north_arrow", True):
        _surround(layout, mf, "NORTH_ARROW", "North_Arrow", w - 3.0, 4.0)
    if cfg.get("scale_bar", True):
        _surround(layout, mf, "SCALE_BAR", "Scale_Bar", 2.0, 3.4)
    if cfg.get("legend", True):
        try:
            layout.createMapSurroundElement(arcpy.Point(w - 5.0, h / 2), "LEGEND", mf)
        except Exception as e:
            log("legend skipped: %s" % e, "WARN")
    log("layout built (%s)" % cfg.get("page", "A4P"))
    return layout


def _text(layout, text, x, y, size, bold=False):
    if not text:
        return None
    el = layout.createTextElement(arcpy.Point(x, y), text, "POINT")
    el.textSize = size
    el.fontStyleName = "Bold" if bold else "Regular"
    return el


def _surround(layout, mf, kind, style_name, x, y):
    try:
        style = layout.map.listStyleItems("ArcGIS 2D", style_name)[0]
        layout.createMapSurroundElement(arcpy.Point(x, y), kind, mf, style)
    except Exception as e:
        log("%s skipped: %s" % (kind.lower(), e), "WARN")


def export_layout(layout, out_path, dpi=300):
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    if out_path.lower().endswith(".pdf"):
        layout.exportToPDF(out_path, resolution=dpi)
    else:
        layout.exportToPNG(out_path, resolution=dpi)
    if not os.path.exists(out_path):
        raise RuntimeError("Export missing: " + out_path)
    kb = os.path.getsize(out_path) / 1024.0
    if kb < 20:
        log("export suspiciously small (%.0f KB)" % kb, "WARN")
    log("EXPORT OK -> %s (%.0f KB)" % (out_path, kb))
# --- END RUNTIME (map2arcpy) ---


def runtime_source() -> str:
    """Return the marked runtime block for inlining into generated scripts."""
    here = os.path.abspath(__file__)
    if here.endswith((".pyc", ".pyo")):
        here = here[:-1]
    with open(here, "r", encoding="utf-8") as f:
        src = f.read()
    start = src.index("# --- BEGIN RUNTIME")
    end = src.index("# --- END RUNTIME")
    return src[start:end].rstrip() + "\n"
