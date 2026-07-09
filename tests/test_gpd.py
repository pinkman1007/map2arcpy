"""The GeoPandas (open-source) backend: same MapSpec, no Esri."""
import ast
import os
import subprocess
import sys

import pytest

from conftest import EXAMPLES
from map2arcpy.detect import parse_any
from map2arcpy.generator.emit_gpd import generate_gpd
from map2arcpy.parsers import steps

WARDS = os.path.join(EXAMPLES, "wards.geojson")


def _gen(text):
    return generate_gpd(parse_any(text), strict=False)


def test_description_generates_parsing_script():
    code = _gen("choropleth of population from wards.geojson using greens, "
                "labeled with ward_name, titled 'Density', A4 landscape")
    ast.parse(code)
    assert "geopandas" in code and "import arcpy" not in code
    assert "cmap='Greens'" in code or 'cmap="Greens"' in code
    assert "column='population'" in code
    assert "figsize" in code


def test_all_ops_translate():
    code = _gen("buffer schools.shp by 500 m, clip to boundary.shp, "
                "dissolve by ZONE, select where \"pop > 5\"")
    ast.parse(code)
    for frag in (".buffer(parse_distance_m", "gpd.clip(", ".dissolve(by=",
                 "sql_where("):
        assert frag in code, f"missing {frag}"


def test_op_outputs_not_in_sources():
    code = _gen("buffer schools.shp by 500 m, titled 'B'")
    # 'buffered' is computed by the op, never a CONFIG source to load
    src_block = code.split("'sources': {")[1].split("}")[0]
    assert "buffered" not in src_block
    assert "schools" in src_block


def test_strict_raises_on_invalid_spec():
    spec = parse_any("titled 'Nothing At All'")
    spec.layers = []
    with pytest.raises(ValueError):
        generate_gpd(spec, strict=True)


def test_recipe_with_steps_keeps_banners():
    recipe = ("1. load wards.shp\n2. clip to city.shp\n"
              "3. choropleth of pop_density\n4. titled 'R', A4 portrait")
    code = generate_gpd(steps.parse(recipe), strict=False)
    ast.parse(code)
    assert "# ==== STEP 2: clip to city.shp" in code


@pytest.mark.skipif(
    not os.environ.get("M2A_RUN_GPD"),
    reason="end-to-end execution needs geopandas+matplotlib (set M2A_RUN_GPD=1)")
def test_end_to_end_execution(tmp_path):
    recipe = (f'1. load "{WARDS}"\n'
              "2. choropleth of population using greens\n"
              "3. label by ward_name\n"
              "4. titled 'E2E', A4 portrait\n"
              "5. export png at 100 dpi")
    code = generate_gpd(steps.parse(recipe, name_hint="e2e"), strict=False)
    script = tmp_path / "m.py"
    script.write_text(code, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (tmp_path / "e2e.png").exists()
