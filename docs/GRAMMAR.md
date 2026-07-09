# The map2arcpy grammar — every phrase the parser understands

map2arcpy's natural-language parser is a deterministic, rule-based grammar —
not an LLM. That means it recognises a **specific vocabulary**, exactly and
repeatably, and anything outside it becomes a visible `# TODO` instead of a
guess. This page is the complete vocabulary. Every example below works both
as part of a one-line description and as a line in a step-by-step recipe.

> **Recipes:** paste numbered or bulleted lines (`1.` `2)` `-` `*` `Step 3:`)
> and each line is parsed with this grammar and applied **in order** — later
> steps see earlier results. Unparseable steps get a `did you mean …?`
> suggestion. See the README's recipe section.

---

## Data sources

Any token ending in a supported extension becomes a layer. Quote paths that
contain spaces.

```
load wards.shp
map of "C:\GIS\data\district boundary.geojson"
D:\data\city.gdb\roads
rainfall_2020.tif
```

Recognised extensions: `.shp .geojson .json .gpkg .kml .kmz .gpx .csv .lyrx
.dxf .tif .tiff .img .nc .asc .hgt .jp2 .dem .flt .bil` and `.gdb\dataset`
paths. Rasters get a stretched renderer automatically.

The verbs `load / add / open / use / import` are optional — a bare path is
enough.

## Geoprocessing operations

Operations chain: each output feeds the next step automatically.

| you write | tool emitted |
|---|---|
| `buffer roads.shp by 500 m` (m, km, miles, feet) | PairwiseBuffer |
| `buffer wards.shp by 1 km dissolved` | PairwiseBuffer (dissolve ALL) |
| `clip to boundary.shp` | PairwiseClip (subject = your data / prior output) |
| `dissolve by DISTRICT` | PairwiseDissolve on that field |
| `erase water.shp from wards.shp` | PairwiseErase |
| `intersect wards.shp and flood.shp` | PairwiseIntersect |
| `union a.shp and b.shp` / `merge a.shp and b.shp` | Union / Merge |
| `spatial join wards.shp and schools.shp` | SpatialJoin |
| `select where "pop_density > 50"` | Select (quote the SQL) |

(If your ArcGIS Pro profile reports a version below 2.7, the classic
non-Pairwise tools are emitted instead — run `map2arcpy probe` once.)

## Raster analysis (Spatial Analyst)

These emit `arcpy.sa` tools; the script checks the extension out (and stops
with a clear message if it isn't licensed).

| you write | tool emitted |
|---|---|
| `decadal average of "C:\rain\rain_20*.tif"` (wildcard or folder) | Cell Statistics MEAN over the matched rasters |
| `sum of "C:\rain\*.tif"` / `maximum of …` / `minimum of …` | Cell Statistics SUM / MAXIMUM / MINIMUM |
| `slope from dem.tif` | Slope (DEGREE) |
| `hillshade from dem.tif` | Hillshade (az 315, alt 45) |
| `terrain slope hillshade map from dem.tif` | both, ready to drape |
| `distance to rivers.shp` | Euclidean Distance surface |
| `zonal statistics of rainfall.tif by wards.shp` | Zonal Statistics as Table (MEAN) |

**Product knowledge (analysis chains):** naming a *product* attaches its
methodology to the script header — e.g. `decadal average rainfall map`
states "Spatial Analyst > Local > Cell Statistics (MEAN) …" — and in the
unambiguous case acts on it: upload several **year-tagged rasters** together
and ask for an average-rainfall product, and the MEAN over exactly those
epochs is added automatically (inputs stay loaded but hidden; the average is
drawn with the rainfall convention).

## Symbology

| you write | result |
|---|---|
| `choropleth of pop_density` | graduated colours on that field |
| `graduated by AREA using blues` | graduated + named ramp |
| `shaded by elevation` / `heat map of density` | graduated (synonyms) |
| `unique values by landuse` / `categorized by zone` | one colour per class |
| `in red` / `dark green fill` | single-colour symbol |
| `using viridis` | ramp (applies to raster stretch too) |
| `with 5 classes, natural breaks` | class count + method (via style panel / intent) |

**Named ramps:** greens, blues, reds, oranges, purples, greys, viridis,
magma, plasma, cividis — diverging: red_blue, brown_teal, red_yellow_green,
spectral, pink_green.

**Named colours:** red, green, blue, dark green, dark blue, light blue,
light green, orange, yellow, purple, pink, magenta, cyan, teal, brown,
beige, black, white, gray/grey.

## Labels

```
label by ward_name
labelled with NAME
```

## Selection / definition queries

```
select where "pop_density > 50"
filter where "landuse = 'residential'"
```

Quote the whole SQL expression — commas and quotes inside survive.

## CRS

```
EPSG:32644
UTM zone 44N
web mercator
WGS84
```

No CRS mentioned → EPSG:4326 with a note reminding you to set a projected
CRS for correct buffer distances and areas.

## Basemaps

```
on imagery
over OSM
on a dark gray basemap
```

Recognised: imagery, satellite, imagery hybrid, topographic/topo, streets,
osm/openstreetmap, dark gray/grey, light gray/grey, terrain, oceans,
navigation.

## Layout & export

| you write | effect |
|---|---|
| `titled 'School Walkability'` | map title (quotes required) |
| `A3 landscape` / `A4 portrait` / `letter` | page size + orientation |
| `300 dpi` | export resolution |
| `export pdf` / `as png` / `jpg` | export format |
| `no legend` / `no north arrow` / `no scale bar` | switch elements off |

## Thematic archetypes

Naming a map *type* applies its cartographic conventions (ramp direction,
classification, stretch): `carbon storage map`, `emissions map`, `rainfall
map`, `flood map`, `NDVI / vegetation map`, `terrain map`, `temperature
map`, `LULC map`, `population density map`, `hazard risk map`,
`eco-sensitive zones`, and more.

## Systems analysis (optional)

Tick **systems analysis** in the dashboard (or `"systems": true` via the
API) and the spec gains a causal-context block; year-tagged raster series
also get a behaviour-archetype computation (Limits to Growth, overshoot, …)
at run time.

---

## A full recipe, as a worked example

```
1. load wards.shp
2. clip to district_boundary.shp
3. choropleth of pop_density using greens
4. label by ward_name
5. select where "pop_density > 50"
6. buffer hospitals.shp by 500 m
7. on a light gray basemap
8. EPSG:32644
9. titled 'Dense Wards — Health Access', A3 landscape
10. export pdf at 300 dpi
```

Every operation in the generated script carries a `# ==== STEP n ====`
banner, and the script header carries a step-by-step account of what each
line was understood to mean — so the script reads like the recipe.

## When a step is not understood

It is never silently dropped. You get, in the spec notes **and** in the
script:

```
# TODO (step): STEP 2 NOT UNDERSTOOD — 'crop it to the city area':
#              did you mean: 'clip to boundary.shp'? (vocabulary reference: docs/GRAMMAR.md)
```

The suggestions are deterministic keyword/typo matches against this
vocabulary — examples of the grammar, not guesses about your data.
