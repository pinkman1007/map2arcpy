# Examples

Every file here is a valid input to `map2arcpy generate`:

| file | input kind | try |
|---|---|---|
| `describe_choropleth.txt` | natural language | `map2arcpy generate examples/describe_choropleth.txt -o out.py` |
| `describe_buffer.txt` | natural language | `map2arcpy generate examples/describe_buffer.txt -o out.py` |
| `wards.geojson` | GeoJSON data | `map2arcpy generate examples/wards.geojson -o out.py` |
| `landuse.lyrx` | ArcGIS Pro layer file (CIM) | `map2arcpy generate examples/landuse.lyrx -o out.py` |
| `webmap.json` | ArcGIS web map JSON | `map2arcpy generate examples/webmap.json -o out.py` |

Or skip files entirely and pass a description straight in:

```bash
map2arcpy generate "Buffer hospitals.shp by 1 km in EPSG:32644, clip to \"district.shp\", titled 'Hospital Coverage'" -o coverage.py
```

Use `map2arcpy inspect <input>` to see the intermediate MapSpec JSON without
generating code.
