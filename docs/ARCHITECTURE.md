# Architecture

## The pipeline

```
input ──> detect.detect_kind() ──> parsers.* ──> MapSpec ──> generator.emit ──> script.py
                                                    │
                                          inspect / --spec / hand-edit
```

Everything left of `script.py` is pure stdlib Python and fully unit-tested;
`arcpy` only exists inside the generated script, and even there it is
imported lazily so the script byte-compiles in any environment ("the arcpy
boundary").

## MapSpec — the intermediate representation

`spec.py` defines five small dataclasses:

* **MapSpec** — CRS, layers, operations, layout, provenance notes
* **Layer** — name, source (path / URL / basemap name), kind
  (vector | raster | basemap | service), renderer, definition query, labels
* **Renderer** — simple | unique | graduated | stretch, with colours as hex
* **Operation** — one geoprocessing step (tool key + inputs + params);
  the tool table `KNOWN_OPS` maps keys to `arcpy.analysis.Pairwise*` etc.
* **Layout** — title, page (A4P…LetterL), dpi, surrounds, export target

The IR is deliberately tiny, JSON round-trippable (`to_json`/`from_json`),
and validated (`validate()` returns a list of human-readable problems).
Everything a parser cannot resolve is recorded in `notes` rather than
guessed — notes surface as `# TODO` comments in the generated script.

## Parsers

| module | input | approach |
|---|---|---|
| `parsers/nl.py` | plain English | a regex grammar over the working vocabulary of map requests: operations, distances+units, EPSG/UTM phrases, named colours and ramps, basemap names, page/dpi/format, quoted titles. Operations chain (buffer → clip picks up the buffer output). |
| `parsers/cim.py` | `.lyrx`, `.mapx`, `.aprx` | reads ArcGIS Pro's CIM JSON directly. `.aprx` is a ZIP package: every JSON entry is harvested. Data connections (`workspaceConnectionString` + `dataset`) become paths; `CIMUniqueValueRenderer` / `CIMClassBreaksRenderer` / `CIMSimpleRenderer` become Renderers, with RGB/HSV/CMYK colour conversion. |
| `parsers/data.py` | GeoJSON, shapefile, web-map JSON | profiles the data and *proposes* cartography. The shapefile reader is pure stdlib: `.shp` header (geometry type, bbox), `.dbf` field descriptors, `.prj` WKT → EPSG. Web maps translate `operationalLayers` drawingInfo renderers. |
| `parsers/image.py` | GeoTIFF, PNG/JPG (+world file), PDF | extracts what is deterministically recoverable: TIFF IFD GeoTIFF tags (33550/33922/34735 → affine + EPSG), six-parameter world files, geospatial-PDF markers. Plain pictures produce an explicitly-experimental scaffold, never fake layers. |

`detect.py` sniffs which parser applies (extension first, then JSON shape),
and refuses to reinterpret a typo'd filename as prose.

## Generator

`generator/emit.py` compiles the IR section by section:

1. header docstring (how to run, provenance, TODOs)
2. `CONFIG` dict — the only part a user should need to edit
3. inlined runtime (below)
4. `main()` — geoprocessing ops in order, map assembly (basemap first),
   per-layer symbology, layout, verified export

Generated code is `ast.parse`-checked before being returned.

`generator/runtime.py` holds the runtime between `BEGIN/END RUNTIME` markers
and is inlined verbatim, so generated scripts are single-file. It carries the
production patterns: `setup_env` (scratch/results GDBs, CRS lock, parallel
factor), `audit_exists` (one consolidated missing-input failure), CIM
symbology helpers (`apply_unique`, `apply_graduated`), programmatic
`arcpy.mp` layout with graceful surround fallbacks, and `export_layout` with
a did-it-actually-write check. Because the module is real importable Python
(not a string template), the test suite exercises it directly.

## Testing strategy

* every example input must generate, and the output must `ast.parse`
* parser goldens: NL grammar cases, a real `.lyrx` fixture, `.mapx`/`.aprx`
  built in-test, shapefiles synthesised byte-by-byte, a GeoTIFF written from
  raw struct-packed IFD entries
* CLI end-to-end through `main()` with exit codes
* CI runs the suite on Python 3.9 / 3.11 / 3.12 (the Pythons ArcGIS Pro ships)

What is *not* tested here: live arcpy behaviour. The first run inside
ArcGIS Pro is a shakedown by design, and the scripts' QA gates make failures
loud and early.
