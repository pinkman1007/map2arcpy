"""The log doctor: deterministic diagnosis of run logs and run reports."""
import json

from map2arcpy.doctor import diagnose
from map2arcpy.detect import parse_any
from map2arcpy.generator import generate
from map2arcpy.parsers import steps

GOOD_LOG = """[10:41:01] INFO | Spatial Analyst checked out
[10:41:02] INFO | 9 raster(s): PERSIANN_1y2015.tif, ...
[10:41:07] INFO | cell_statistics done -> results.gdb/period_average
[10:41:12] INFO | output layer 'period_average' added to your open map 'Map'
[10:41:15] INFO | EXPORT OK -> C:/x/decadal.pdf (1834 KB)
[10:41:15] INFO | ALL DONE"""

FAIL_LOG = """[10:40:01] INFO | ENVIRONMENT SETUP
Traceback (most recent call last):
  ...
FileNotFoundError: Missing inputs:
  - C:/GIS/rain/rain_2015.tif"""


def test_clean_run_diagnosed_as_success():
    d = diagnose(GOOD_LOG)
    assert d["success"] is True
    assert "COMPLETED" in d["summary"]
    goods = [f for f in d["findings"] if f["severity"] == "good"]
    assert len(goods) >= 3          # checkout, cellstats, added-to-map, export


def test_missing_inputs_diagnosed_with_fix():
    d = diagnose(FAIL_LOG)
    assert d["success"] is False
    err = d["findings"][0]
    assert err["severity"] == "error"
    assert "CONFIG['sources']" in err["fix"]


def test_field_typo_and_sa_and_wildcard_rules():
    d = diagnose("[1] WARN | field 'pop_densty' not found on 'wards'")
    assert any("field" in f["what"] for f in d["findings"])
    d = diagnose("SystemExit: This analysis needs the Spatial Analyst extension")
    assert any("Spatial Analyst" in f["what"] for f in d["findings"])
    d = diagnose("SystemExit: no rasters matched: 'C:/rain/x_20*.tif'")
    assert any("wildcard" in f["what"] for f in d["findings"])


def test_run_report_json_paste_works():
    rep = json.dumps({"generator": "map2arcpy", "success": True,
                      "events": GOOD_LOG.splitlines()})
    d = diagnose(rep)
    assert d["success"] is True


def test_unknown_error_still_flagged():
    d = diagnose("RuntimeError: something exotic happened")
    assert d["success"] is None or d["success"] is False
    assert any(f["severity"] == "error" for f in d["findings"])


def test_empty_input_is_honest():
    assert diagnose("")["success"] is None


def test_generated_scripts_write_run_report():
    code = generate(parse_any("map of wards.geojson titled 'X'"), strict=False)
    assert "write_run_report(work_dir, success=True)" in code
    assert "success=False, error=_e" in code
    code2 = generate(steps.parse(
        '1. decadal average of "C:/r/rain_20*.tif"\n2. rainfall map'),
        strict=False)
    assert "run_report.json" in code2
