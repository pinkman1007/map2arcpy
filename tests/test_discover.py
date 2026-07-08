"""Discover — what maps can I make from this data? (v0.16.0)"""
import json
import os
import urllib.request

from map2arcpy import discover
from map2arcpy.parsers import data
from map2arcpy.cli import main
from conftest import EXAMPLES


def test_geojson_suggests_choropleth_categories_and_boundary():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    sug = discover.suggest(spec)
    titles = [s["title"] for s in sug]
    assert any("Choropleth of population" in t for t in titles)
    assert any("Categories by zone" in t for t in titles)
    assert any("Boundary map" in t for t in titles)
    # each carries a runnable depict
    ch = next(s for s in sug if "Choropleth of population" in s["title"])
    assert "choropleth of population" in ch["depict"]
    assert "density map" not in ch["depict"]        # not a false theme here


def test_field_inventory_captured():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    fields = {f["name"]: f["type"] for f in spec.layers[0].extra["fields"]}
    assert fields["population"] == "numeric" and fields["zone"] == "text"


def test_temporal_rasters_suggest_series_and_change(monkeypatch):
    from map2arcpy.spec import MapSpec, Layer, Renderer
    spec = MapSpec(source_kind="zip")
    for y in (2015, 2016, 2017, 2018):
        spec.layers.append(Layer(name=f"rain_{y}", source=f"rain_{y}.tif",
                                 kind="raster", renderer=Renderer(type="stretch")))
    sug = discover.suggest(spec)              # no profile -> SA assumed available
    titles = [s["title"] for s in sug]
    assert any("time series" in t for t in titles)
    assert any("Change map" in t for t in titles)
    change = next(s for s in sug if "Change map" in s["title"])
    assert change["requires"] == "Spatial Analyst" and change["systems"]


def test_theme_hint_from_names():
    from map2arcpy.spec import MapSpec, Layer, Renderer
    spec = MapSpec(source_kind="shapefile",
                   layers=[Layer(name="carbon_stock", source="carbon.shp",
                                 kind="vector", geometry="polygon",
                                 renderer=Renderer(type="simple", color="#ccc"),
                                 extra={"fields": [{"name": "agb_mgha", "type": "numeric"}]})])
    sug = discover.suggest(spec)
    assert any("carbon storage map" in s["depict"] for s in sug)


def test_spatial_analyst_gated_by_profile():
    from map2arcpy.spec import MapSpec, Layer, Renderer
    spec = MapSpec(source_kind="zip",
                   layers=[Layer(name=f"r{y}", source=f"r{y}.tif", kind="raster",
                                 renderer=Renderer(type="stretch"))
                           for y in (2015, 2016, 2017)])
    no_sa = {"pro_version": "3.4", "extensions": {"Spatial Analyst": False}}
    titles = [s["title"] for s in discover.suggest(spec, no_sa)]
    assert not any("Change map" in t for t in titles)     # gated out


def test_cli_discover(capsys):
    rc = main(["discover", os.path.join(EXAMPLES, "wards.geojson")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "maps you can make" in out
    assert "Choropleth of population" in out
    assert "--depict" in out


def test_discover_endpoint():
    import threading, tempfile
    from http.server import ThreadingHTTPServer
    from map2arcpy import server as srv
    srv._Handler.web_enabled = False
    srv._Handler.upload_dir = tempfile.mkdtemp()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        path = os.path.abspath(os.path.join(EXAMPLES, "wards.geojson"))
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/discover",
            data=json.dumps({"path": path}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode())
        assert j["suggestions"] and any("Choropleth" in s["title"] for s in j["suggestions"])
    finally:
        httpd.shutdown()
