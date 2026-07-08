"""
ZIP archives -> MapSpec.

Zipped shapefiles are the lingua franca of data portals, so `.zip` is a
first-class input: the archive is extracted to a sibling folder
(`<name>_unzipped/`) — the generated script needs real paths on disk — and
every supported payload inside is parsed and merged into ONE MapSpec
(multiple shapefiles become multiple layers).

Guards: per-entry and total size caps (zip-bomb), entry-count cap, and
path-traversal-safe extraction (no absolute paths, no `..`).
"""
from __future__ import annotations

import os
import zipfile
from typing import List

from ..spec import MapSpec

#: extensions we parse as primary datasets (sidecars ride along silently)
_PRIMARY_EXT = (".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".gpx", ".csv",
                ".dxf", ".dwg", ".dgn", ".lyrx", ".mapx", ".json",
                ".tif", ".tiff", ".asc", ".agr", ".nc", ".hgt", ".flt", ".bil",
                ".img", ".jp2", ".dem", ".png", ".jpg", ".jpeg", ".pdf")
_SIDECAR_EXT = (".dbf", ".prj", ".shx", ".cpg", ".sbn", ".sbx", ".qix",
                ".hdr", ".stx", ".aux", ".ovr", ".tfw", ".pgw", ".jgw",
                ".wld", ".xml", ".adf")

_MAX_ENTRY = 256 * 1024 * 1024          # 256 MB per member
_MAX_TOTAL = 512 * 1024 * 1024          # 512 MB per archive
_MAX_MEMBERS = 200
_MAX_DATASETS = 10                       # primary datasets parsed per zip


def parse(path: str) -> MapSpec:
    from ..detect import parse_any      # lazy: avoids a circular import

    out_dir = os.path.splitext(path)[0] + "_unzipped"
    extracted = _extract(path, out_dir)
    primaries = _pick_primaries(extracted)
    if not primaries:
        raise ValueError(
            f"{path}: no supported datasets inside the zip "
            f"(looked for {', '.join(_PRIMARY_EXT[:8])} …)")

    skipped = len(primaries) - _MAX_DATASETS
    specs: List[MapSpec] = []
    failures: List[str] = []
    for p in primaries[:_MAX_DATASETS]:
        try:
            specs.append(parse_any(p))
        except (ValueError, FileNotFoundError) as e:
            failures.append(f"{os.path.basename(p)}: {e}")
    if not specs:
        raise ValueError(f"{path}: nothing inside the zip could be parsed — "
                         + "; ".join(failures[:3]))

    spec = specs[0]
    seen = {l.name for l in spec.layers}
    for other in specs[1:]:
        for lyr in other.layers:
            base = lyr.name
            n = 2
            while lyr.name in seen:
                lyr.name = f"{base}_{n}"
                n += 1
            seen.add(lyr.name)
            spec.layers.append(lyr)
        for note in other.notes:
            if note not in spec.notes:
                spec.notes.append(note)
        if other.crs_epsg != spec.crs_epsg and other.crs_epsg != 4326:
            spec.notes.append(
                f"zip: datasets carry mixed CRS (EPSG:{spec.crs_epsg} vs "
                f"EPSG:{other.crs_epsg}) — everything is projected to "
                f"CONFIG['epsg'] on output; verify it is the right one")

    spec.source_kind = "zip"
    stem = os.path.splitext(os.path.basename(path))[0]
    spec.layout.title = stem.replace("_", " ").replace("-", " ").title()
    spec.layout.export = stem + ".pdf"
    spec.notes.insert(0, f"zip: extracted {len(extracted)} files to {out_dir} — "
                         "the generated script reads from that folder, keep it")
    for f in failures:
        spec.notes.append(f"zip: could not parse {f}")
    if skipped > 0:
        spec.notes.append(f"zip: {skipped} more dataset(s) inside were not "
                          f"parsed (cap is {_MAX_DATASETS}) — extract and run "
                          "them separately if needed")
    return spec


# ---------------------------------------------------------------------------
def _extract(path: str, out_dir: str) -> List[str]:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path}: not a readable zip ({e})") from e
    with z:
        members = [i for i in z.infolist() if not i.is_dir()]
        if len(members) > _MAX_MEMBERS:
            raise ValueError(f"{path}: {len(members)} members — over the "
                             f"{_MAX_MEMBERS}-file safety cap")
        total = 0
        keep = []
        for info in members:
            ext = os.path.splitext(info.filename)[1].lower()
            if ext not in _PRIMARY_EXT + _SIDECAR_EXT:
                continue
            if info.file_size > _MAX_ENTRY:
                continue                          # skip absurd members
            total += info.file_size
            if total > _MAX_TOTAL:
                raise ValueError(f"{path}: archive expands past the "
                                 f"{_MAX_TOTAL // (1024*1024)} MB safety cap")
            keep.append(info)
        os.makedirs(out_dir, exist_ok=True)
        out_paths = []
        for info in keep:
            # traversal-safe flat-ish extraction: keep one level of structure
            safe_name = info.filename.replace("\\", "/")
            parts = [p for p in safe_name.split("/") if p not in ("", ".", "..")]
            if not parts:
                continue
            rel = os.path.join(*parts[-2:]) if len(parts) > 1 else parts[0]
            dest = os.path.join(out_dir, rel)
            if not os.path.abspath(dest).startswith(os.path.abspath(out_dir)):
                continue
            os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as dst:
                dst.write(src.read(_MAX_ENTRY))
            out_paths.append(dest)
    return out_paths


def _pick_primaries(paths: List[str]) -> List[str]:
    """Order matters: real spatial data first, pictures/pdfs last so a
    zipped shapefile with a preview.png maps the shapefile, not the png."""
    rank = {ext: i for i, ext in enumerate(_PRIMARY_EXT)}
    prims = [p for p in paths
             if os.path.splitext(p)[1].lower() in rank]
    return sorted(prims, key=lambda p: rank[os.path.splitext(p)[1].lower()])
