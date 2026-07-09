"""
Step-by-step recipes — paste numbered instructions, get ONE ordered script.

Instead of a single dense sentence, a recipe is a list of small instructions,
one per line:

    1. load wards.shp
    2. clip to district_boundary.shp
    3. choropleth of pop_density with 5 classes
    4. label by ward_name
    5. buffer hospitals.shp by 500 m
    6. title 'Dense Wards', A3 landscape
    7. export pdf at 300 dpi

Each step is parsed with the SAME deterministic grammar (nl + intent) and
applied to the growing MapSpec in order, so later steps see everything the
earlier steps built (step 3's choropleth lands on step 2's clipped output).
Every operation is tagged with the step that created it, and the generator
emits a `# ==== STEP n: ... ====` banner above it, so the script reads like
the recipe. Steps the grammar can't understand are NOT silently dropped —
they become explicit "STEP n NOT UNDERSTOOD" notes carried into the script.

Detection: text with 2+ lines that start with numbering (`1.` `2)` `3:`),
bullets (`-` `*` `•`), or `step N` is treated as a recipe. A single sentence
or unmarked prose still goes through the normal NL parser.
"""
from __future__ import annotations

import difflib
import re
from typing import List, Tuple

from ..spec import MapSpec

#: a line that is explicitly marked as a step
_STEP_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,3}\s*[.):=-]"          # 1.  2)  3:  4-
    r"|[-*•‣◦]"    # -  *  •
    r"|step\s+\d{1,3}\s*[.:)-]?"  # step 1:  Step 2
    r")\s*(.+)$",
    re.IGNORECASE)


def looks_like_steps(text: str) -> bool:
    """True when the text reads as a numbered/bulleted recipe (2+ marked
    lines), not as one prose description."""
    if not text or "\n" not in text:
        return False
    marked = [ln for ln in text.splitlines() if _STEP_LINE_RE.match(ln.strip())]
    return len(marked) >= 2


def split_steps(text: str) -> List[str]:
    """The cleaned instruction of each step, in order. Unmarked non-empty
    lines between marked ones are treated as steps too (people forget to
    number one line) — the order on the page is the order that runs."""
    steps: List[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):         # '#' lines are recipe comments
            continue
        m = _STEP_LINE_RE.match(s)
        steps.append(m.group(1).strip() if m else s)
    return [s for s in steps if s]


def parse(text: str, name_hint: str = "recipe map") -> MapSpec:
    spec = MapSpec(source_kind="steps")
    spec.layout.title = name_hint.replace("_", " ").strip().title() or "Recipe Map"
    return apply_recipe(spec, text)


def apply_recipe(spec: MapSpec, text: str) -> MapSpec:
    """Apply a step-by-step recipe to an existing spec, in order. Used both
    by parse() (recipe-only input) and by the server/dashboard when a recipe
    rides along with an uploaded data file (the 'depict' path)."""
    from ..intent import apply_intent          # late: intent imports parsers

    steps = split_steps(text)
    spec.notes.append(f"recipe: {len(steps)} steps, applied in order")

    for i, step in enumerate(steps, 1):
        ops_before = len(spec.operations)
        notes_before = len(spec.notes)
        apply_intent(spec, step)

        # ---- rewrite apply_intent's bookkeeping as per-step notes ----------
        new_notes = spec.notes[notes_before:]
        del spec.notes[notes_before:]
        understood = None
        for n in new_notes:
            if n.startswith("depict instruction applied: "):
                understood = n[len("depict instruction applied: "):]
            elif n.startswith("depict instruction given but nothing recognised"):
                understood = None
            else:
                spec.notes.append(n)           # keep archetype/parser notes
        if understood:
            spec.notes.append(f"STEP {i} ok — {step!r}: {understood}")
        else:
            hint = "; ".join(suggest_phrasing(step))
            spec.notes.append(
                f"STEP {i} NOT UNDERSTOOD — {step!r}: "
                + (f"did you mean: {hint}? " if hint else "")
                + "(vocabulary reference: docs/GRAMMAR.md)")

        # ---- tag the operations this step created --------------------------
        label = f"STEP {i}: {step}"
        for op in spec.operations[ops_before:]:
            op.params.setdefault("step", label)

    return spec


# ---------------------------------------------------------------------------
# "Did you mean …?" — deterministic phrasing suggestions for a failed step.
#
# Each entry: (intent keywords the user might have used, the canonical
# phrasing to suggest). Keywords are fuzzy-matched (difflib, stdlib, fully
# deterministic) so typos like 'bufer' or near-synonyms like 'shade' still
# find their template. Suggestions are examples of the GRAMMAR, not guesses
# about the user's data — the user swaps in their own layer/field names.
# ---------------------------------------------------------------------------
_SUGGESTIONS: List[Tuple[Tuple[str, ...], str]] = [
    (("buffer", "ring", "radius", "distance", "within"),
     "'buffer roads.shp by 500 m'"),
    (("clip", "crop", "cut", "trim", "extract", "mask"),
     "'clip to boundary.shp'"),
    (("dissolve", "aggregate", "combine", "group"),
     "'dissolve by DISTRICT'"),
    (("choropleth", "graduated", "shade", "shaded", "classified", "heatmap",
      "gradient", "intensity"),
     "'choropleth of pop_density using greens'"),
    (("unique", "categories", "categorical", "categorise", "categorize",
      "classes", "types"),
     "'unique values by landuse'"),
    (("label", "labels", "labelled", "annotate", "name", "names", "text"),
     "'label by ward_name'"),
    (("select", "filter", "where", "query", "subset", "only"),
     "'select where \"pop_density > 50\"'"),
    (("intersect", "intersection", "overlap"),
     "'intersect wards.shp and flood.shp'"),
    (("erase", "remove", "subtract", "exclude"),
     "'erase water.shp from wards.shp'"),
    (("union", "merge", "append", "join"),
     "'merge north.shp and south.shp' (or 'spatial join a.shp and b.shp')"),
    (("title", "titled", "heading", "caption", "call"),
     "\"titled 'My Map Title'\" (quotes required)"),
    (("export", "save", "output", "print", "pdf", "png", "jpg", "jpeg"),
     "'export pdf at 300 dpi'"),
    (("page", "size", "a3", "a4", "letter", "landscape", "portrait", "orientation"),
     "'A3 landscape'"),
    (("basemap", "background", "imagery", "satellite", "osm", "topographic"),
     "'on imagery basemap'"),
    (("epsg", "crs", "projection", "project", "utm", "mercator", "coordinate"),
     "'EPSG:32644' or 'UTM zone 44N'"),
    (("load", "add", "open", "use", "import", "read", "bring"),
     "'load wards.shp' (any path ending .shp/.geojson/.gpkg/.tif/…)"),
    (("color", "colour", "red", "green", "blue", "ramp", "palette", "scheme"),
     "'in red' / 'using blues' (named colour or ramp)"),
    (("legend", "north", "scalebar", "scale"),
     "'no legend' / 'no north arrow' / 'no scale bar'"),
]

_ALL_KEYWORDS = sorted({k for keys, _ in _SUGGESTIONS for k in keys})


def suggest_phrasing(step_text: str, limit: int = 2) -> List[str]:
    """Up to `limit` canonical phrasings the failed step probably meant.
    Deterministic: exact keyword hits first (in _SUGGESTIONS order), then
    difflib close-matches for typos. Empty list when nothing is plausible."""
    words = re.findall(r"[a-z]+", step_text.lower())
    if not words:
        return []
    hits: List[str] = []
    matched = set()
    for keys, template in _SUGGESTIONS:
        if any(w in keys for w in words):
            hits.append(template)
            matched.update(keys)
    if not hits:                                # typo pass: 'bufer' -> 'buffer'
        for w in words:
            if len(w) < 4:
                continue
            for close in difflib.get_close_matches(w, _ALL_KEYWORDS, n=1,
                                                   cutoff=0.8):
                for keys, template in _SUGGESTIONS:
                    if close in keys and template not in hits:
                        hits.append(template)
    return hits[:limit]
