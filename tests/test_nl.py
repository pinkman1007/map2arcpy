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


def test_buffer_then_dissolve_by_field_stays_separate():
    spec = nl.parse("buffer roads.shp by 500 m and dissolve by ward, epsg 32644")
    tools = [(o.tool, o.inputs) for o in spec.operations]
    assert tools == [("buffer", ["roads"]), ("dissolve", ["buffered"])]
    assert spec.operations[0].params["dissolve"] == "NONE"
    assert spec.operations[1].params["field"] == "ward"


def test_bare_dissolve_folds_into_buffer():
    spec = nl.parse("buffer roads.shp by 500 m, dissolved, epsg 32644")
    assert [o.tool for o in spec.operations] == ["buffer"]
    assert spec.operations[0].params["dissolve"] == "ALL"


def test_where_clause_survives_commas_and_quotes():
    spec = nl.parse("from sites.shp select where \"type IN ('A', 'B') AND ward = 3\"")
    sel = next(o for o in spec.operations if o.tool == "select")
    assert sel.params["where"] == "type IN ('A', 'B') AND ward = 3"


def test_without_surrounds():
    spec = nl.parse("map of parks.shp without a legend, no scale bar and without the north arrow")
    assert spec.layout.legend is False
    assert spec.layout.north_arrow is False
    assert spec.layout.scale_bar is False


def test_erase_and_intersect_ops():
    s1 = nl.parse("erase wetlands.shp from parcels.shp, epsg 32644")
    op = next(o for o in s1.operations if o.tool == "erase")
    assert op.inputs == ["parcels", "wetlands"]      # Erase(in, erase_features)
    s2 = nl.parse("intersect parks.shp with wards.shp, epsg 32644")
    assert any(o.tool == "intersect" and o.inputs == ["parks", "wards"]
               for o in s2.operations)
