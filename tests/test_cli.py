import ast
import json
import os

from map2arcpy.cli import main
from conftest import EXAMPLES


def test_generate_to_file(tmp_path, capsys):
    out = tmp_path / "script.py"
    spec_out = tmp_path / "spec.json"
    rc = main(["generate", os.path.join(EXAMPLES, "describe_choropleth.txt"),
               "-o", str(out), "--spec", str(spec_out)])
    assert rc == 0
    code = out.read_text()
    ast.parse(code)
    spec = json.loads(spec_out.read_text())
    assert spec["crs_epsg"] == 32644
    assert "script ->" in capsys.readouterr().err


def test_generate_from_inline_description(capsys):
    rc = main(["generate", "buffer wells.shp by 250 m, epsg 32643, titled 'Well Buffers'"])
    assert rc == 0
    code = capsys.readouterr().out
    ast.parse(code)
    assert "'250 Meters'" in code


def test_inspect_outputs_spec_json(capsys):
    rc = main(["inspect", os.path.join(EXAMPLES, "wards.geojson")])
    assert rc == 0
    out = capsys.readouterr().out
    body = out.split("\n", 1)[1]
    spec = json.loads(body)
    assert spec["source_kind"] == "geojson"


def test_examples_list_and_run(capsys):
    assert main(["examples", "--list"]) == 0
    assert "choropleth" in capsys.readouterr().out
    assert main(["examples", "--run", "buffer"]) == 0
    ast.parse(capsys.readouterr().out)


def test_missing_input_fails_cleanly(capsys):
    rc = main(["generate", "no_such_file.aprx"])
    assert rc == 1
    assert "map2arcpy:" in capsys.readouterr().err
