import json
import os
import zipfile

from map2arcpy.parsers import cim
from conftest import EXAMPLES


def test_lyrx_unique_values():
    spec = cim.parse(os.path.join(EXAMPLES, "landuse.lyrx"))
    assert spec.source_kind == "lyrx"
    assert len(spec.layers) == 1
    lyr = spec.layers[0]
    assert lyr.name == "Land_Use_2026"
    assert lyr.source.replace("\\", "/") == "C:/GIS/city.gdb/landuse_2026"
    assert lyr.definition_query == "AREA_HA > 0.1"
    assert lyr.label_field == "LU_CLASS"
    r = lyr.renderer
    assert r.type == "unique"
    assert r.field == "LU_CLASS"
    assert r.color_map["Residential"] == "#FFEBAF"
    assert r.color_map["Industrial"] == "#9C9C9C"


def test_mapx_map_definition(tmp_path):
    mapx = {
        "type": "CIMMapDocument",
        "mapDefinition": {
            "type": "CIMMap",
            "name": "Flood Zones",
            "spatialReference": {"wkid": 32644},
        },
        "layerDefinitions": [{
            "type": "CIMFeatureLayer",
            "name": "zones",
            "featureTable": {
                "dataConnection": {
                    "type": "CIMStandardDataConnection",
                    "workspaceConnectionString": "DATABASE=/data/flood.gdb",
                    "dataset": "zones",
                },
            },
            "renderer": {"type": "CIMSimpleRenderer", "symbol": {
                "symbol": {"symbolLayers": [
                    {"type": "CIMSolidFill",
                     "color": {"type": "CIMRGBColor", "values": [44, 123, 182, 100]}}]}}},
        }],
    }
    p = tmp_path / "flood.mapx"
    p.write_text(json.dumps(mapx))
    spec = cim.parse(str(p))
    assert spec.crs_epsg == 32644
    assert spec.layout.title == "Flood Zones"
    assert spec.layers[0].source == "/data/flood.gdb/zones"
    assert spec.layers[0].renderer.color == "#2C7BB6"


def test_aprx_zip_package(tmp_path):
    inner = {
        "type": "CIMMap",
        "name": "Packaged Map",
        "spatialReference": {"wkid": 3857},
        "layerDefinitions": [],
    }
    # .aprx = zip of CIM JSON documents
    p = tmp_path / "proj.aprx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("GISProject.json", json.dumps({"type": "CIMGISProject"}))
        z.writestr("Map/map.json", json.dumps(inner))
        z.writestr("thumbnail.png", b"\x89PNG not-json")
    spec = cim.parse(str(p))
    assert spec.source_kind == "aprx"
    assert spec.crs_epsg == 3857
    assert spec.layout.title == "Packaged Map"
