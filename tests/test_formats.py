"""New-format parsers (v0.4.0) — every fixture is synthesised in-test."""
import ast
import os
import sqlite3
import struct
import zipfile

import pytest

from map2arcpy import convert, parse_any
from map2arcpy.parsers import data, image


# ---------------------------------------------------------------- rasters
def test_ascii_grid(tmp_path):
    p = tmp_path / "dem.asc"
    p.write_text("ncols 4\nnrows 3\nxllcorner 700000\nyllcorner 1960000\n"
                 "cellsize 30\nNODATA_value -9999\n1 2 3 4\n5 6 7 8\n9 8 7 6\n")
    (tmp_path / "dem.prj").write_text(
        'PROJCS["UTM44",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
        'SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
        'UNIT["Degree",0.017453]],PROJECTION["Transverse_Mercator"],'
        'UNIT["Meter",1.0],AUTHORITY["EPSG",32644]]')
    spec = image.parse(str(p))
    assert spec.source_kind == "ascii-grid"
    assert spec.crs_epsg == 32644
    assert any("cell size 30" in n for n in spec.notes)
    assert spec.layers[0].kind == "raster"


def test_srtm_hgt(tmp_path):
    p = tmp_path / "N17E083.hgt"
    p.write_bytes(b"\x00\x01" * (1201 * 1201))
    spec = image.parse(str(p))
    assert spec.crs_epsg == 4326
    assert spec.extent == [83, 17, 84, 18]
    assert any("3 arc-second" in n for n in spec.notes)


def _classic_netcdf_bytes():
    """Hand-build a minimal CDF-1 header: dims lon/lat, vars lon/lat/pr."""
    def name(s):
        b = s.encode()
        pad = (4 - len(b) % 4) % 4
        return struct.pack(">I", len(b)) + b + b"\x00" * pad

    out = b"CDF\x01" + struct.pack(">I", 0)              # magic + numrecs
    out += struct.pack(">II", 0x0A, 2)                   # dim_list, 2 dims
    out += name("lon") + struct.pack(">I", 4)
    out += name("lat") + struct.pack(">I", 3)
    out += struct.pack(">II", 0, 0)                      # no global atts
    out += struct.pack(">II", 0x0B, 3)                   # var_list, 3 vars
    for vname, dimids in (("lon", [0]), ("lat", [1]), ("pr", [1, 0])):
        out += name(vname) + struct.pack(">I", len(dimids))
        for d in dimids:
            out += struct.pack(">I", d)
        out += struct.pack(">II", 0, 0)                  # no var atts
        out += struct.pack(">III", 5, 4, 0)              # type float, vsize, begin
    return out


def test_netcdf_classic_variable_detection(tmp_path):
    p = tmp_path / "rain.nc"
    p.write_bytes(_classic_netcdf_bytes())
    spec = image.parse(str(p))
    lyr = spec.layers[0]
    assert lyr.extra["variable"] == "pr"                 # data var, not a dim
    assert lyr.extra["x_dim"] == "lon" and lyr.extra["y_dim"] == "lat"
    code = convert(str(p))
    ast.parse(code)
    assert "add_netcdf(m, results" in code and "'pr'" in code


def test_netcdf4_hdf5_scaffolds(tmp_path):
    p = tmp_path / "modern.nc"
    p.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 64)
    spec = image.parse(str(p))
    assert spec.layers[0].extra["variable"] == "TODO_VARIABLE"
    assert any("netCDF-4" in n for n in spec.notes)


def test_arcgrid_folder(tmp_path):
    grid = tmp_path / "lulcgrid"
    grid.mkdir()
    (grid / "hdr.adf").write_bytes(b"\x00" * 32)
    (grid / "dblbnd.adf").write_bytes(struct.pack(">4d", 7e5, 1.9e6, 7.1e5, 2e6))
    spec = parse_any(str(grid))
    assert spec.source_kind == "arcgrid"
    assert any("ArcGrid extent" in n for n in spec.notes)


# ---------------------------------------------------------------- vectors
def test_geopackage(tmp_path):
    p = tmp_path / "city.gpkg"
    con = sqlite3.connect(p)
    con.executescript("""
      CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INT);
      CREATE TABLE gpkg_geometry_columns (table_name TEXT, geometry_type_name TEXT);
      CREATE TABLE gpkg_spatial_ref_sys (srs_id INT, organization TEXT,
                                         organization_coordsys_id INT);
      INSERT INTO gpkg_spatial_ref_sys VALUES (100, 'EPSG', 32644);
      INSERT INTO gpkg_contents VALUES ('wards', 'features', 100);
      INSERT INTO gpkg_geometry_columns VALUES ('wards', 'MULTIPOLYGON');
      CREATE TABLE wards (fid INTEGER, geom BLOB, ward_name TEXT, pop_density REAL);
    """)
    con.commit(); con.close()
    spec = data.parse(str(p))
    assert spec.source_kind == "geopackage"
    assert spec.crs_epsg == 32644
    lyr = spec.layers[0]
    assert lyr.source.endswith("city.gpkg/main.wards")
    assert lyr.geometry == "polygon"
    assert lyr.renderer.type == "graduated" and lyr.renderer.field == "pop_density"
    assert lyr.label_field == "ward_name"


KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>A</name><Point><coordinates>83.2,17.7</coordinates></Point></Placemark>
  <Placemark><name>B</name><Point><coordinates>83.3,17.8</coordinates></Point></Placemark>
</Document></kml>"""


def test_kml_and_kmz(tmp_path):
    k = tmp_path / "sites.kml"
    k.write_text(KML)
    spec = data.parse(str(k))
    assert spec.crs_epsg == 4326
    assert spec.layers[0].geometry == "point"
    assert any("2 placemarks" in n.lower() for n in spec.notes)
    z = tmp_path / "sites.kmz"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("doc.kml", KML)
    spec2 = data.parse(str(z))
    assert spec2.layers[0].geometry == "point"
    code = convert(str(z))
    ast.parse(code)
    assert "add_kml(m, work_dir" in code


def test_gpx(tmp_path):
    p = tmp_path / "survey.gpx"
    p.write_text("""<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">
      <wpt lat="17.7" lon="83.2"><name>P1</name></wpt>
      <wpt lat="17.8" lon="83.3"><name>P2</name></wpt></gpx>""")
    spec = data.parse(str(p))
    assert spec.layers[0].geometry == "point"
    code = convert(str(p))
    assert "add_gpx(m, results" in code


def test_csv_with_coordinates(tmp_path):
    p = tmp_path / "sensors.csv"
    p.write_text("site,latitude,longitude,pm25\nA,17.71,83.21,42\nB,17.72,83.25,55\n")
    spec = data.parse(str(p))
    lyr = spec.layers[0]
    assert lyr.extra == {"x_field": "longitude", "y_field": "latitude"}
    assert lyr.renderer.type == "graduated" and lyr.renderer.field == "pm25"
    code = convert(str(p))
    ast.parse(code)
    assert "add_csv_xy(m, results" in code and "'longitude'" in code


def test_csv_without_coordinates_scaffolds(tmp_path):
    p = tmp_path / "budget.csv"
    p.write_text("dept,amount\nparks,100\nroads,200\n")
    spec = data.parse(str(p))
    assert spec.layers[0].extra["x_field"] == "TODO_X_FIELD"
    assert any("no obvious coordinate columns" in n for n in spec.notes)


def test_cad_dxf(tmp_path):
    p = tmp_path / "layout_plan.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    spec = data.parse(str(p))
    assert spec.source_kind == "cad"
    assert any("CAD" in n for n in spec.notes)


# ------------------------------------------------------- everything compiles
@pytest.mark.parametrize("maker", ["asc", "hgt", "gpkg", "csv"])
def test_all_new_formats_generate_valid_python(tmp_path, maker):
    if maker == "asc":
        p = tmp_path / "x.asc"
        p.write_text("ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\ncellsize 1\n"
                     "NODATA_value -9999\n1 2\n3 4\n")
    elif maker == "hgt":
        p = tmp_path / "N17E083.hgt"
        p.write_bytes(b"\x00\x01" * (1201 * 1201))
    elif maker == "gpkg":
        p = tmp_path / "x.gpkg"
        con = sqlite3.connect(p)
        con.executescript(
            "CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INT);"
            "CREATE TABLE gpkg_geometry_columns (table_name TEXT, geometry_type_name TEXT);"
            "CREATE TABLE gpkg_spatial_ref_sys (srs_id INT, organization TEXT,"
            " organization_coordsys_id INT);"
            "INSERT INTO gpkg_contents VALUES ('a', 'features', 0);"
            "INSERT INTO gpkg_geometry_columns VALUES ('a', 'POINT');"
            "CREATE TABLE a (fid INTEGER, geom BLOB);")
        con.commit(); con.close()
    else:
        p = tmp_path / "x.csv"
        p.write_text("lat,lon,v\n1,2,3\n")
    ast.parse(convert(str(p)))
