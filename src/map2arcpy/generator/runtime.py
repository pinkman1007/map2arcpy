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


def ensure_crs_defined(sources, epsg):
    """Datasets with an UNKNOWN coordinate system (common with downloaded
    rasters whose GeoTIFF tags lack an EPSG code) get one defined so Pro
    can place them. DefineProjection only writes metadata — it never
    reprojects pixels — and is skipped for anything that already has a CRS."""
    sr = arcpy.SpatialReference(int(epsg))
    for name, src in sources.items():
        if not src or str(src).startswith("http"):
            continue
        try:
            d = arcpy.Describe(src)
            sr_name = getattr(getattr(d, "spatialReference", None), "name", "") or ""
            if sr_name.lower() in ("", "unknown"):
                arcpy.management.DefineProjection(src, sr)
                log("CRS was undefined on '%s' -> defined EPSG:%s" % (name, epsg))
        except Exception as e:
            log("CRS check skipped for '%s': %s" % (name, e), "WARN")


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


def _ols2(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 1.0
    return slope, my - slope * mx, max(0.0, min(1.0, r2))


def classify_series(x):
    """Compact behaviour-archetype classifier (see docs/SYSTEMS_DYNAMICS_MATH.md).
    Returns behaviour + archetype + indicators. Behavioural consistency, not
    proof of structure."""
    import math as _m
    n = len(x)
    if n < 3:
        return {"behaviour": "insufficient data (need >=3 epochs)"}
    t = list(range(n))
    mean = sum(x) / n
    tot = sum((v - mean) ** 2 for v in x)
    exp = None
    if all(v > 0 for v in x):
        r, b, _ = _ols2(t, [_m.log(v) for v in x])
        x0 = _m.exp(b)
        ss = sum((x[i] - x0 * _m.exp(r * t[i])) ** 2 for i in range(n))
        exp = {"r": r, "r2": (1 - ss / tot) if tot > 0 else 1.0}
    log = None
    xmax = max(x)
    if xmax > 0 and n >= 4:
        lo, hi = xmax * 1.001, xmax * 4.0
        for i in range(241):
            K = lo + (hi - lo) * i / 240
            pts = [(t[j], x[j]) for j in range(n) if 0 < x[j] < K]
            if len(pts) < 3:
                continue
            r, b, _ = _ols2([p[0] for p in pts],
                            [_m.log(p[1] / (K - p[1])) for p in pts])
            if r <= 0:
                continue
            A = _m.exp(-b)
            ss = sum((x[j] - K / (1 + A * _m.exp(-r * t[j]))) ** 2 for j in range(n))
            r2 = (1 - ss / tot) if tot > 0 else 1.0
            if log is None or r2 > log["r2"]:
                log = {"K": K, "r": r, "r2": r2, "frac": x[-1] / K}
    pk = max(range(n), key=lambda i: x[i])
    if 0 < pk < n - 1 and x[-1] < x[pk] * 0.92 and x[pk] > x[0]:
        return {"behaviour": "overshoot then decline",
                "archetype": "overshoot and collapse (limits-to-growth with "
                             "delay, or tragedy of the commons)"}
    if log and log["r2"] >= 0.9 and log["frac"] > 0.55 \
            and log["r2"] >= (exp["r2"] if exp else 0) - 0.02:
        return {"behaviour": "S-curve approaching a limit",
                "archetype": "limits to growth",
                "K": log["K"], "r": log["r"], "fraction_of_limit": log["frac"]}
    if exp and exp["r"] > 0 and exp["r2"] >= 0.9 \
            and all(x[i + 1] >= x[i] for i in range(n - 1)):
        out = {"behaviour": "accelerating (near-exponential) growth",
               "archetype": "reinforcing growth", "r": exp["r"]}
        if exp["r"] > 0:
            out["doubling_time"] = _m.log(2) / exp["r"]
        return out
    if all(x[i + 1] <= x[i] for i in range(n - 1)):
        return {"behaviour": "sustained decline",
                "archetype": "decline / erosion (eroding goals or depletion)"}
    return {"behaviour": "irregular / no clean archetype signature",
            "archetype": "-"}


def raster_series_means(pairs):
    """pairs: [(year, raster_source), ...] -> [(year, mean_over_raster), ...]."""
    out = []
    for yr, src in pairs:
        try:
            m = float(arcpy.management.GetRasterProperties(src, "MEAN").getOutput(0))
            out.append((yr, m))
        except Exception as e:
            log("systems: mean of %s failed: %s" % (src, e), "WARN")
    return out


def systems_dynamics_report(pairs, work_dir, metric="raster mean"):
    """Compute the per-epoch metric from the temporal rasters and classify its
    behaviour archetype — printed as its own result block and written to a
    sidecar file, so the archetype appears when the map is prepared."""
    banner("SYSTEMS DYNAMICS  (behaviour archetype)")
    ser = raster_series_means(pairs)
    if len(ser) < 3:
        log("systems dynamics: fewer than 3 epochs with values — skipped", "WARN")
        return None
    ser.sort(key=lambda p: p[0])
    years = [p[0] for p in ser]
    vals = [p[1] for p in ser]
    res = classify_series(vals)
    print("  metric        : %s over the AOI, per epoch" % metric)
    print("  series        : " + ", ".join("%s=%.4g" % (y, v) for y, v in ser))
    print("  BEHAVIOUR     : %s" % res.get("behaviour", "?"))
    print("  ARCHETYPE     : %s" % res.get("archetype", "-"))
    for k, lbl in (("K", "carrying capacity K"), ("r", "growth rate r"),
                   ("fraction_of_limit", "fraction of limit reached"),
                   ("doubling_time", "doubling time")):
        if k in res:
            print("  %-14s: %.4g" % (lbl, res[k]))
    print("  NOTE          : behavioural consistency, NOT proof of structure")
    try:
        p = os.path.join(work_dir, "systems_dynamics.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("SYSTEMS DYNAMICS — behaviour archetype\n")
            f.write("metric: %s per epoch over the AOI\n" % metric)
            for y, v in ser:
                f.write("  %s : %.6g\n" % (y, v))
            f.write("\nbehaviour: %s\narchetype: %s\n"
                    % (res.get("behaviour"), res.get("archetype")))
            for k in ("K", "r", "fraction_of_limit", "doubling_time"):
                if k in res:
                    f.write("%s: %.6g\n" % (k, res[k]))
            f.write("\nbehavioural consistency, not proof of structure\n")
        log("systems dynamics report -> %s" % p)
    except Exception as e:
        log("systems sidecar not written: %s" % e, "WARN")
    return res


def show_in_pro(aprx, the_map, layout=None):
    """Bring the freshly built map (and layout) up in the ArcGIS Pro window
    and zoom to the data. Uses openView (Pro 3.1+); harmlessly skipped when
    running headless via propy.bat."""
    if layout is not None:
        try:
            layout.openView()
        except Exception as e:
            log("layout view not opened: %s" % e, "WARN")
    try:
        the_map.openView()
        try:
            mv = aprx.activeView
            lyrs = [l for l in the_map.listLayers()
                    if not l.isBasemapLayer and l.visible]
            if lyrs and hasattr(mv, "getLayerExtent"):
                mv.camera.setExtent(mv.getLayerExtent(lyrs[0]))
        except Exception as e:
            log("auto-zoom skipped: %s" % e, "WARN")
        log("map view opened in ArcGIS Pro")
    except Exception as e:
        log("map view not opened (%s) — double-click the map in the "
            "Catalog pane" % e, "WARN")


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
