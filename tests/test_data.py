import os
import struct

from map2arcpy.parsers import data
from conftest import EXAMPLES


def test_geojson_suggests_choropleth_and_labels():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    assert spec.crs_epsg == 4326
    lyr = spec.layers[0]
    assert lyr.geometry == "polygon"
    assert lyr.renderer.type == "graduated"
    assert lyr.renderer.field == "population"
    assert lyr.label_field == "ward_name"
    assert any("graduated" in n for n in spec.notes)


def test_webmap_layers_and_renderers():
    spec = data.parse(os.path.join(EXAMPLES, "webmap.json"))
    assert spec.source_kind == "webmap"
    assert spec.crs_epsg == 3857
    names = [l.name for l in spec.layers]
    assert "basemap" in names and "Health_Clinics" in names and "Ward_Boundaries" in names
    wards = next(l for l in spec.layers if l.name == "Ward_Boundaries")
    assert wards.renderer.type == "graduated"
    assert wards.renderer.field == "POP_DENS"
    assert wards.renderer.breaks == [50, 150, 500]
    clinics = next(l for l in spec.layers if l.name == "Health_Clinics")
    assert clinics.renderer.color == "#C00000"
    assert clinics.source.startswith("https://")


def _write_shapefile(tmp_path, name="parcels", shp_type=5, prj=None, fields=()):
    # minimal .shp header (100 bytes)
    shp = tmp_path / f"{name}.shp"
    header = struct.pack(">i", 9994) + b"\x00" * 20 + struct.pack(">i", 50)
    header += struct.pack("<i", 1000) + struct.pack("<i", shp_type)
    header += struct.pack("<4d", 83.1, 17.6, 83.5, 17.9) + struct.pack("<4d", 0, 0, 0, 0)
    shp.write_bytes(header)
    # minimal .dbf with field descriptors
    if fields:
        dbf = tmp_path / f"{name}.dbf"
        n = len(fields)
        head = bytearray(32)
        head[0] = 3
        struct.pack_into("<H", head, 8, 33 + 32 * n)
        struct.pack_into("<H", head, 10, 1)
        body = b""
        for fname, ftype in fields:
            d = bytearray(32)
            d[0:11] = fname.encode("ascii")[:11].ljust(11, b"\x00")
            d[11] = ord(ftype)
            body += bytes(d)
        dbf.write_bytes(bytes(head) + body + b"\r")
    if prj:
        (tmp_path / f"{name}.prj").write_text(prj)
    return str(shp)


def test_shapefile_with_prj_and_numeric_field(tmp_path):
    prj = ('PROJCS["WGS_1984_UTM_Zone_44N",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
           'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
           'UNIT["Degree",0.0174532925199433],AUTHORITY["EPSG",4326]],'
           'PROJECTION["Transverse_Mercator"],UNIT["Meter",1.0],AUTHORITY["EPSG",32644]]')
    shp = _write_shapefile(tmp_path, prj=prj,
                           fields=[("NAME", "C"), ("AREA_HA", "N")])
    spec = data.parse(shp)
    assert spec.crs_epsg == 32644                # last AUTHORITY wins
    lyr = spec.layers[0]
    assert lyr.geometry == "polygon"
    assert lyr.renderer.type == "graduated"
    assert lyr.renderer.field == "AREA_HA"
    assert lyr.label_field == "NAME"


def test_shapefile_without_prj_guesses_geographic(tmp_path):
    shp = _write_shapefile(tmp_path, name="noprj")
    spec = data.parse(shp)
    assert spec.crs_epsg == 4326
    assert any("guessed" in n for n in spec.notes)
