"""map2arcpy — turn any map into an executable ArcGIS Pro (arcpy) script."""
from .spec import MapSpec, Layer, Operation, Renderer, Layout   # noqa: F401
from .detect import parse_any, detect_kind                      # noqa: F401
from .generator import generate                                 # noqa: F401

__version__ = "0.12.0"


def convert(inp: str, strict: bool = False, web: bool = False,
            out_dir: str = ".") -> str:
    """One-call API: input (path or description) -> arcpy script text.

    web=True additionally geocodes places, downloads OSM features and
    searches ArcGIS Online for natural-language inputs (network access
    and OSM/Esri terms of use apply)."""
    spec = parse_any(inp)
    if web and spec.source_kind == "natural-language":
        import os
        from . import web as _web
        text = inp
        if os.path.exists(inp):
            with open(inp, "r", encoding="utf-8-sig") as f:
                text = f.read()
        _web.enrich(spec, text, out_dir)
    from .probe import load_profile
    return generate(spec, strict=strict, profile=load_profile())
