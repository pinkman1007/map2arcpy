"""
Depict instructions — "what should the map SAY?"

Data inputs (zip/gpkg/shapefile/…) parse into layers with real sources, but
until now the CARTOGRAPHIC INTENT was auto-proposed. This module lets a
plain-English instruction ride along with a data input and drive the map:

    data: wards.gpkg
    depict: "choropleth of pop_density, label by ward_name,
             select where \"pop_density > 50\", titled 'Dense Wards', A3 landscape"

The instruction is parsed with the same NL grammar and MERGED onto the data
spec: operations are re-targeted at the real layers (matched by name),
renderers and labels land on the layer the text mentions (or the first
vector layer), extra files referenced in the text become layers, and layout
words (title, page, format, dpi, no-legend) override the defaults. Style
overrides (style.py) still apply afterwards and win.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .spec import MapSpec, Layer, Renderer
from .palettes import GEOMETRY_DEFAULTS
from .parsers import nl


def apply_intent(spec: MapSpec, text: str) -> MapSpec:
    text = (text or "").strip()
    if not text:
        return spec
    low = " ".join(text.split()).lower()
    instr = nl.parse(text, name_hint=spec.layout.title)
    applied: List[str] = []

    # the ORIGINAL uploaded data layer is the operation subject — capture it
    # before instruction-mentioned files are added, so "clip to city_boundary"
    # targets the uploaded data, not the boundary named in the text
    data_layers = [l for l in spec.layers if l.kind != "basemap" and l.source]

    # ---- extra data files mentioned in the instruction become layers ------
    existing = {l.name.lower() for l in spec.layers}
    for il in instr.layers:
        if il.kind == "basemap" or il.source in ("", "TODO_SET_PATH.shp"):
            continue
        if il.name.lower() not in existing:
            spec.layers.append(il)
            existing.add(il.name.lower())
            applied.append(f"added layer '{il.name}' from the instruction")

    target = data_layers[0] if data_layers else _find_target(spec, low)

    # ---- CRS: only when the text names one explicitly ---------------------
    if not any("no CRS given" in n for n in instr.notes):
        spec.crs_epsg = instr.crs_epsg
        applied.append(f"crs=EPSG:{instr.crs_epsg}")

    # ---- operations, re-targeted at real layers ---------------------------
    name_map = {l.name.lower(): l.name for l in spec.layers if l.kind != "basemap"}
    instr_outputs = {op.output for op in instr.operations if op.output}
    for op in instr.operations:
        op.inputs = [_resolve(i, name_map, instr_outputs, target) for i in op.inputs]
        # "buffer WARDS by 1 km" — the word after the verb names the subject;
        # it beats whatever path the grammar grabbed first
        if op.tool in ("buffer", "dissolve", "select") and op.inputs \
                and op.inputs[0] not in instr_outputs:
            word = _subject_word(op.tool, low)
            if word and word not in _STOPWORDS:
                hit = _subject_after_verb(op.tool, low, name_map)
                if hit:
                    op.inputs[0] = hit                 # names a real layer
                elif word != (target.name.lower() if target else ""):
                    # names a layer that wasn't uploaded -> keep it unresolved
                    # (surfaces in validation) instead of silently using target
                    op.inputs[0] = word
        # a leading "clip/erase to X" (no subject) parsed as clipping X by
        # itself — the subject is the uploaded data layer; fix the first input
        if op.tool in ("clip", "erase") and op.inputs and target is not None:
            if len(op.inputs) >= 2 and op.inputs[0] == op.inputs[1]:
                op.inputs[0] = target.name
            elif op.inputs[0] not in name_map.values() and \
                    op.inputs[0] not in instr_outputs:
                op.inputs.insert(0, target.name)
        spec.operations.append(op)
        applied.append(f"op:{op.tool}")
    declared = {l.name for l in spec.layers}
    last_out: Optional[str] = None
    for op in spec.operations:
        if op.output:
            last_out = op.output
            if op.output not in declared:
                spec.layers.append(Layer(
                    name=op.output, source="", kind="vector",
                    renderer=Renderer(type="simple",
                                      color=GEOMETRY_DEFAULTS["polygon"])))
                declared.add(op.output)

    # ---- symbology / labels straight from the instruction text ------------
    sym_target = next((l for l in spec.layers if l.name == last_out), None) or target
    if sym_target is not None:
        u = nl._UNIQ_RE.search(text)
        g = nl._GRAD_RE.search(text)
        if u:
            sym_target.renderer = Renderer(type="unique", field=u.group(1).strip())
            applied.append(f"unique by '{u.group(1).strip()}' on '{sym_target.name}'")
        elif g:
            fld = (g.group(1) or "").strip().split(" using")[0].strip() or "VALUE"
            from .palettes import RAMPS, DEFAULT_RAMP
            ramp = RAMPS.get(nl._ramp(low) or DEFAULT_RAMP)
            sym_target.renderer = Renderer(type="graduated", field=fld,
                                           ramp=list(ramp))
            applied.append(f"graduated by '{fld}' on '{sym_target.name}'")
        elif nl._color(low):
            sym_target.renderer = Renderer(type="simple", color=nl._color(low))
            applied.append(f"colour on '{sym_target.name}'")
    lab = nl._LABEL_RE.search(text)
    if lab and sym_target is not None:
        sym_target.label_field = lab.group(1)
        applied.append(f"labels by '{lab.group(1)}'")

    # ---- basemap ------------------------------------------------------------
    instr_bm = next((l for l in instr.layers if l.kind == "basemap"), None)
    if instr_bm:
        spec.layers = [l for l in spec.layers if l.kind != "basemap"]
        spec.layers.insert(0, instr_bm)
        applied.append(f"basemap={instr_bm.source}")

    # ---- layout words --------------------------------------------------------
    if nl._TITLE_RE.search(text):
        spec.layout.title = instr.layout.title
        spec.layout.export = (re.sub(r"\W+", "_", instr.layout.title.lower()).strip("_")
                              + "." + spec.layout.export.rsplit(".", 1)[-1])
        applied.append("title")
    if re.search(r"\b(a3|a4|letter|landscape|portrait)\b", low):
        spec.layout.page = instr.layout.page
        applied.append(f"page={instr.layout.page}")
    if re.search(r"\b(png|jpe?g|pdf)\b", low):
        ext = instr.layout.export.rsplit(".", 1)[-1]
        spec.layout.export = spec.layout.export.rsplit(".", 1)[0] + "." + ext
        applied.append(f"format={ext}")
    if nl._DPI_RE.search(low):
        spec.layout.dpi = instr.layout.dpi
        applied.append(f"dpi={instr.layout.dpi}")
    for key in ("legend", "north_arrow", "scale_bar"):
        if re.search(nl._NO_SURROUND_RE % key.replace("_", r"\s+"), low):
            setattr(spec.layout, key, False)
            applied.append(f"{key}=off")

    # thematic map-type conventions ("carbon map", "eco-sensitive zones", ...)
    from . import archetypes
    before = len(spec.notes)
    archetypes.apply(spec, text)
    if len(spec.notes) > before:
        applied.append("archetype")

    if applied:
        spec.notes.append("depict instruction applied: " + "; ".join(applied))
    else:
        spec.notes.append("depict instruction given but nothing recognised in it — "
                          "see the README's grammar vocabulary")
    return spec


# ---------------------------------------------------------------------------
def _find_target(spec: MapSpec, low: str) -> Optional[Layer]:
    """The layer the instruction is about: named in the text, else the first
    vector layer, else the first data layer."""
    for l in spec.layers:
        if l.kind == "basemap":
            continue
        nm = l.name.lower()
        if nm in low or nm.replace("_", " ") in low:
            return l
    return (next((l for l in spec.layers if l.kind == "vector"), None)
            or next((l for l in spec.layers if l.kind != "basemap"), None))


def _resolve(inp: str, name_map, instr_outputs, target: Optional[Layer]) -> str:
    """Map an instruction op-input onto a real layer name."""
    il = str(inp).lower()
    if il in name_map:
        return name_map[il]
    if inp in instr_outputs:                       # chained op output
        return inp
    fuzzy = next((v for k, v in name_map.items()
                  if len(il) >= 3 and (il in k or k in il)), None)
    if fuzzy:
        return fuzzy
    if any(c in inp for c in "/\\."):              # a literal path
        return inp
    # nl.parse's own placeholders (no real layer named in the text) mean "the
    # data" -> resolve to the target data layer
    if il == "input" or re.fullmatch(r"layer_\d+", il):
        return target.name if target is not None else inp
    # a genuinely unknown NAMED token (e.g. 'rivers' never uploaded): keep it
    # so the spec-validator surfaces it, rather than silently running the op on
    # the wrong data
    return inp


_STOPWORDS = {"by", "the", "to", "from", "with", "of", "and", "a", "an",
              "using", "in", "on", "it", "them", "this", "that", "where",
              "into", "over", "for", "at", "as"}


def _subject_word(tool: str, low: str) -> Optional[str]:
    """The raw word after the verb (e.g. 'rivers' in 'buffer rivers by 1km')."""
    m = re.search(r"\b%s\w*\s+(?:the\s+)?([a-z_][\w]*)" % re.escape(tool), low)
    return m.group(1) if m else None


def _subject_after_verb(tool: str, low: str, name_map) -> Optional[str]:
    word = _subject_word(tool, low)
    if not word or word in _STOPWORDS:
        return None
    if word in name_map:
        return name_map[word]
    return next((v for k, v in name_map.items()
                 if len(word) >= 3 and (word in k or k in word)), None)


def _instr_final(instr: MapSpec) -> Optional[Layer]:
    for l in reversed(instr.layers):
        if l.kind != "basemap" and (l.renderer.type != "simple" or l.renderer.color):
            return l
    return None
