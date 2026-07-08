"""map2arcpy — turn any map into an executable ArcGIS Pro (arcpy) script."""
from .spec import MapSpec, Layer, Operation, Renderer, Layout   # noqa: F401
from .detect import parse_any, detect_kind                      # noqa: F401
from .generator import generate                                 # noqa: F401

__version__ = "0.1.0"


def convert(inp: str, strict: bool = False) -> str:
    """One-call API: input (path or description) -> arcpy script text."""
    return generate(parse_any(inp), strict=strict)
