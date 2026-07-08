# Archetype Study — reading each map type as a system

*Groundwork for the systems-thinking layer (v0.11.0). Before we wire causal
edges between map types, we study each one deeply: what it depicts in
system-dynamics terms, how it is made, why its cartographic conventions
exist, the standards that govern it, and the feedback loops it lives inside.
This document is the reference the code will encode.*

---

## 0. The lens: stocks, flows, drivers, states

System dynamics (Forrester) and systems thinking (Meadows) give four
primitives we can classify every map by:

- **Stock** — an accumulation, the state of the system at an instant (carbon
  *stored*, forest *area*, water *volume*). Maps of stocks answer "how much
  is here now?"
- **Flow** — a rate of change of a stock over time (carbon *sequestered per
  year*, land *converted*, rainfall *per season*). Flow maps answer "what is
  moving, and how fast?" They are almost always *differences* — between two
  dates, or in/out of a place.
- **Driver** — an exogenous or upstream variable that pushes a flow (slope
  drives runoff; built-up density drives heat).
- **State/index** — a composite condition derived from several of the above
  (risk, sensitivity, suitability).

The single most important discipline this gives cartography: **a stock is
symbolised sequentially (light→dark = less→more); a flow is symbolised
divergingly (through a neutral midpoint, because flows have sign — gain vs
loss).** Almost every map error we can catch reduces to "a flow drawn as a
stock" or "a stock differenced without a diverging ramp."

The second discipline is **boundary**: a stock can be summarised inside any
polygon, but a *flow* only makes sense inside its own system boundary
(a watershed for water, an airshed for pollution). Clipping a flow to an
administrative ward is a classic systems error.

The third is **delay**: many loops act with lag (LULC change today →
carbon flux over years → climate feedback over decades). Delays are why
single-date maps mislead and why the tool should nudge toward time series.

---

## 1. Carbon storage / biomass

**SD class:** STOCK (Mg C or Mg C/ha). The quintessential accumulation.

**What it depicts:** carbon currently held in a pool — above-ground biomass,
below-ground, soil organic carbon, dead wood, litter (the IPCC five pools).
Most municipal studies map above-ground biomass converted to carbon.

**Method:** either (a) a look-up — assign a per-hectare carbon density to
each LULC class from field plots or literature, then `carbon = density ×
area` per class (this is the InVEST Carbon model's approach); or (b) a
continuous surface from biomass remote sensing (allometry on canopy
height/NDVI). Data needed: an LULC raster + a carbon-density table, or a
biomass raster.

**Cartographic convention & why:** green sequential ramp, light→dark for
low→high. Green because carbon-in-vegetation reads as "green infrastructure";
sequential because a stock has no natural midpoint — zero is just the low
end, not a pivot. Always print the total (Σ over the AOI) and state units;
a carbon map without a total is decoration.

**Governing references:** IPCC 2006 GL for National GHG Inventories (pool
definitions, Tier 1 default factors); InVEST Carbon Storage & Sequestration
model documentation; ICFRE/FSI biomass factors for Indian forest types.

**Causal role:** carbon *stock* is the accumulation; its inflow is
sequestration (a function of vegetation growth), its outflow is
emissions/loss (a function of LULC conversion, fire, degradation). So the
carbon map is downstream of the LULC map and upstream of the emissions map.

**Feedback loops it sits in:**
- *Reinforcing (vicious):* deforestation → carbon stock ↓ → CO₂ ↑ → warming
  → drought/fire risk ↑ → further vegetation loss.
- *Balancing:* higher CO₂ → (some) fertilisation of plant growth → uptake ↑.
  Weak and saturating; do not overstate.

**Boundary/delay:** stock can be summed in any AOI. But the *change* in
carbon (the flow) lags LULC change — soil carbon especially adjusts over
years to decades. A single-date carbon map hides this; pair with a
sequestration/loss map.

**Pitfalls:** mapping biomass but labelling it carbon (biomass ≈ 2× carbon;
use the 0.47 IPCC factor); mixing pools; ignoring below-ground.

**map2arcpy today:** green ramp on stretch/graduated ✔ (v0.10.0). *Should
add:* the total-over-AOI print (currently only in the older Jaideep lib),
and a link to the LULC input as its driver.

---

## 2. Carbon / GHG emissions

**SD class:** FLOW (t CO₂e / year). A rate, not a stock — the outflow from
carbon stocks plus combustion sources.

**What it depicts:** rate of greenhouse gas release — from energy, transport,
waste, industry (activity-based inventory), or from land-use change (stock
difference × time). Municipal work usually maps sectoral emissions to wards
or a grid.

**Method:** activity data × emission factor per source, allocated spatially
(to roads for transport, to parcels for buildings, to the dump-yard for
waste). Or ΔCarbon-stock / Δt for land-based emissions. Data: activity layers
+ IPCC/CPCB emission factors.

**Cartographic convention & why:** red sequential ramp, low→high (red =
pressure/harm). It is a flow, but a *one-signed* flow (emissions are ≥ 0), so
sequential is correct here, not diverging — the sign discipline says diverge
only when the variable crosses a meaningful zero. *Net* flux (emissions minus
sequestration) DOES cross zero and should diverge.

**Governing references:** IPCC 2006 GL + 2019 Refinement; GPC (Global
Protocol for Community-Scale GHG, the city-inventory standard); CPCB factors.

**Causal role:** the primary *outflow* draining the carbon stock; driven by
LULC (land emissions), density & transport (energy emissions), waste mass
(the dump-yard link to your UAV work).

**Loops:** reinforcing climate loop as above; balancing policy loop
(emissions ↑ → regulation → emissions ↓) which is the whole point of mapping
them.

**Boundary/delay:** Scope matters (GPC Scopes 1/2/3) — a ward's "emissions"
depend on whether you count electricity generated elsewhere. This is a
boundary-critique opportunity par excellence.

**map2arcpy today:** red ramp ✔. *Should add:* the net-flux → diverging
recommendation, and a Scope note.

---

## 3. LULC / land use & land cover

**SD class:** STATE (categorical) — the current configuration of the system.
Its *change* (§5) is the master flow that drives carbon, runoff, heat, and
biodiversity all at once.

**What it depicts:** every cell/parcel classified into a land class
(built-up, cropland, forest, water, barren…). The keystone map — most other
themes are functions of it.

**Method:** supervised/unsupervised classification of satellite imagery, or
digitised parcels. Always paired with an **accuracy assessment** (confusion
matrix → overall accuracy + Cohen's Kappa) — an unaudited LULC map is
inadmissible in a DPR.

**Cartographic convention & why:** categorical (unique-value) symbology, with
*conventional* class colours, not arbitrary ones: built-up red/grey, forest
dark green, cropland yellow/tan, water blue, barren grey. Convention matters
because readers decode land-use maps pre-attentively — a blue "forest" would
mislead. India: the NRSC LULC 50k/250k legend and URDPFI master-plan colour
codes are the reference palettes.

**Governing references:** NRSC/ISRO LULC classification scheme; URDPFI 2014
land-use categories and colour convention (residential yellow, commercial
blue, industrial purple/red, recreational green, public/semi-public…);
Anderson classification (international).

**Causal role:** **the central driver node.** Built-up ↑ → impervious ↑ →
runoff ↑, infiltration ↓, heat ↑. Forest ↓ → carbon ↓, biodiversity ↓.
Cropland ↔ built-up conversion is the peri-urban story of every Indian city.

**Loops:** urbanisation reinforcing loop (built-up → land value ↑ → more
conversion); the balancing loop is zoning/regulation (the master plan).

**Boundary/delay:** class definitions must be stable across dates or the
change map is noise (§5). Minimum mapping unit matters.

**map2arcpy today:** categorical symbology ✔; asks for the class field.
*Should add:* the conventional URDPFI/NRSC palette as a named ramp, and the
accuracy-assessment reminder (the Jaideep lib has the Kappa math already).

---

## 4. LULC change / loss–gain / difference

**SD class:** FLOW — the rate of change of the LULC state. The master flow.

**What it depicts:** where and how land converted between two epochs
(forest→built-up, cropland→built-up…), usually as a transition matrix + a
change map.

**Method:** post-classification comparison — `Combine(lulc_t1, lulc_t2)` →
read the cross-tab from the VAT; or image differencing for continuous
variables. Requires two **co-registered** rasters (same CRS, same cell grid)
— the tool must gate on this.

**Cartographic convention & why:** **diverging** ramp through a neutral
centre — loss (red) ← no-change (white/grey) → gain (blue/green). Diverging
because change is *signed*: the eye must instantly separate loss from gain,
and the neutral midpoint is meaningful (zero change). This is the textbook
case where a sequential ramp would be a lie.

**Causal role:** the flow that drives the carbon, emissions, biodiversity and
runoff *stocks/states* simultaneously. If the tool understands one causal
fact, it should be this: **change-in-LULC is upstream of almost everything.**

**Loops/delay:** conversion is often irreversible on planning timescales
(a delay of ∞ in the balancing loop) — worth flagging.

**Boundary:** the two dates must share the class scheme AND the grid; a
change map across mismatched rasters is the #1 technical error.

**map2arcpy today:** diverging red_blue ramp ✔. *Should add:* the two-raster
co-registration gate, real `Combine`/differencing generation, and the
transition-matrix output (both exist in the Jaideep lib — port them).

---

## 5. Eco-sensitive zones (ESZ)

**SD class:** STATE/INDEX derived by a DRIVER-distance function — a graded
buffer expressing "sensitivity decays with distance from the protected core."

**What it depicts:** graded zones of development restriction around a
national park / sanctuary / protected feature.

**Method:** multiple-ring buffers around the protected boundary, each ring a
regulation tier. **Standard, verified:** the Supreme Court's 3 June 2022
order mandated a *minimum* 1 km ESZ around protected areas; on **26 April
2023 the Court modified this**, holding that a uniform 1 km buffer cannot
apply nationwide and that site-specific ESZs notified by MoEFCC (often
0–10 km, varying by boundary) prevail — mining is banned within PAs and 1 km
of boundaries. So the tool's default rings (1/5/10 km) are a *sensible
starting scaffold, not a legal fixed rule* — and the note must say so and
point to the site's gazette notification.

**Cartographic convention & why:** graded ramp, most-sensitive (innermost,
red) → least (outermost, green) — the "sensitivity" ramp. Rings, not a smooth
surface, because regulation is tiered and legally discrete.

**Governing references:** Environment (Protection) Act 1986; MoEFCC ESZ
notifications (site-specific); **Supreme Court WP(C) 202/1995, order dated
26-04-2023** (the modification); National Wildlife Action Plan.

**Causal role:** a *balancing* intervention on the urbanisation loop — it is
the regulation that resists built-up encroachment on the ecology stock.

**Boundary/delay:** the buffer must be computed in a **projected CRS**
(metres), never geographic degrees — a distance buffer on lat/long is wrong
by design; the tool must ensure a projected EPSG before buffering.

**map2arcpy today:** multi-ring buffer at 1/5/10 km + sensitivity ramp ✔
(v0.10.0). *Should add:* the projected-CRS gate before the buffer, and the SC
2023 caveat in the note (currently just says "edit distances").

---

## 6. Flood / inundation

**SD class:** STATE (depth/extent now) fed by FLOWS (rainfall in, drainage
out) and shaped by DRIVERS (slope, imperviousness).

**Method:** hydrological/hydraulic modelling (HEC-RAS), or a simpler
terrain-driven proxy — fill→flow-direction→flow-accumulation→depth, or a
height-above-nearest-drainage index. Data: DEM (essential), rainfall,
drainage network, land cover for roughness.

**Cartographic convention & why:** blue sequential, shallow→deep. Blue for
water; sequential because depth is a one-signed stock.

**Causal role — the richest node for systems thinking:** flood risk is
DRIVEN by rainfall intensity (+), slope (− steeper drains faster into valleys
but also concentrates), built-up/impervious fraction (+, less infiltration),
drainage capacity (−), and moderated by green/permeable cover (−). This is
the map that most benefits from "you have data for 2 of 4 drivers" context.

**Loops:** reinforcing urban-flood loop — built-up ↑ → impervious ↑ → runoff
↑ → flooding ↑ → (paradoxically) more hard drainage → downstream flooding ↑.

**Boundary/delay:** **watershed, not ward.** Water obeys topography, not
administration — the canonical boundary-critique case. Delay: upstream
rainfall → downstream peak has a lag (time of concentration).

**map2arcpy today:** blue ramp ✔. *Should add:* the driver-checklist note,
the watershed-boundary critique when clipped to admin units, and (with
Spatial Analyst, which the probe confirms Jaideep has) real flow-accumulation
generation.

---

## 7. Hazard / risk / vulnerability

**SD class:** composite STATE/INDEX. Risk = Hazard × Exposure ×
Vulnerability (the UNDRR/IPCC framing).

**Method:** weighted overlay of driver layers (slope, geology, rainfall,
land use…) normalised to a common scale, combined by weights (often AHP).
Data: the driver layers + a defensible weighting.

**Cartographic convention:** red sequential, low→high risk.

**Causal role:** explicitly a *composite of drivers* — the archetype that
most literally embodies systems thinking, because it is a function of other
maps. The tool should, for a risk map, enumerate the standard components and
note which the user has.

**Pitfalls:** conflating hazard (the threat) with risk (threat × what's
exposed × how fragile) — a common and serious error; and hidden sensitivity
to arbitrary weights (state them).

**map2arcpy today:** red ramp ✔. *Should add:* the Hazard×Exposure×
Vulnerability decomposition note.

---

## 8. Vegetation / NDVI

**SD class:** STATE indicator of the vegetation stock; its *trend* is a flow.

**Method:** `(NIR − Red)/(NIR + Red)` from multispectral imagery; range −1..1.
Data: red + NIR bands.

**Cartographic convention & why:** brown→green diverging-ish ramp (bare/stressed
→ dense/healthy); water and cloud masked. The −1..1 range has a meaningful
low (no vegetation ≈ 0) so a brown-to-green sequential-with-brown-tail is
conventional.

**Causal role:** proxy for the vegetation that *feeds* the carbon stock and
*moderates* heat and runoff — a driver/indicator sitting upstream of carbon,
temperature and flood.

**Delay:** seasonal — a single-date NDVI conflates phenology with land
condition; multi-date compositing matters.

**map2arcpy today:** ndvi ramp ✔ (v0.10.0). *Should add:* the band-math
generation and the seasonality note.

---

## 9. Terrain / elevation / slope

**SD class:** DRIVER (the most exogenous of all — the physical stage).

**Method:** DEM display; derivatives via Spatial Analyst — Slope, Aspect,
Hillshade, Curvature.

**Cartographic convention & why:** hypsometric green(low)→brown(high) tints,
often with a hillshade underlay for depth. Convention is centuries old
(hypsometric tinting) and reads instantly.

**Causal role:** upstream driver of flood (slope→runoff), erosion, drainage,
site suitability, even temperature (lapse rate). Rarely a stock or flow
itself — it *shapes* the flows.

**map2arcpy today:** terrain ramp ✔. *Should add:* Slope/Hillshade generation
(Jaideep lib has `build_terrain`).

**boundary:** watershed derivation needs the DEM to extend beyond the AOI or
edge effects corrupt flow accumulation — a real delay/boundary trap.

## 10. Rainfall / precipitation

**SD class:** FLOW (mm per time) — the primary water *inflow* to every
hydrological system.

**Method:** interpolation of gauge data (IDW/kriging), or gridded products
(IMD 0.25°, your PERSIANN). Data: point gauges or a gridded raster.

**Cartographic convention & why:** blue sequential, dry→wet. **Verified IMD
category thresholds** (for reference breaks): light 0.1–15.5 mm/day, moderate
15.6–64.4, heavy 64.5–115.5, very heavy 115.6–204.4, extremely heavy
≥204.5 mm/day. Using these as class breaks makes a rainfall map speak the
same language as the met department.

**Causal role:** exogenous *driver/inflow* — upstream of flood, vegetation,
carbon (growth), agriculture. The classic external forcing.

**Delay/flow discipline:** annual rasters are stocks-of-accumulated-flow per
year; the *difference* between years (your PERSIANN change map) is the flow's
trend and must diverge.

**map2arcpy today:** blue ramp ✔; your PERSIANN run proved it end-to-end.
*Should add:* IMD-threshold class breaks as an option; temporal-series
detection (→ §12).

## 11. Temperature / heat / LST

**SD class:** STATE (°C now); urban-heat *anomaly* is the derived flow.

**Method:** land-surface temperature from thermal bands (Landsat TIRS split-
window), or air-temp interpolation.

**Cartographic convention & why:** thermal ramp yellow→red→dark-red (warm
colours only) — the near-universal heat convention.

**Causal role:** an *outcome/state* driven by built-up density (+, UHI),
vegetation (−, evapotranspiration cooling), water bodies (−), albedo. The
downstream sink of the urban-heat loop — pairs naturally with LULC and NDVI
as its drivers.

**Loops:** reinforcing UHI loop — heat ↑ → AC demand ↑ → waste heat + power
emissions ↑ → heat ↑.

**map2arcpy today:** thermal ramp ✔. *Should add:* the driver note (density,
NDVI, water).

## 12. Density (population / built-up)

**SD class:** STATE (per km²) — and a master DRIVER of the urban system.

**Method:** count / area per zone (choropleth) or kernel density (surface).
**Normalisation is the whole game** — raw counts on unequal polygons lie;
must be per unit area (or per capita for services).

**Cartographic convention & why:** orange/red sequential, low→high; **always
normalised**, and area-normalised data should use a graduated (not
proportional-symbol) renderer on the polygons.

**Causal role:** the upstream driver — density → impervious → runoff & heat;
density → emissions; density → service demand. With LULC-change, one of the
two master drivers of the whole urban system.

**Pitfalls:** the classic un-normalised choropleth; the modifiable areal unit
problem (results change with zone size — worth a note).

**map2arcpy today:** orange ramp + a normalisation reminder ✔. Good as is.

---

## 13. Synthesis — the causal graph

Reading across the studies, the archetypes form a system, not a list. The
edges (sign in parentheses; "→" = drives/feeds):

```
        RAINFALL ─(+)─┐         TERRAIN/SLOPE ─(+)─┐
                      ▼                            ▼
   DENSITY ─(+)→ LULC-CHANGE ─(+)→ [IMPERVIOUS] ─(+)→ FLOOD
      │  │            │  │                 ▲            ▲
      │  │            │  └─(−carbon)→ CARBON STOCK      │
      │  │            │                    │(outflow)   │
      │  │            │                    ▼            │
      │  │            └─(−veg)→ NDVI/VEG ─(−)───────────┘
      │  │                          │(−cooling)
      │  └─(+)→ EMISSIONS           ▼
      └─(+heat)──────────────→ TEMPERATURE/UHI
                                    ▲
   ECO-SENSITIVE ZONES ─(−, balancing regulation)─ resists ─ DENSITY/LULC-CHANGE
   HAZARD/RISK = f(FLOOD, SLOPE, LULC, RAINFALL, DENSITY)   ← composite of the above
```

Three readings fall out of this:

1. **Two master drivers** — *LULC-change* and *density* — sit upstream of
   almost everything. A tool that knows this can, for any requested map, name
   the drivers the user should map alongside it.
2. **Every arrow is a note we can generate.** Ask for a flood map → "driven by
   rainfall(+), slope(+), imperviousness/density(+), drainage(−), vegetation(−);
   you supplied data for N of these." That is systems thinking delivered as
   cartographic advice, deterministically.
3. **The loops are the narrative.** UHI loop, urban-flood loop, deforestation-
   carbon-climate loop — each can print as a "SYSTEMS CONTEXT" block so every
   map ships with the causal story a DPR chapter needs.

## 14. What this means for map2arcpy (the build list this study justifies)

Gaps-only, note-based, deterministic — never overriding the user:

- **Causal-context notes** — a `CAUSAL_GRAPH` table (the edges above); for each
  archetype, emit "drivers you should consider, and which you have."
- **Stock/flow discipline** — classify each archetype; enforce diverging ramps
  for signed flows, sequential for stocks; warn when a difference/change map
  lacks a diverging ramp.
- **Boundary critique** — flag flow-type themes (flood, drainage, rainfall,
  emissions) clipped to administrative boundaries → suggest the natural system
  boundary (watershed/airshed).
- **Temporal series → stock/flow** — detect years in layer names (your
  PERSIANN case); offer the change map (stock difference = flow) with the
  diverging convention and, with Spatial Analyst, real raster differencing.
- **Convention hardening** — projected-CRS gate before ESZ buffers; two-raster
  co-registration gate before change maps; IMD breaks for rainfall; URDPFI/NRSC
  palette for LULC; total-over-AOI for carbon.
- **Loops block** — optional "SYSTEMS CONTEXT" header text per archetype.

Each of these is a small, testable rule with a citation behind it — the same
philosophy as the rest of the tool. This study is the specification; the
v0.11.0 code will encode it.

---

### Sources (standards verified July 2026)

- Supreme Court of India, WP(C) 202/1995, order dated 26 April 2023 (ESZ
  modification of the 1 km rule): https://api.sci.gov.in/supremecourt/1995/2997/2997_1995_8_1501_43924_Judgement_26-Apr-2023.pdf ; summary: https://www.drishtiias.com/daily-updates/daily-news-analysis/supreme-court-modifies-order-on-esz
- URDPFI Guidelines 2014 (land-use classification & colour convention),
  MoHUA: https://mohua.gov.in/upload/uploadfiles/files/URDPFI%20Guidelines%20Vol%20I(2).pdf
- IMD Heavy Rainfall Warning Services (rainfall category thresholds):
  https://mausam.imd.gov.in/imd_latest/contents/pdf/pubbrochures/Heavy%20Rainfall%20Warning%20Services.pdf
- IPCC 2006 Guidelines for National GHG Inventories; GPC (city inventories);
  InVEST Carbon model documentation — standard references, not re-verified here.
