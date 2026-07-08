"""Pro-environment probe + profile-aware generation (v0.7.0)."""
import ast
import json
import os

import pytest

from map2arcpy import probe
from map2arcpy.generator import generate
from map2arcpy.parsers import nl
from map2arcpy.cli import main


def _fake_profile(tmp_path, monkeypatch, **over):
    prof = {"profile_schema": 1, "captured": "2026-07-08T12:00:00",
            "pro_version": "3.3.1", "product": "ArcGISPro",
            "license": "Advanced",
            "extensions": {"Spatial Analyst": True},
            "portal_signed_in": True, "portal_url": "https://www.arcgis.com/",
            "project": {"path": "C:/GIS/city.aprx", "default_gdb": "C:/GIS/city.gdb",
                        "maps": [{"name": "Map", "layers": ["wards"]}]}}
    prof.update(over)
    p = tmp_path / "pro_profile.json"
    p.write_text(json.dumps(prof))
    monkeypatch.setenv("MAP2ARCPY_PROFILE", str(p))
    return prof


def test_probe_script_is_valid_python():
    src = probe.probe_script()
    ast.parse(src)
    assert "GetInstallInfo" in src and "CheckExtension" in src
    assert "GetSigninToken" in src and "ArcGISProject" in src


def test_load_profile_and_summary(tmp_path, monkeypatch):
    _fake_profile(tmp_path, monkeypatch)
    prof = probe.load_profile()
    assert prof["pro_version"] == "3.3.1"
    s = probe.summary(prof)
    assert "3.3.1" in s and "portal signed in" in s
    assert probe.pro_version(prof) == (3, 3)
    assert probe.use_classic_tools(prof) is False


def test_missing_or_bad_profile_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MAP2ARCPY_PROFILE", str(tmp_path / "nope.json"))
    assert probe.load_profile() is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("MAP2ARCPY_PROFILE", str(bad))
    assert probe.load_profile() is None


def test_old_pro_gets_classic_tools(tmp_path, monkeypatch):
    prof = _fake_profile(tmp_path, monkeypatch, pro_version="2.6.0")
    assert probe.use_classic_tools(prof) is True
    spec = nl.parse("buffer schools.shp by 500 m and clip to \"city.shp\", epsg 32644")
    code = generate(spec, strict=False, profile=prof)
    ast.parse(code)
    assert "arcpy.analysis.Buffer(" in code and "PairwiseBuffer" not in code
    assert "arcpy.analysis.Clip(" in code and "PairwiseClip" not in code
    assert "layout section (createLayout) needs Pro 3.x" in code


def test_no_portal_comments_out_basemap(tmp_path, monkeypatch):
    prof = _fake_profile(tmp_path, monkeypatch, portal_signed_in=False)
    spec = nl.parse("map of parks.shp on a topographic basemap, epsg 32644")
    code = generate(spec, strict=False, profile=prof)
    ast.parse(code)
    assert "# m.addBasemap('Topographic')" in code
    assert "no portal sign-in" in code


def test_profile_prefills_aprx_template(tmp_path, monkeypatch):
    prof = _fake_profile(tmp_path, monkeypatch)
    spec = nl.parse("map of parks.shp, epsg 32644")
    code = generate(spec, strict=False, profile=prof)
    assert "'aprx_template': 'C:/GIS/city.aprx'" in code
    assert "Matched to your machine" in code


def test_no_profile_generates_tip():
    spec = nl.parse("map of parks.shp, epsg 32644")
    code = generate(spec, strict=False, profile=None)
    assert "PairwiseBuffer" not in code            # no buffer requested anyway
    assert "run `map2arcpy probe`" in code


def test_cli_probe_writes_script_and_show(tmp_path, monkeypatch, capsys):
    out = tmp_path / "probe.py"
    assert main(["probe", "-o", str(out)]) == 0
    ast.parse(out.read_text())
    assert "run it ONCE inside ArcGIS Pro" in capsys.readouterr().out
    _fake_profile(tmp_path, monkeypatch)
    assert main(["probe", "--show"]) == 0
    assert "3.3.1" in capsys.readouterr().out


def test_generate_cli_uses_profile(tmp_path, monkeypatch, capsys):
    _fake_profile(tmp_path, monkeypatch, pro_version="2.6.0")
    out = tmp_path / "s.py"
    assert main(["generate", "buffer wells.shp by 100 m, epsg 32644",
                 "-o", str(out)]) == 0
    assert "using Pro profile" in capsys.readouterr().err
    assert "arcpy.analysis.Buffer(" in out.read_text()
    # and --no-profile ignores it
    assert main(["generate", "buffer wells.shp by 100 m, epsg 32644",
                 "-o", str(out), "--no-profile"]) == 0
    assert "PairwiseBuffer" in out.read_text()
