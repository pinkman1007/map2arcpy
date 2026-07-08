"""Style overrides (v0.8.0) — 'how should the map look'."""
import ast
import json
import os
import urllib.request

from map2arcpy.style import apply_style
from map2arcpy.parsers import nl, data
from map2arcpy.generator import generate
from map2arcpy.cli import main
from conftest import EXAMPLES


def test_ramp_and_color_overrides():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_style(spec, {"ramp": "blues", "color": "1A9641"})
    lyr = spec.layers[0]
    assert lyr.renderer.ramp[0] == "#EFF3FF"          # blues, not viridis
    assert any("ramp=blues" in n for n in spec.notes)


def test_layout_overrides_and_export_rename():
    spec = nl.parse("map of parks.shp titled 'Old Name', epsg 32644")
    apply_style(spec, {"title": "Guntur Parks 2026", "page": "A3L",
                       "dpi": 600, "format": "png",
                       "legend": False, "north_arrow": False})
    assert spec.layout.title == "Guntur Parks 2026"
    assert spec.layout.export == "guntur_parks_2026.png"
    assert spec.layout.page == "A3L" and spec.layout.dpi == 600
    assert spec.layout.legend is False and spec.layout.north_arrow is False
    assert spec.layout.scale_bar is True             # untouched


def test_basemap_set_and_removed():
    spec = nl.parse("map of parks.shp on a topographic basemap, epsg 32644")
    apply_style(spec, {"basemap": "imagery"})
    bms = [l for l in spec.layers if l.kind == "basemap"]
    assert len(bms) == 1 and bms[0].source == "Imagery"
    apply_style(spec, {"basemap": "none"})
    assert not [l for l in spec.layers if l.kind == "basemap"]


def test_invalid_values_skip_with_notes_never_break():
    spec = nl.parse("map of parks.shp, epsg 32644")
    apply_style(spec, {"page": "A0", "dpi": 9999, "ramp": "rainbow",
                       "color": "greenish", "basemap": "Mars"})
    assert sum("style override skipped" in n for n in spec.notes) == 5
    ast.parse(generate(spec, strict=False))          # still generates


def test_cli_style_flags(tmp_path):
    out = tmp_path / "styled.py"
    rc = main(["generate", "map of parks.shp, epsg 32644", "-o", str(out),
               "--title", "Styled Map", "--ramp", "greens", "--page", "A3L",
               "--basemap", "none", "--format", "png", "--no-profile"])
    assert rc == 0
    code = out.read_text()
    assert "'title': 'Styled Map'" in code
    assert "'page': 'A3L'" in code
    assert "addBasemap" not in code


def test_server_accepts_style(tmp_path):
    import threading, tempfile
    from http.server import ThreadingHTTPServer
    from map2arcpy import server as srv
    srv._Handler.web_enabled = False
    srv._Handler.upload_dir = tempfile.mkdtemp()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/generate",
            data=json.dumps({"input": "map of parks.shp, epsg 32644",
                             "style": {"title": "Via API", "dpi": 150}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode())
        assert j["spec"]["layout"]["title"] == "Via API"
        assert j["spec"]["layout"]["dpi"] == 150
        assert j["filename"] == "via_api.py"
    finally:
        httpd.shutdown()


def test_new_ramps_and_reverse():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_style(spec, {"ramp": "spectral"})
    first = spec.layers[0].renderer.ramp[0]
    apply_style(spec, {"reverse_ramp": True})
    assert spec.layers[0].renderer.ramp[-1] == first        # reversed
    assert any("reverse_ramp" in n for n in spec.notes)


def test_classes_and_method():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_style(spec, {"classes": 7, "classify": "quantile"})
    r = spec.layers[0].renderer
    assert r.class_count == 7 and r.class_method == "quantile"
    code = generate(spec, strict=False)
    assert "apply_graduated(lyr, 'population', [], " in code
    assert "'quantile', 7)" in code
    ast.parse(code)


def test_transparency_outline_marker():
    from map2arcpy.parsers import nl as _nl
    spec = _nl.parse("show sites.shp in red, epsg 32644")
    spec.layers[-1].geometry = "point"
    apply_style(spec, {"transparency": 40, "outline": "1F4E5F",
                       "outline_width": 1.5, "marker_size": 8})
    r = spec.layers[-1].renderer
    assert r.transparency == 40 and r.outline == "#1F4E5F"
    assert r.outline_width == 1.5 and r.marker_size == 8.0
    code = generate(spec, strict=False)
    assert "apply_simple(lyr, '#D7191C', '#1F4E5F', 40, 1.5, 8.0)" in code
    ast.parse(code)


def test_invalid_new_values_skip():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_style(spec, {"classes": 99, "classify": "wizardry",
                       "transparency": 500, "outline_width": 50})
    assert sum("skipped" in n for n in spec.notes) == 4


def test_ramp_interp_in_runtime():
    from map2arcpy.generator import runtime
    five = runtime._ramp_interp(["#000000", "#FFFFFF"], 5)
    assert len(five) == 5 and five[0] == "#000000" and five[-1] == "#FFFFFF"
    assert five[2] == "#808080"                             # midpoint grey


def test_cli_new_style_flags(tmp_path):
    out = tmp_path / "s.py"
    rc = main(["generate", os.path.join(EXAMPLES, "wards.geojson"), "-o", str(out),
               "--no-profile", "--classes", "6", "--classify", "natural_breaks",
               "--reverse-ramp", "--transparency", "30"])
    assert rc == 0
    code = out.read_text()
    assert "'natural_breaks', 6)" in code
    ast.parse(code)
