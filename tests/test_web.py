"""Web-pass tests — the network is always mocked; CI must never go online."""
import ast
import json
import os

import pytest

from map2arcpy import web
from map2arcpy.parsers import nl
from map2arcpy.generator import generate

VIZAG = {"lat": "17.6868", "lon": "83.2185", "display_name": "Visakhapatnam, AP, India",
         "boundingbox": ["17.5", "17.9", "83.1", "83.4"]}   # s, n, w, e


def fake_fetch_factory(nominatim=None, overpass=None, agol=None):
    def _fake(url, params):
        if "nominatim" in url:
            return nominatim if nominatim is not None else []
        if "overpass" in url:
            return overpass if overpass is not None else {"elements": []}
        if "arcgis" in url:
            return agol if agol is not None else {"results": []}
        raise AssertionError("unexpected URL " + url)
    return _fake


def test_utm_epsg_zones():
    assert web.utm_epsg(17.7, 83.2) == 32644     # Visakhapatnam -> UTM 44N
    assert web.utm_epsg(-33.9, 18.4) == 32734    # Cape Town -> UTM 34S
    assert web.utm_epsg(51.5, -0.1) == 32630     # London -> UTM 30N


def test_geocode_sets_extent_and_utm(monkeypatch):
    monkeypatch.setattr(web, "_fetch_json", fake_fetch_factory(nominatim=[VIZAG]))
    spec = nl.parse("map of parks.shp in Visakhapatnam")
    web.enrich(spec, "map of parks.shp in Visakhapatnam")
    assert spec.extent == [83.1, 17.5, 83.4, 17.9]           # xmin,ymin,xmax,ymax
    assert spec.crs_epsg == 32644                            # auto UTM
    assert any("Nominatim" in n for n in spec.notes)


def test_explicit_epsg_not_overridden_by_web(monkeypatch):
    monkeypatch.setattr(web, "_fetch_json", fake_fetch_factory(nominatim=[VIZAG]))
    spec = nl.parse("map of parks.shp in Visakhapatnam, EPSG:3857")
    web.enrich(spec, "map of parks.shp in Visakhapatnam, EPSG:3857")
    assert spec.crs_epsg == 3857                             # user's choice wins


def test_osm_download_creates_geojson_layer(tmp_path, monkeypatch):
    overpass = {"elements": [
        {"type": "node", "id": 1, "lat": 17.7, "lon": 83.2,
         "tags": {"amenity": "hospital", "name": "KGH"}},
        {"type": "way", "id": 2,
         "geometry": [{"lat": 17.70, "lon": 83.20}, {"lat": 17.70, "lon": 83.21},
                      {"lat": 17.71, "lon": 83.21}, {"lat": 17.70, "lon": 83.20}],
         "tags": {"building": "hospital"}},
    ]}
    monkeypatch.setattr(web, "_fetch_json",
                        fake_fetch_factory(nominatim=[VIZAG], overpass=overpass))
    text = "hospitals from osm in Visakhapatnam"
    spec = nl.parse(text)
    web.enrich(spec, text, str(tmp_path))
    lyr = next(l for l in spec.layers if "hospitals" in l.name)
    assert lyr.source.endswith("hospitals_osm.geojson")
    saved = json.load(open(lyr.source))
    assert len(saved["features"]) == 2
    geoms = {f["geometry"]["type"] for f in saved["features"]}
    assert geoms == {"Point", "Polygon"}                     # node + closed building way
    assert any("OpenStreetMap contributors" in n for n in spec.notes)


def test_osm_without_place_is_skipped_with_note(monkeypatch):
    monkeypatch.setattr(web, "_fetch_json", fake_fetch_factory())
    spec = nl.parse("hospitals from osm")
    web.enrich(spec, "hospitals from osm")
    assert any("needs a place" in n for n in spec.notes)


def test_agol_search_adds_service_layer(monkeypatch):
    agol = {"results": [
        {"title": "Flood Zones AP", "url": "https://svc/x/FeatureServer", "owner": "apgov"},
        {"title": "Flood 2", "url": "https://svc/y/FeatureServer", "owner": "other"},
    ]}
    monkeypatch.setattr(web, "_fetch_json", fake_fetch_factory(agol=agol))
    text = "map of city.shp, find a flood zones layer online"
    spec = nl.parse(text)
    web.enrich(spec, text)
    svc = next(l for l in spec.layers if l.kind == "service")
    assert svc.source == "https://svc/x/FeatureServer/0"
    assert any("other candidates" in n for n in spec.notes)


def test_web_failure_degrades_to_note(monkeypatch):
    def boom(url, params):
        raise OSError("no internet")
    monkeypatch.setattr(web, "_fetch_json", boom)
    spec = nl.parse("map of parks.shp in Visakhapatnam")
    web.enrich(spec, "map of parks.shp in Visakhapatnam")
    assert any("geocoding" in n and "failed" in n for n in spec.notes)
    assert generate(spec, strict=False)                      # still generable


def test_generated_script_converts_geojson_and_sets_extent(tmp_path, monkeypatch):
    overpass = {"elements": [{"type": "node", "id": 1, "lat": 17.7, "lon": 83.2,
                              "tags": {"amenity": "school", "name": "ZPH"}}]}
    monkeypatch.setattr(web, "_fetch_json",
                        fake_fetch_factory(nominatim=[VIZAG], overpass=overpass))
    text = "schools from osm in Visakhapatnam, titled 'Schools'"
    spec = nl.parse(text)
    web.enrich(spec, text, str(tmp_path))
    code = generate(spec, strict=False)
    ast.parse(code)
    assert "geojson_to_fc(" in code and "'POINT'" in code
    assert "set_extent(layout, CONFIG['extent'])" in code
    assert "'extent': [83.1, 17.5, 83.4, 17.9]" in code
