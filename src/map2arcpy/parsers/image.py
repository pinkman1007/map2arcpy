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
    if ext == ".asc" or ext == ".agr":
        return _ascii_grid(path)
    if ext in (".flt", ".bil", ".bip", ".bsq"):
        return _hdr_raster(path)
    if ext == ".hgt":
        return _srtm_hgt(path)
    if ext == ".nc":
        return _netcdf(path)
    if ext == ".adf" or (os.path.isdir(path) and
                         os.path.exists(os.path.join(path, "hdr.adf"))):
        return _arcgrid(path)
    if ext in (".jp2", ".ecw", ".sid", ".dem", ".img"):
        return _plain_raster(path, ext)
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


# ===========================================================================
# additional raster formats (all header-level, pure stdlib)
# ===========================================================================
def _base_raster_spec(path: str, kind_note: str) -> MapSpec:
    spec = MapSpec(source_kind=kind_note)
    stem = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0]).strip("_")
    spec.layers.append(Layer(name=stem or "raster", source=path, kind="raster",
                             renderer=Renderer(type="stretch")))
    spec.layout.title = (stem or "Raster Map").replace("_", " ").title()
    spec.layout.export = (stem or "raster_map") + ".pdf"
    return spec


def _sidecar_epsg(path: str) -> Optional[int]:
    from .data import _epsg_from_prj
    return _epsg_from_prj(os.path.splitext(path)[0] + ".prj")


def _ascii_grid(path: str) -> MapSpec:
    """Esri ASCII grid (.asc): a 6-line text header — fully parseable."""
    spec = _base_raster_spec(path, "ascii-grid")
    hdr: Dict[str, float] = {}
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as f:
            for _ in range(6):
                parts = f.readline().split()
                if len(parts) == 2:
                    try:
                        hdr[parts[0].lower()] = float(parts[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    if "ncols" in hdr and "cellsize" in hdr:
        spec.notes.append(
            "ASCII grid: %d x %d cells, cell size %g, origin (%g, %g)"
            % (int(hdr.get("ncols", 0)), int(hdr.get("nrows", 0)),
               hdr["cellsize"],
               hdr.get("xllcorner", hdr.get("xllcenter", 0)),
               hdr.get("yllcorner", hdr.get("yllcenter", 0))))
    epsg = _sidecar_epsg(path)
    if epsg:
        spec.crs_epsg = epsg
    else:
        spec.notes.append("no .prj beside the ASCII grid — set 'epsg' in CONFIG")
    return spec


def _hdr_raster(path: str) -> MapSpec:
    """.flt/.bil/.bip/.bsq with a text .hdr sidecar."""
    spec = _base_raster_spec(path, "hdr-raster")
    hdr_path = os.path.splitext(path)[0] + ".hdr"
    hdr: Dict[str, str] = {}
    if os.path.exists(hdr_path):
        try:
            with open(hdr_path, "r", encoding="ascii", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        hdr[parts[0].lower()] = parts[1]
        except OSError:
            pass
    if hdr:
        spec.notes.append("header: " + ", ".join(f"{k}={v}" for k, v in
                                                 sorted(hdr.items())[:6]))
    else:
        spec.notes.append("no .hdr sidecar found — ArcGIS Pro needs it to read "
                          "this raster")
    epsg = _sidecar_epsg(path)
    if epsg:
        spec.crs_epsg = epsg
    return spec


def _srtm_hgt(path: str) -> MapSpec:
    """SRTM .hgt tile: the filename IS the georeferencing (N17E083 etc.)."""
    spec = _base_raster_spec(path, "srtm-hgt")
    spec.crs_epsg = 4326
    m = re.match(r"([NS])(\d{1,2})([EW])(\d{3})",
                 os.path.basename(path).upper())
    if m:
        lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
        lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
        spec.extent = [lon, lat, lon + 1, lat + 1]
        try:
            size = os.path.getsize(path)
            res = {2 * 3601 * 3601: "1 arc-second (~30 m)",
                   2 * 1201 * 1201: "3 arc-second (~90 m)"}.get(size)
            if res:
                spec.notes.append(f"SRTM tile {m.group(0)}: {res}")
        except OSError:
            pass
        spec.notes.append("SRTM elevation tile — consider a terrain workflow "
                          "(hillshade/slope) in ArcGIS Pro")
    else:
        spec.notes.append("could not read the tile position from the .hgt "
                          "filename — extent unknown")
    return spec


def _arcgrid(path: str) -> MapSpec:
    """Esri binary ArcGrid: a FOLDER of .adf files. dblbnd.adf carries the
    extent as four big-endian doubles; the rest stays binary-opaque (arcpy
    reads the folder natively)."""
    grid_dir = os.path.dirname(path) if path.lower().endswith(".adf") else path
    spec = _base_raster_spec(grid_dir.rstrip("/\\") or path, "arcgrid")
    dblbnd = os.path.join(grid_dir, "dblbnd.adf")
    if os.path.exists(dblbnd):
        try:
            with open(dblbnd, "rb") as f:
                xmin, ymin, xmax, ymax = struct.unpack(">4d", f.read(32))
            spec.notes.append("ArcGrid extent: (%g, %g) - (%g, %g)"
                              % (xmin, ymin, xmax, ymax))
        except (OSError, struct.error):
            pass
    epsg = None
    prj = os.path.join(grid_dir, "prj.adf")
    if os.path.exists(prj):
        from .data import _epsg_from_prj
        epsg = _epsg_from_prj(prj)
    if epsg:
        spec.crs_epsg = epsg
    else:
        spec.notes.append("ArcGrid CRS not readable here — verify 'epsg' in CONFIG")
    spec.notes.append("binary ArcGrid folder — added natively by ArcGIS Pro; "
                      "point the source at the folder, not a single .adf")
    return spec


def _plain_raster(path: str, ext: str) -> MapSpec:
    """Formats arcpy reads natively but whose headers we don't parse
    (.jp2/.ecw/.sid/.dem/.img)."""
    spec = _base_raster_spec(path, ext.lstrip("."))
    epsg = _sidecar_epsg(path)
    if epsg:
        spec.crs_epsg = epsg
    else:
        spec.notes.append(f"{ext} georeferencing is read by ArcGIS Pro itself — "
                          "verify 'epsg' in CONFIG matches the data")
    if ext in (".ecw", ".sid"):
        spec.notes.append(f"{ext} may need the appropriate raster-format "
                          "extension enabled in ArcGIS Pro")
    return spec


# ---------------------------------------------------------------------------
# NetCDF — classic (CDF-1/CDF-2) headers parsed for dimensions + variables;
# netCDF-4 (HDF5 container) detected and scaffolded honestly.
# ---------------------------------------------------------------------------
_NC_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}


def _netcdf(path: str) -> MapSpec:
    spec = _base_raster_spec(path, "netcdf")
    lyr = spec.layers[0]
    try:
        with open(path, "rb") as f:
            magic = f.read(8)
    except OSError:
        magic = b""
    if magic[:4] == b"\x89HDF":
        spec.notes.append("netCDF-4 (HDF5) file — variable/dimension names are "
                          "not parsed here; set them in CONFIG (the script uses "
                          "MakeNetCDFRasterLayer)")
        lyr.extra = {"variable": "TODO_VARIABLE", "x_dim": "lon", "y_dim": "lat"}
        return spec
    parsed = _netcdf_classic(path) if magic[:3] == b"CDF" else None
    if not parsed:
        spec.notes.append("could not parse the NetCDF header — set the variable "
                          "name in CONFIG")
        lyr.extra = {"variable": "TODO_VARIABLE", "x_dim": "lon", "y_dim": "lat"}
        return spec
    dims, variables = parsed
    data_vars = [v for v in variables if v not in dims]
    xdim = next((d for d in dims if d.lower() in
                 ("lon", "longitude", "x", "easting")), dims[0] if dims else "lon")
    ydim = next((d for d in dims if d.lower() in
                 ("lat", "latitude", "y", "northing")),
                dims[1] if len(dims) > 1 else "lat")
    var = data_vars[0] if data_vars else (variables[0] if variables else "TODO_VARIABLE")
    lyr.extra = {"variable": var, "x_dim": xdim, "y_dim": ydim}
    spec.notes.append(f"NetCDF: dimensions {dims}; variables {variables}; "
                      f"the script maps '{var}' over ({xdim}, {ydim}) — change "
                      "CONFIG if another variable is wanted")
    if len(data_vars) > 1:
        spec.notes.append("multiple data variables present — one raster layer "
                          "per run; duplicate the add_netcdf call for more")
    return spec


def _netcdf_classic(path: str):
    """Minimal classic-NetCDF header walk -> (dim_names, var_names)."""
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 20)
        version = data[3]                       # 1 = CDF-1 (32-bit), 2 = CDF-2
        begin_size = 4 if version == 1 else 8
        pos = [4]

        def u32() -> int:
            v = struct.unpack(">I", data[pos[0]:pos[0] + 4])[0]
            pos[0] += 4
            return v

        def name() -> str:
            n = u32()
            s = data[pos[0]:pos[0] + n].decode("utf-8", "ignore")
            pos[0] += n + ((4 - n % 4) % 4)
            return s

        def skip_attrs() -> None:
            tag, cnt = u32(), u32()
            if tag != 0x0C:
                return
            for _ in range(cnt):
                name()
                atype, alen = u32(), u32()
                size = alen * _NC_TYPE_SIZE.get(atype, 1)
                pos[0] += size + ((4 - size % 4) % 4)

        u32()                                   # numrecs
        dims: List[str] = []
        tag, cnt = u32(), u32()
        if tag == 0x0A:
            for _ in range(cnt):
                dims.append(name())
                u32()                           # dim length
        skip_attrs()                            # global attributes
        variables: List[str] = []
        tag, cnt = u32(), u32()
        if tag == 0x0B:
            for _ in range(cnt):
                variables.append(name())
                ndims = u32()
                pos[0] += 4 * ndims             # dimids
                skip_attrs()
                u32()                           # nc_type
                u32()                           # vsize
                pos[0] += begin_size            # begin offset
        return dims, variables
    except Exception:                           # noqa: BLE001 - honest fallback
        return None
