import struct

from map2arcpy.parsers import image


def _write_geotiff(path, epsg=32644):
    """Tiny valid little-endian TIFF with GeoTIFF tags (no image strips)."""
    # entries: ModelPixelScale (33550), ModelTiepoint (33922), GeoKeyDir (34735)
    n = 3
    ifd_offset = 8
    data_start = ifd_offset + 2 + n * 12 + 4
    scale = (30.0, 30.0, 0.0)
    tie = (0.0, 0.0, 0.0, 700000.0, 1960000.0, 0.0)
    # GeoKeyDirectory: version 1,1,0, 2 keys: model type + ProjectedCSTypeGeoKey
    geokeys = (1, 1, 0, 2,  1024, 0, 1, 1,  3072, 0, 1, epsg)
    off_scale = data_start
    off_tie = off_scale + 8 * len(scale)
    off_keys = off_tie + 8 * len(tie)

    buf = struct.pack("<2sHI", b"II", 42, ifd_offset)
    buf += struct.pack("<H", n)
    buf += struct.pack("<HHII", 33550, 12, len(scale), off_scale)
    buf += struct.pack("<HHII", 33922, 12, len(tie), off_tie)
    buf += struct.pack("<HHII", 34735, 3, len(geokeys), off_keys)
    buf += struct.pack("<I", 0)                       # next IFD
    buf += struct.pack("<%dd" % len(scale), *scale)
    buf += struct.pack("<%dd" % len(tie), *tie)
    buf += struct.pack("<%dH" % len(geokeys), *geokeys)
    path.write_bytes(buf)


def test_geotiff_epsg_and_affine(tmp_path):
    p = tmp_path / "lulc.tif"
    _write_geotiff(p, epsg=32644)
    spec = image.parse(str(p))
    assert spec.crs_epsg == 32644
    assert any("GeoTIFF tags" in n for n in spec.notes)
    assert spec.layers[0].kind == "raster"


def test_world_file_georeferencing(tmp_path):
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n fake")
    (tmp_path / "scan.pgw").write_text("2.5\n0\n0\n-2.5\n700000\n1960000\n")
    spec = image.parse(str(p))
    assert any("world file" in n for n in spec.notes)


def test_plain_image_is_marked_experimental(tmp_path):
    p = tmp_path / "photo.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    spec = image.parse(str(p))
    assert any("EXPERIMENTAL" in n for n in spec.notes)


def test_plain_pdf_scaffold(tmp_path):
    p = tmp_path / "figure.pdf"
    p.write_bytes(b"%PDF-1.7 nothing geospatial here")
    spec = image.parse(str(p))
    assert spec.source_kind == "pdf"
    assert any("EXPERIMENTAL" in n for n in spec.notes)


def test_geospatial_pdf_detected(tmp_path):
    p = tmp_path / "geo.pdf"
    p.write_bytes(b"%PDF-1.7 ... /LGIDict << >> ...")
    spec = image.parse(str(p))
    assert any("geospatial PDF detected" in n for n in spec.notes)
