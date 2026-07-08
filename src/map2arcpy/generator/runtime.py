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


def check_pro_version(min_major=3):
    """Programmatic layouts (createLayout/createMapFrame) need ArcGIS Pro 3.x —
    warn up front instead of failing halfway through."""
    try:
        ver = str(arcpy.GetInstallInfo().get("Version", "0"))
        if int(ver.split(".")[0]) < min_major:
            log("ArcGIS Pro %s detected — this script's layout section needs "
                "Pro %d.x or newer" % (ver, min_major), "WARN")
    except Exception:                          # never block the run on a probe
        pass


def fresh_map(aprx, name):
    """Always build in a NEW map so the user's existing maps are never
    touched. Falls back to the first map WITHOUT clearing it."""
    try:
        return aprx.createMap(str(name)[:80] or "map2arcpy")
    except Exception as e:
        log("createMap unavailable (%s) — using the first existing map; "
            "your layers are NOT removed" % e, "WARN")
        maps = aprx.listMaps()
        if not maps:
            raise RuntimeError("project has no maps and createMap failed")
        return maps[0]


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
    _text(aprx, layout, cfg.get("title", "").upper(), 1.0, h - 2.0, 16, bold=True)
    if cfg.get("subtitle"):
        _text(aprx, layout, cfg["subtitle"], 1.0, h - 2.8, 11)
    _text(aprx, layout, cfg.get("credits", ""), 1.0, 1.2, 7)
    if cfg.get("north_arrow", True):
        _surround(aprx, layout, mf, "NORTH_ARROW", "North_Arrow", w - 3.0, 4.0)
    if cfg.get("scale_bar", True):
        _surround(aprx, layout, mf, "SCALE_BAR", "Scale_Bar", 2.0, 3.4)
    if cfg.get("legend", True):
        _surround(aprx, layout, mf, "LEGEND", "Legend", w - 5.0, h / 2)
    log("layout built (%s)" % cfg.get("page", "A4P"))
    return layout


def _text(aprx, layout, text, x, y, size, bold=False):
    """Pro 3.x: text elements are created from the PROJECT
    (aprx.createTextElement(layout, point, 'POINT', text, size)); older
    builds had layout.createTextElement. Try both, degrade to a WARN."""
    if not text:
        return None
    el = None
    try:
        el = aprx.createTextElement(layout, arcpy.Point(x, y), "POINT",
                                    str(text), size)
    except Exception:
        try:
            el = layout.createTextElement(arcpy.Point(x, y), str(text), "POINT")
        except Exception as e:
            log("text element skipped (%s...): %s" % (str(text)[:24], e), "WARN")
            return None
    for attr, val in (("textSize", size),
                      ("fontStyleName", "Bold" if bold else "Regular")):
        try:
            setattr(el, attr, val)
        except Exception:
            pass
    return el


def _surround(aprx, layout, mf, kind, style_name, x, y):
    """North arrow / scale bar / legend. Styles come from the project;
    creation is tried on the Layout first, then the project (API moved
    between Pro releases). Always degrades to a WARN, never crashes."""
    style = None
    for cat in (style_name, style_name.replace("_", " ")):
        try:
            items = aprx.listStyleItems("ArcGIS 2D", cat)
            if items:
                style = items[0]
                break
        except Exception:
            continue
    err = None
    for maker in (layout, aprx):
        for args in (((arcpy.Point(x, y), kind, mf, style) if style is not None
                      else (arcpy.Point(x, y), kind, mf)),
                     (arcpy.Point(x, y), kind, mf)):
            try:
                return maker.createMapSurroundElement(*args)
            except Exception as e:
                err = e
    log("%s skipped: %s" % (kind.lower(), err), "WARN")
    return None


def add_netcdf(m, results, src, name, variable, x_dim="lon", y_dim="lat"):
    """NetCDF -> raster layer (MakeNetCDFRasterLayer -> CopyRaster -> add)."""
    try:
        tmp = name + "_ncl"
        arcpy.md.MakeNetCDFRasterLayer(src, variable, x_dim, y_dim, tmp)
        out = os.path.join(results, name)
        arcpy.management.CopyRaster(tmp, out)
        log("NetCDF '%s' variable '%s' -> %s" % (os.path.basename(str(src)),
                                                 variable, out))
        return m.addDataFromPath(out)
    except Exception as e:
        log("NetCDF layer '%s' skipped: %s (check variable/x_dim/y_dim in "
            "CONFIG)" % (name, e), "WARN")
        return None


def add_gpx(m, results, src, name):
    """GPX -> points feature class (GPXtoFeatures) -> add."""
    try:
        out = os.path.join(results, name)
        arcpy.conversion.GPXtoFeatures(src, out)
        log("GPX converted -> %s" % out)
        return m.addDataFromPath(out)
    except Exception as e:
        log("GPX layer '%s' skipped: %s" % (name, e), "WARN")
        return None


def add_csv_xy(m, results, src, name, x_field, y_field, epsg=4326):
    """CSV with coordinate columns -> point feature class -> add."""
    try:
        out = os.path.join(results, name)
        arcpy.management.XYTableToPoint(src, out, x_field, y_field,
                                        coordinate_system=arcpy.SpatialReference(int(epsg)))
        log("CSV points (%s/%s) -> %s" % (x_field, y_field, out))
        return m.addDataFromPath(out)
    except Exception as e:
        log("CSV layer '%s' skipped: %s (set x_field/y_field in the "
            "add_csv_xy call)" % (name, e), "WARN")
        return None


def add_kml(m, work_dir, src, name):
    """KML/KMZ -> KMLToLayer -> add every Placemark feature class found."""
    try:
        arcpy.conversion.KMLToLayer(src, work_dir, name)
        gdb = os.path.join(work_dir, name + ".gdb")
        added = None
        for fc in ("Placemarks_Point", "Placemarks_Polyline", "Placemarks_Polygon",
                   "Points", "Polylines", "Polygons"):
            p = os.path.join(gdb, fc)
            if arcpy.Exists(p):
                added = m.addDataFromPath(p)
                log("KML class added: %s" % fc)
        if added is None:
            log("KML converted but no Placemark classes found in %s" % gdb, "WARN")
        return added
    except Exception as e:
        log("KML layer '%s' skipped: %s" % (name, e), "WARN")
        return None


def set_extent(layout, bbox4326):
    """Zoom the layout's map frame to a WGS84 [xmin, ymin, xmax, ymax] bbox
    (e.g. from a geocoded place). Safe no-op on failure."""
    try:
        w, s, e, n = bbox4326
        sr = arcpy.SpatialReference(4326)
        poly = arcpy.Polygon(arcpy.Array([arcpy.Point(w, s), arcpy.Point(w, n),
                                          arcpy.Point(e, n), arcpy.Point(e, s)]), sr)
        mf = layout.listElements("MAPFRAME_ELEMENT")[0]
        mf.camera.setExtent(poly.extent)
        log("map frame zoomed to bbox %s" % (bbox4326,))
    except Exception as e:
        log("set_extent skipped: %s" % e, "WARN")


def geojson_to_fc(path, out_fc, geometry="POLYGON"):
    """GeoJSON file -> feature class via JSONToFeatures (ArcGIS Pro 2.6+).
    Pro cannot add a .geojson directly, so every GeoJSON source converts
    into results.gdb first."""
    arcpy.conversion.JSONToFeatures(path, out_fc, geometry)
    log("converted %s -> %s" % (os.path.basename(str(path)), out_fc))
    return out_fc


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
