from map2arcpy.parsers import nl


def test_buffer_clip_crs_title_page():
    spec = nl.parse("Buffer schools.shp by 500 meters and clip to \"city_boundary.shp\". "
                    "Use UTM zone 44N. Titled 'School Walkability', A3 landscape, export to PNG.")
    assert spec.crs_epsg == 32644
    tools = [o.tool for o in spec.operations]
    assert tools == ["buffer", "clip"]
    buf = spec.operations[0]
    assert buf.params["distance"] == "500 Meters"
    assert buf.inputs == ["schools"]
    clip = spec.operations[1]
    assert clip.inputs[0] == "buffered"          # chains onto the buffer output
    assert clip.inputs[1] == "city_boundary"
    assert spec.layout.title == "School Walkability"
    assert spec.layout.page == "A3L"
    assert spec.layout.export.endswith(".png")


def test_choropleth_ramp_basemap_labels():
    spec = nl.parse("Choropleth map of population using viridis from wards.geojson "
                    "on a light gray basemap, labeled with ward_name, 300 dpi")
    final = [l for l in spec.layers if l.kind != "basemap"][-1]
    assert final.renderer.type == "graduated"
    assert final.renderer.field == "population"
    assert len(final.renderer.ramp) == 5
    assert final.label_field == "ward_name"
    assert any(l.kind == "basemap" and l.source == "Light Gray Canvas" for l in spec.layers)
    assert spec.layout.dpi == 300


def test_epsg_and_km_units():
    spec = nl.parse("buffer rivers.shp by 1.5 km, EPSG:32643")
    assert spec.crs_epsg == 32643
    assert spec.operations[0].params["distance"] == "1.5 Kilometers"


def test_select_where_and_color():
    spec = nl.parse("Show sites.shp in red, select where \"status = 'ACTIVE'\", wgs84")
    assert spec.crs_epsg == 4326
    sel = [o for o in spec.operations if o.tool == "select"]
    assert sel and "status" in sel[0].params["where"]
    final = [l for l in spec.layers if l.kind != "basemap"][-1]
    assert final.renderer.color == "#D7191C"


def test_no_data_becomes_scaffold_with_notes():
    spec = nl.parse("a pretty map of the city")
    assert spec.layers                       # scaffold layer added
    assert any("scaffold" in n or "not found" in n for n in spec.notes)


def test_gdb_feature_class_path():
    spec = nl.parse("unique values by LU_CLASS from C:/GIS/city.gdb/landuse, epsg 32644")
    assert any(l.source.endswith("city.gdb/landuse") for l in spec.layers)
    final = [l for l in spec.layers if l.kind != "basemap"][-1]
    assert final.renderer.type == "unique"
    assert final.renderer.field == "LU_CLASS"
