# GAPS — honest limits, known weaknesses, and what to do about them

This file is the gap register for map2arcpy. Read it before promising
anything about live behaviour. Items marked **fixed** were found by the gap
audit and closed; everything else is open and documented deliberately —
silence would read as coverage.

## 1. The big one: no arcpy has ever run here

The generator, parsers, and 40-test suite are pure Python; the generated
scripts' arcpy calls are emitted from templates and syntax-checked, but no
geoprocessing has executed against real data. **The first run inside
ArcGIS Pro is a shakedown.** The scripts' QA gates (consolidated input
audit, CRS lock, export verification) exist precisely so that first run
fails loudly, not silently.

Practical consequences to expect on shakedown:

* `apply_graduated` / `apply_unique` drive `layer.symbology`, which behaves
  slightly differently across Pro 3.0–3.4 (e.g. `breakCount` before vs after
  colour assignment). The helpers catch exceptions and log a WARN rather than
  crash — the map still exports, possibly with default symbology.
* `apply_stretch` is a stub: continuous rasters keep Pro's default stretch;
  the intended ramp is only logged. Classified raster symbology from CIM
  colorizers is not carried over (see §3).
* `aprx.createLayout` / `createMapFrame` / `createMapSurroundElement` need
  ArcGIS Pro **3.x**; on 2.x the layout section will fail. There is no
  version probe in the generated script.
* `m.addBasemap('Topographic')` etc. resolve against the signed-in portal.
  Offline or enterprise portals without Esri basemaps will WARN and continue.

## 2. Natural-language grammar (parsers/nl.py)

Rule-based means bounded. The grammar covers the vocabulary in the README;
outside it, the parser degrades to a scaffold with TODOs, never a guess.

* **One operation of each kind per description.** "Buffer schools by 500 m
  and buffer parks by 200 m" captures only one buffer. Workaround: generate,
  then duplicate the op in the script or edit the `--spec` JSON and re-generate.
* Operation ORDER is fixed (buffer → dissolve → clip → erase → intersect →
  union/merge → spatial-join → select), regardless of the sentence's order.
  For a different order, edit the spec JSON.
* English only. Units: m/km/mi/ft. Dates, scales ("1:25,000") and extent
  phrases ("around Vizag") are not understood.
* Field names with spaces can't be captured by the `by FIELD` patterns.
* ~~"dissolve by FIELD" after a buffer was swallowed into `dissolve=ALL`,
  losing the field~~ — **fixed**, now a separate chained step.
* ~~SQL where-clauses truncated at the first comma~~ — **fixed** for quoted
  clauses (`where "type IN ('A','B')"`); unquoted clauses still stop at
  `, . ;`.
* ~~"without a legend" / "no scale bar" variants ignored~~ — **fixed**.
* ~~intersect / erase / union / merge were in KNOWN_OPS but unreachable from
  NL~~ — **fixed** with basic phrasings ("erase X from Y", "intersect X with Y").

## 3. CIM parsing (.aprx / .lyrx / .mapx)

* Renderers handled: **Simple, UniqueValue, ClassBreaks**. Everything else
  (heat-map, dot-density, chart, proportional, dictionary, attribute-driven
  CIMVisualVariables, raster **colorizers**) degrades to a simple renderer or
  a TODO layer. Labels: only the first label class's field expression.
* `.aprx` handling walks ZIP entries for CIM JSON. It is validated against
  synthetic packages in tests, **not against a wide corpus of real
  Pro-saved projects** — real .aprx internals vary by Pro version and may
  store some documents in non-JSON form. If a real .aprx yields nothing,
  export the map as `.mapx` (Share > Export Map File) — that path is solid.
* Layouts inside .aprx/.mapx (CIMLayout: existing title blocks, multiple
  map frames, insets) are **not** imported; the generated script always
  rebuilds its own programmatic layout. Template `.pagx` support is a
  natural extension (the runtime's layout builder has the hook point).
* Joins/relates, group-layer visibility inheritance, layer time/range
  properties, and definition queries stored as `featureTable.searchOrder`
  alternates are ignored.

## 4. Data parsing (GeoJSON / shapefile / web map)

* Shapefile reader touches header + `.dbf` descriptors + `.prj` only — it
  never reads geometries, so it cannot detect empty or corrupt record
  sections. Missing `.prj` → CRS is **guessed** from the bbox (flagged in
  notes, never silent).
* `.prj` → EPSG uses WKT `AUTHORITY`/`ID` tags. Esri WKT often omits the
  top-level authority; then the guess/note path applies. No full WKT
  parser, by design (zero dependencies).
* GeoJSON: field profiling samples the first 500 features; a numeric field
  appearing only later won't be proposed. The choropleth field choice is
  "first plausible", not statistical.
* Web maps: layers defined by embedded `featureCollection` (no URL) become
  TODO layers — export them to a feature class first. Secured services
  aren't authenticated at parse time; the script relies on Pro's portal
  sign-in. VectorTile basemaps map to the nearest named Esri basemap.
* GeoPackage (.gpkg), KML/KMZ, file-gdb-on-disk introspection, and CSV
  XY tables are recognised as *paths in NL descriptions* but have **no
  data-profiling parser** — the layer is added with a default renderer.

## 5. Images and PDFs

* Deterministically recoverable georeferencing only: GeoTIFF tags
  (little/big-endian classic TIFF; **BigTIFF not supported**), world files,
  geospatial-PDF markers. EPSG comes from GeoKey 3072/2048; user-defined
  (32767) projections are skipped.
* Everything else about a picture of a map — layers, symbols, boundaries —
  is *not recoverable by rules*, and the tool says so in the script instead
  of pretending. That whole quadrant is the natural seam for a future
  vision-model front-end (see README roadmap).

## 6. Generator / runtime

* Vector-only ops today: no Spatial Analyst (zonal stats, reclassify,
  hillshade), no license checkout helper in emitted scripts.
* The emitted geoprocessing uses `Pairwise*` tools (Pro 2.7+); classic
  equivalents are not offered as a fallback.
* Op inputs that are layer names resolve via `CONFIG['sources']`; op inputs
  that are literal paths bypass the CONFIG block (edit two places).
* Generated scripts always rebuild the map from scratch (`removeLayer` on
  non-basemap layers of the first map) — they are figure factories, not
  in-place editors of an existing Pro session.
* `spatial_join`'s output field mapping is arcpy's default (all fields,
  first match); no field-map control from NL or spec yet.

## 7. Web pass (`--web`)

* NL inputs only for now; `--web` on data/CIM inputs prints a skip notice.
* One place per description; the FIRST capitalised "in <Place>" match wins.
  Ambiguous names ("in Hyderabad" — India or Pakistan?) take Nominatim's
  top hit; the matched display name is recorded in a note so you can check.
* Overpass queries use the geocoded bbox as-is: a whole-state place name
  can time out or return tens of thousands of features. No paging, no
  result cap yet. Keep places city-scale.
* OSM ways are converted to lines/polygons locally; multipolygon
  *relations* (complex lakes, boundaries) are skipped.
* Service etiquette is the user's responsibility at scale: Nominatim asks
  for max 1 request/second; Overpass and AGOL have fair-use limits. The
  tool sends one request per feature/place per run and a proper User-Agent,
  but does not queue or throttle beyond that.
* Downloaded GeoJSON is a snapshot; nothing tracks OSM updates.

## 8. Process gaps

* No PyPI release; install is from GitHub.
* CI runs tests + a CLI smoke on 3.9/3.11/3.12 but (by nature) no ArcGIS
  Pro job — a nightly run on a licensed Windows runner is the only way to
  close §1 and is worth doing if this repo gets real users.
* No linting config committed (ruff/flake8) — code is clean but unenforced.

---
*Update this register when a gap closes or a new one is found. A gap
documented is a feature request with an honest label.*
