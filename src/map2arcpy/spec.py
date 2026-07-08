"""
MapSpec — the intermediate representation every parser targets and the
generator consumes.

    input (NL text / .aprx / .lyrx / .mapx / GeoJSON / shapefile /
           web-map JSON / georeferenced image)
        │  parsers.*          (pure Python, rule-based)
        ▼
    MapSpec                    (this module — plain dataclasses)
        │  generator.emit     (templates)
        ▼
    standalone arcpy script    (runs inside ArcGIS Pro)

Keeping the IR tiny and JSON-serialisable means every stage can be unit
tested without arcpy, and users can hand-edit the spec (``--spec out.json``)
before generating code.
"""
from __future__ import annotations

import json
import dataclasses
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

SCHEMA_VERSION = 1

VALID_RENDERERS = ("simple", "unique", "graduated", "stretch")
VALID_LAYER_KINDS = ("vector", "raster", "basemap", "service")
VALID_PAGES = ("A4P", "A4L", "A3P", "A3L", "LetterP", "LetterL")

#: Geoprocessing operations the generator knows how to emit, mapped to the
#: arcpy call. Params are validated loosely on purpose — arcpy is the
#: authority; we only guarantee the emitted call is syntactically right.
KNOWN_OPS = {
    "buffer":       "arcpy.analysis.PairwiseBuffer",
    "clip":         "arcpy.analysis.PairwiseClip",
    "dissolve":     "arcpy.analysis.PairwiseDissolve",
    "intersect":    "arcpy.analysis.PairwiseIntersect",
    "erase":        "arcpy.analysis.PairwiseErase",
    "union":        "arcpy.analysis.Union",
    "merge":        "arcpy.management.Merge",
    "spatial_join": "arcpy.analysis.SpatialJoin",
    "select":       "arcpy.analysis.Select",
    "near":         "arcpy.analysis.Near",
    "project":      "arcpy.management.Project",
    "multi_buffer": "arcpy.analysis.MultipleRingBuffer",
}

#: pre-Pairwise equivalents, emitted when a Pro profile reports < 2.7
CLASSIC_OPS = dict(KNOWN_OPS, **{
    "buffer":    "arcpy.analysis.Buffer",
    "clip":      "arcpy.analysis.Clip",
    "dissolve":  "arcpy.management.Dissolve",
    "intersect": "arcpy.analysis.Intersect",
    "erase":     "arcpy.analysis.Erase",
})


@dataclass
class Renderer:
    """How a layer is drawn."""
    type: str = "simple"                       # simple|unique|graduated|stretch
    field: Optional[str] = None                # drives unique/graduated
    color: Optional[str] = None                # simple: single hex
    color_map: Dict[str, str] = dataclasses.field(default_factory=dict)   # unique: value->hex
    ramp: List[str] = dataclasses.field(default_factory=list)             # graduated/stretch hexes
    breaks: List[float] = dataclasses.field(default_factory=list)         # graduated class breaks
    outline: Optional[str] = None
    transparency: int = 0                      # 0-100
    class_count: int = 0                       # graduated: # classes (0 = auto)
    class_method: Optional[str] = None         # natural_breaks|quantile|equal_interval|geometric|std_dev
    outline_width: float = 0.0                 # points (0 = default)
    marker_size: float = 0.0                   # points, for point markers (0 = default)

    def validate(self) -> List[str]:
        errs = []
        if self.type not in VALID_RENDERERS:
            errs.append(f"renderer.type '{self.type}' not one of {VALID_RENDERERS}")
        if self.type in ("unique", "graduated") and not self.field:
            errs.append(f"renderer.type '{self.type}' requires a field")
        if not 0 <= int(self.transparency) <= 100:
            errs.append("renderer.transparency must be 0-100")
        return errs


@dataclass
class Layer:
    name: str
    source: str = ""                           # path / URL / basemap name
    kind: str = "vector"                       # vector|raster|basemap|service
    geometry: Optional[str] = None             # point|line|polygon (vectors)
    renderer: Renderer = dataclasses.field(default_factory=Renderer)
    definition_query: Optional[str] = None
    label_field: Optional[str] = None
    visible: bool = True
    notes: List[str] = dataclasses.field(default_factory=list)   # parser-added TODOs
    #: format-specific load parameters (NetCDF variable/dims, CSV x/y fields …)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> List[str]:
        errs = []
        if not self.name:
            errs.append("layer has no name")
        if self.kind not in VALID_LAYER_KINDS:
            errs.append(f"layer '{self.name}': kind '{self.kind}' not one of {VALID_LAYER_KINDS}")
        if self.kind != "basemap" and not self.source:
            errs.append(f"layer '{self.name}': no data source")
        errs.extend(f"layer '{self.name}': {e}" for e in self.renderer.validate())
        return errs


@dataclass
class Operation:
    """One geoprocessing step, run before the map is assembled."""
    tool: str                                  # key in KNOWN_OPS
    inputs: List[str] = dataclasses.field(default_factory=list)   # layer names or paths
    output: str = ""                           # result name (added as a layer if listed)
    params: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> List[str]:
        errs = []
        if self.tool not in KNOWN_OPS:
            errs.append(f"unknown operation '{self.tool}' (known: {', '.join(sorted(KNOWN_OPS))})")
        if not self.inputs:
            errs.append(f"operation '{self.tool}' has no inputs")
        return errs


@dataclass
class Layout:
    title: str = "Untitled Map"
    subtitle: str = ""
    credits: str = ""
    page: str = "A4P"
    dpi: int = 300
    legend: bool = True
    north_arrow: bool = True
    scale_bar: bool = True
    export: str = "map.pdf"                    # .pdf or .png

    def validate(self) -> List[str]:
        errs = []
        if self.page not in VALID_PAGES:
            errs.append(f"layout.page '{self.page}' not one of {VALID_PAGES}")
        if not str(self.export).lower().endswith((".pdf", ".png", ".jpg")):
            errs.append("layout.export must end in .pdf, .png or .jpg")
        return errs


@dataclass
class MapSpec:
    """The whole map, ready to compile."""
    crs_epsg: int = 4326
    layers: List[Layer] = dataclasses.field(default_factory=list)
    operations: List[Operation] = dataclasses.field(default_factory=list)
    layout: Layout = dataclasses.field(default_factory=Layout)
    source_kind: str = "unknown"               # which parser produced this
    notes: List[str] = dataclasses.field(default_factory=list)
    extent: Optional[List[float]] = None       # [xmin,ymin,xmax,ymax] in WGS84
    systems_context: List[str] = dataclasses.field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    # ---- validation ----
    def validate(self) -> List[str]:
        errs = []
        if not isinstance(self.crs_epsg, int) or self.crs_epsg <= 0:
            errs.append(f"crs_epsg '{self.crs_epsg}' is not a positive integer")
        op_outputs = {op.output for op in self.operations if op.output}
        if not self.layers and not op_outputs:
            errs.append("spec has no layers and no operation outputs — nothing to map")
        names = [l.name for l in self.layers]
        for dup in {n for n in names if names.count(n) > 1}:
            errs.append(f"duplicate layer name '{dup}'")
        for l in self.layers:
            layer_errs = l.validate()
            if l.name in op_outputs:
                # a layer produced by an operation legitimately has no source
                layer_errs = [e for e in layer_errs if "no data source" not in e]
            errs.extend(layer_errs)
        known = set(names) | op_outputs
        for op in self.operations:
            errs.extend(op.validate())
            for i in op.inputs:
                looks_like_path = any(c in str(i) for c in "/\\.")
                if i not in known and not looks_like_path:
                    errs.append(f"operation '{op.tool}': input '{i}' is neither a layer, "
                                f"a prior output, nor a path")
        errs.extend(self.layout.validate())
        return errs

    # ---- (de)serialisation ----
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MapSpec":
        layers = []
        for ld in d.get("layers", []):
            ld = dict(ld)
            rd = ld.pop("renderer", {}) or {}
            layers.append(Layer(renderer=Renderer(**rd), **ld))
        ops = [Operation(**o) for o in d.get("operations", [])]
        layout = Layout(**(d.get("layout") or {}))
        return cls(
            crs_epsg=int(d.get("crs_epsg", 4326)),
            layers=layers,
            operations=ops,
            layout=layout,
            source_kind=d.get("source_kind", "unknown"),
            notes=list(d.get("notes", [])),
            extent=d.get("extent"),
            systems_context=list(d.get("systems_context", [])),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )

    @classmethod
    def from_json(cls, s: str) -> "MapSpec":
        return cls.from_dict(json.loads(s))
