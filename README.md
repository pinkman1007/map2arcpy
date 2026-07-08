# map2arcpy

**Turn any map into an executable ArcGIS Pro Python script.**

`map2arcpy` is a deterministic, rule-based converter ("compiler", if you
like): give it a map in almost any form and it emits a standalone,
ready-to-run **arcpy** script that rebuilds that map inside ArcGIS Pro —
geoprocessing, symbology, layout, and export included. No LLM, no API key,
no network, no dependencies: pure Python stdlib, so it runs anywhere,
including directly inside ArcGIS Pro's conda environment or an offline
government workstation.

```
  plain-English description ─┐
  .aprx / .lyrx / .mapx ─────┤                       ┌─> geoprocessing (Buffer, Clip, …)
  GeoJSON / shapefile ───────┼──> MapSpec (JSON) ──> │   CIM symbology (unique / graduated)
  ArcGIS web-map JSON ───────┤    inspectable,       │   layout (title, legend, N-arrow, scale)
  GeoTIFF / image / PDF ─────┘    hand-editable      └─> export (PDF / PNG, 300 dpi)
```

## Quick start

```bash
pip install git+https://github.com/pinkman1007/map2arcpy.git

# from a plain-English description
map2arcpy generate "Buffer schools.shp by 500 meters, clip to \"city_boundary.shp\", \
  UTM zone 44N, titled 'School Walkability', A3 landscape" -o walkability.py

# from an ArcGIS Pro layer file
map2arcpy generate landuse.lyrx -o landuse_map.py

# from data — it inspects fields and proposes the cartography
map2arcpy generate wards.geojson -o wards_map.py

# from a whole project package
map2arcpy generate project.aprx -o rebuild.py
```

Then run the generated script inside ArcGIS Pro (Python window, notebook, or
`propy.bat`). Everything a human might need to change — paths, EPSG, colours,
page size — sits in one `CONFIG` dict at the top of the script.

## What it accepts

| input | what happens |
|---|---|
| plain English (`"choropleth of population from wards.geojson…"`) | a regex grammar extracts sources, operations (buffer/clip/dissolve/select/spatial-join…), colours & ramps, CRS, page, export format |
| `.lyrx` / `.mapx` / `.aprx` | the CIM JSON is parsed: data connections, definition queries, label fields, and unique-value / class-breaks / simple renderers are carried over faithfully, colours and all |
| `.geojson` / `.shp` | the data is profiled (geometry type, attribute fields — the shapefile reader is pure stdlib, header + `.dbf` + `.prj`) and sensible cartography is proposed: numeric field → choropleth, low-cardinality text → categories |
| ArcGIS web-map JSON | `operationalLayers` become service layers with their drawingInfo renderers translated |
| GeoTIFF / image + world file / PDF | georeferencing is recovered from TIFF tags, world files, or geospatial-PDF markers; the script scaffolds a map around the raster. *Plain screenshots are experimental — pixels can't be reverse-engineered into layers by rules, and the tool says so instead of guessing.* |
| a saved MapSpec `.json` | regenerated exactly — the IR is the contract |

## The honest bits

* The **generator** runs anywhere; the **generated scripts** need ArcGIS Pro
  3.x (`arcpy.mp` programmatic layouts). Scripts import arcpy lazily and
  byte-compile without it, so they can be linted/CI-checked anywhere.
* Nothing is silently guessed. Whatever the parsers cannot resolve becomes an
  explicit `# TODO` in the script and a note in the spec — `--strict` turns
  those into hard errors instead.
* Generated code is syntax-checked (`ast.parse`) before it is handed over;
  the CLI refuses to emit code that does not compile.
* No arcpy geoprocessing runs at generate time — the first run inside Pro is
  the shakedown. QA gates are built into every script (consolidated
  missing-input audit, CRS lock, export verification) so failures are loud
  and early.

## Three commands

```bash
map2arcpy generate <input> [-o script.py] [--spec spec.json] [--strict]
map2arcpy inspect  <input>          # show the intermediate MapSpec JSON
map2arcpy examples [--list|--run NAME]
```

`--spec` writes the intermediate representation next to the script; edit it
by hand and feed it back to `generate` for full control between "what the
parser understood" and "what the script does".

Python API, one call:

```python
import map2arcpy
code = map2arcpy.convert("buffer wells.shp by 250 m, EPSG:32643")
```

## Architecture

Parsers normalise every input into a tiny JSON-serialisable IR (`MapSpec`:
layers, renderers, operations, layout); a template generator compiles the IR
into a single-file script with an inlined runtime (env setup, QA gates, CIM
symbology helpers, programmatic layout, verified export). Details in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and the gap register — what this tool knowingly does not do — in [docs/GAPS.md](docs/GAPS.md), and the failure-mode register in [docs/PREMORTEM.md](docs/PREMORTEM.md). The arcpy idioms in the runtime
are distilled from production ArcGIS Pro figure pipelines.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The whole test suite (parsers, generator, CLI) runs without ArcGIS Pro.

## Roadmap

* raster geoprocessing ops (zonal stats, reclassify, hillshade)
* `.pyt` Python-toolbox output so it runs from the Geoprocessing pane
* optional LLM adapter for free-form descriptions beyond the grammar —
  strictly as a *front-end* that emits the same auditable MapSpec

## License

MIT © 2026 UDAAR

*Not affiliated with or endorsed by Esri. "ArcGIS", "ArcGIS Pro" and "arcpy"
are trademarks of Esri, referenced here only to describe interoperability.*
