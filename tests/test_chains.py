"""Analysis chains: raster ops, methodology notes, auto-injection."""
import ast

from map2arcpy.detect import parse_any
from map2arcpy.generator import generate
from map2arcpy.generator.emit_gpd import generate_gpd
from map2arcpy.parsers import steps
from map2arcpy.spec import MapSpec, Layer, Renderer
from map2arcpy import intent

RECIPE = """1. decadal average of "C:/GIS/rain/rain_20*.tif"
2. rainfall map
3. titled 'Decadal Average Rainfall 2011-2020'
4. A3 landscape
5. export pdf at 300 dpi"""


def test_decadal_average_recipe_full_chain():
    spec = steps.parse(RECIPE, name_hint="decadal rain")
    ops = spec.operations
    assert [o.tool for o in ops] == ["cell_statistics"]
    assert ops[0].params["stat"] == "MEAN"
    assert ops[0].params["pattern"] == "C:/GIS/rain/rain_20*.tif"
    # the output is a stretch raster wearing the rainfall convention (blues)
    out = next(l for l in spec.layers if l.name == "decadal_average")
    assert out.kind == "raster" and out.renderer.type == "stretch"
    assert out.renderer.ramp_name == "blues"
    # methodology is stated
    assert any("ANALYSIS METHOD" in n and "Cell Statistics" in n
               for n in spec.notes)
    # the wildcard did NOT become a bogus loadable layer
    assert not any("*" in (l.source or "") for l in spec.layers)


def test_decadal_script_emits_sa_and_cellstats():
    code = generate(steps.parse(RECIPE), strict=False)
    ast.parse(code)
    assert "need_sa()" in code
    assert "expand_rasters('C:/GIS/rain/rain_20*.tif')" in code
    assert "arcpy.sa.CellStatistics(_in, 'MEAN', 'DATA')" in code
    assert "ANALYSIS METHOD" in code
    assert code.count("# TODO") == 0


def test_injection_from_uploaded_year_rasters():
    """The dashboard flow: 10 uploaded annual rasters + a product phrase."""
    spec = MapSpec(source_kind="data")
    for y in range(2011, 2021):
        spec.layers.append(Layer(name=f"rain_{y}",
                                 source=f"C:/GIS/rain/rain_{y}.tif",
                                 kind="raster", renderer=Renderer(type="stretch")))
    intent.apply_intent(spec, "decadal average rainfall map")
    op = next(o for o in spec.operations if o.tool == "cell_statistics")
    assert len(op.inputs) == 10 and op.params["stat"] == "MEAN"
    assert any("period average injected" in n for n in spec.notes)
    # the input epochs stay loaded but hidden; the average is drawn
    assert all(not l.visible for l in spec.layers if l.name.startswith("rain_2"))
    ast.parse(generate(spec, strict=False))


def test_no_injection_without_multiple_year_rasters():
    spec = MapSpec(source_kind="data")
    spec.layers.append(Layer(name="rain_2020", source="r2020.tif", kind="raster"))
    intent.apply_intent(spec, "decadal average rainfall map")
    assert not any(o.tool == "cell_statistics" for o in spec.operations)
    assert any("averaging step is missing" in n for n in spec.notes)


def test_terrain_distance_zonal_ops():
    spec = parse_any("terrain slope hillshade map from dem.tif")
    assert {o.tool for o in spec.operations} == {"slope", "hillshade"}
    code = generate(spec, strict=False)
    assert "arcpy.sa.Slope" in code and "arcpy.sa.Hillshade" in code

    spec = parse_any("distance to rivers.shp")
    assert [o.tool for o in spec.operations] == ["euc_distance"]

    spec = parse_any("zonal statistics of rainfall.tif by wards.shp")
    op = spec.operations[0]
    assert op.tool == "zonal_stats" and op.inputs == ["wards", "rainfall"]
    # zonal output is a table — never a drawable layer
    assert not any(l.name == "zonal_table" for l in spec.layers)


def test_gpd_backend_cell_statistics_real_and_others_honest():
    code = generate_gpd(steps.parse(RECIPE), strict=False)
    ast.parse(code)
    assert "np.nanmean" in code and "rasterio" in code
    code = generate_gpd(parse_any("slope from dem.tif"), strict=False)
    ast.parse(code)
    assert "not supported in the geopandas backend" in code


def test_outputs_copied_to_users_open_map():
    code = generate(steps.parse(RECIPE), strict=False)
    assert "'outputs_to_active_map': True" in code
    assert "user_map = active_map(aprx)" in code
    assert "copy_outputs_to(user_map, m, ['decadal_average'])" in code
    # no analysis ops -> the MAIN section emits no copy call
    code2 = generate(parse_any("map of wards.geojson titled 'Plain'"), strict=False)
    main2 = code2.split("# MAIN")[-1]
    assert "copy_outputs_to(user_map" not in main2
