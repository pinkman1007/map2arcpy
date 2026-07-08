# PREMORTEM — "it's six months from now and map2arcpy failed. What happened?"

A premortem imagines the failure first and works backward, so the causes get
fixed while they're still cheap. Scenarios are ordered by (likelihood ×
damage). **MITIGATED** items were closed by this audit — each has a
regression test. **OPEN** items carry their watch signal, so failure is
noticed early rather than explained late. Companion register: GAPS.md
(known limits); this file is about *how the project dies*.

## 1. "It wiped my map." — MITIGATED

The original generated scripts reused the project's first map and removed
every non-basemap layer from it. A user running the script in the Python
window of their real, open .aprx would watch their working map get gutted —
one autosave later, permanently. That single GitHub issue ("this tool
deleted my layers") would have defined the project.

*Now:* scripts always build in a **fresh, uniquely named map**
(`fresh_map()`), never call `removeLayer` on user content, and never call
`aprx.save()`. If `createMap` is unavailable the script falls back to the
first map *without clearing it* and says so. Test:
`test_generated_script_never_clears_user_maps`.

## 2. "A malicious .lyrx made the generated script run attacker code." — MITIGATED

Layer and map names from input files flowed unescaped into the generated
script's docstring. A crafted name containing `"""` could terminate the
docstring and inject executable statements into a script the user *trusts
and runs inside their GIS*. That's a supply-chain-style vuln for anyone
converting files they received from others — and shared .lyrx/.mapx files
are exactly how GIS teams work.

*Now:* all text destined for docstrings/comments passes `_safe_text()`
(newlines collapsed, `"""` neutralised); values in CONFIG were already
repr-escaped. The test asserts the payload survives only as an inert string
constant and that no injected call exists anywhere in the AST. Related:
a hostile .aprx with a multi-GB zip entry no longer exhausts memory
(32 MB per-entry cap, `test_aprx_zip_bomb_entry_skipped`).

## 3. "First run crashed on their Pro version; they never came back." — PARTLY MITIGATED

The layout API (`createLayout` etc.) needs Pro 3.x; symbology classes moved
between 3.0→3.4. A cryptic `AttributeError` ten seconds into the demo is how
tools lose GIS users, who rarely file issues — they just leave.

*Now:* `check_pro_version()` warns up front on Pro < 3, and symbology/layout
helpers already WARN-and-continue instead of crashing. *Still open:* no real
matrix testing against Pro versions (no licensed runner in CI). **Watch
signal:** first issue mentioning a Pro version number → stand up a nightly
job on a licensed Windows machine, or recruit one user per Pro version as a
smoke-tester.

## 4. "It said 'any map' and users brought screenshots." — OPEN (by design)

The pitch invites the hardest input (a picture) that the rule-based core
handles least. Users who arrive via the word "AI" may expect pixels →
layers, get an honest scaffold, and leave a "doesn't work" star. Mitigation
so far: README and the generated scripts say loudly what image input can and
cannot do; the scaffold still runs. **Watch signal:** issues phrased "it
didn't convert my PNG" → add a README GIF showing exactly what an image
input produces, and pin an FAQ issue. Long-term: the roadmap's LLM/vision
*front-end* that emits the same auditable MapSpec.

## 5. "The demo was wrong in a way GIS people spot instantly." — OPEN

A buffer of "500 Meters" on EPSG:4326 data, a choropleth on a nonsense field
picked by the profiler, labels on the wrong attribute — individually small,
but professionals judge a cartography tool in the first thirty seconds.
Mitigations in place: projected-CRS nudge notes, field-choice reasoning
recorded in notes, nothing silent. **Watch signal:** any "the output map is
wrong" issue → add a `--review` mode that prints the spec as a human
checklist before generating.

## 6. "One maintainer, zero releases, PR queue of two." — OPEN

Bus factor 1. No PyPI release, no version tags, no lint gate, no
CONTRIBUTING.md. Interest without maintenance converts to forks and decay.
Cheap next steps when (not if) the first external user appears: tag v0.1.0,
publish to PyPI (`pip install map2arcpy` beats a git URL), add ruff to CI,
write a 10-line CONTRIBUTING.md. **Watch signal:** first external PR or
issue.

## 7. "Esri shipped the same thing / changed the format." — ACCEPTED RISK

ArcGIS Pro already exports Python snippets for tool runs; an official
"map to script" could obsolete the niche. Counter-positioning: this tool is
open, offline, scriptable, cross-input (NL + data + CIM + images), and emits
auditable single-file scripts — keep leaning into that. CIM format drift is
the quieter version of the same risk; the parsers fail soft (TODO layers,
notes) rather than hard. **Watch signal:** Pro release notes mentioning CIM
schema changes → extend `tests/test_cim.py` fixtures with a real file from
that version.

## 8. "--web leaked something / broke ToS / rotted." — OPEN (managed)

The web pass sends place names and feature keywords to third parties
(Nominatim, Overpass, ArcGIS Online). For most planning work that's
harmless, but a user mapping something sensitive (a defence site, a
confidential project location) may not expect any network egress from a
"local" tool. Mitigations: web is strictly opt-in per invocation, the
README says exactly which services are called, failures degrade to notes,
and the offline core is untouched. Endpoint drift (Overpass mirrors change,
Nominatim policy tightens) is detected by exactly one thing: the mocked
tests keep passing while real calls fail. **Watch signal:** any issue titled
"--web stopped working" → add a `map2arcpy doctor --web` connectivity probe
and make endpoints configurable via environment variables.

## 9. "The name got us a trademark letter." — LOW, ADDRESSED

"arcpy" appears in the name of an unaffiliated tool. Nominative use of an
API name is normal in the ecosystem (dozens of `arcpy-*` repos), and the
README now carries an explicit non-affiliation disclaimer. If it ever
matters, the rename is cheap while the project is young.

---
*Rule of thumb going forward: when a watch signal fires, the corresponding
mitigation stops being optional. Update this file when it does.*
