"""ZIP input (v0.5.0) — zipped shapefiles, mixed archives, safety guards."""
import ast
import json
import struct
import zipfile

import pytest

from map2arcpy import convert
from map2arcpy.parsers import archive


def _shp_bytes(shp_type=5):
    header = struct.pack(">i", 9994) + b"\x00" * 20 + struct.pack(">i", 50)
    header += struct.pack("<i", 1000) + struct.pack("<i", shp_type)
    header += struct.pack("<4d", 83.1, 17.6, 83.5, 17.9) + struct.pack("<4d", 0, 0, 0, 0)
    return header


def _dbf_bytes(fields):
    n = len(fields)
    head = bytearray(32); head[0] = 3
    struct.pack_into("<H", head, 8, 33 + 32 * n)
    struct.pack_into("<H", head, 10, 1)
    body = b""
    for fname, ftype in fields:
        d = bytearray(32)
        d[0:11] = fname.encode()[:11].ljust(11, b"\x00")
        d[11] = ord(ftype)
        body += bytes(d)
    return bytes(head) + body + b"\r"


PRJ = ('PROJCS["UTM44",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID['
       '"WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
       'UNIT["Degree",0.017453]],PROJECTION["Transverse_Mercator"],'
       'UNIT["Meter",1.0],AUTHORITY["EPSG",32644]]')


def test_zipped_shapefile(tmp_path):
    z = tmp_path / "wards_export.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("wards.shp", _shp_bytes())
        zz.writestr("wards.dbf", _dbf_bytes([("WARD_NAME", "C"), ("POP", "N")]))
        zz.writestr("wards.prj", PRJ)
        zz.writestr("preview.png", b"\x89PNG fake")   # must NOT become the map
    spec = archive.parse(str(z))
    assert spec.source_kind == "zip"
    assert spec.crs_epsg == 32644
    shp_layers = [l for l in spec.layers if l.source.endswith(".shp")]
    assert shp_layers and shp_layers[0].renderer.field == "POP"
    assert any("_unzipped" in n for n in spec.notes)
    code = convert(str(z))
    ast.parse(code)
    assert "wards.shp" in code


def test_zip_with_multiple_datasets_merges_layers(tmp_path):
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "P"},
         "geometry": {"type": "Point", "coordinates": [83.2, 17.7]}}]}
    z = tmp_path / "bundle.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("roads.shp", _shp_bytes(3))
        zz.writestr("roads.prj", PRJ)
        zz.writestr("data/pois.geojson", json.dumps(gj))
    spec = archive.parse(str(z))
    names = {l.name for l in spec.layers}
    assert "roads" in names and "pois" in names
    assert len(spec.layers) >= 2


def test_zip_without_data_errors(tmp_path):
    z = tmp_path / "docs.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("readme.docx", b"not spatial")
    with pytest.raises(ValueError, match="no supported datasets"):
        archive.parse(str(z))


def test_zip_traversal_entries_are_neutralised(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../../escape.geojson",
                    '{"type":"FeatureCollection","features":[]}')
    spec = archive.parse(str(z))                 # parses, but INSIDE out_dir
    out_dir = str(tmp_path / "evil_unzipped")
    assert all(l.source.startswith(out_dir) for l in spec.layers)
    assert not (tmp_path.parent.parent / "escape.geojson").exists()


def test_zip_member_cap(tmp_path):
    z = tmp_path / "many.zip"
    with zipfile.ZipFile(z, "w") as zz:
        for i in range(201):
            zz.writestr(f"f{i}.csv", "lat,lon\n1,2\n")
    with pytest.raises(ValueError, match="safety cap"):
        archive.parse(str(z))
