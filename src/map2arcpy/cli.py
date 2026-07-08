"""map2arcpy command line.

    map2arcpy generate <input> [-o script.py] [--spec spec.json] [--strict]
    map2arcpy inspect  <input>
    map2arcpy examples [--list] [--run NAME]

<input> is a file (.aprx/.lyrx/.mapx, .geojson/.json/.shp, .tif/.png/.jpg/
.pdf, .txt, or a saved MapSpec .json) — or a quoted plain-English map
description.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .detect import parse_any, detect_kind
from .generator import generate

_EXAMPLES = {
    "buffer": "Buffer schools.shp by 500 meters, clip to \"city_boundary.shp\", "
              "in EPSG:32644, titled 'School Walkability', A4 landscape, export to PDF",
    "choropleth": "Choropleth map of population using viridis from wards.geojson "
                  "on a light gray basemap, labeled with ward_name, 300 dpi",
    "site": "Show sites.shp in red over imagery, select where \"status = 'ACTIVE'\", "
            "UTM zone 44N, titled 'Active Project Sites'",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="map2arcpy",
                                 description="Convert any map into an executable "
                                             "ArcGIS Pro (arcpy) Python script.")
    ap.add_argument("--version", action="version", version=f"map2arcpy {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("generate", help="input -> arcpy script")
    g.add_argument("input", help="file or quoted description")
    g.add_argument("-o", "--output", default=None, help="script path (default: stdout)")
    g.add_argument("--spec", default=None, help="also write the intermediate MapSpec JSON here")
    g.add_argument("--strict", action="store_true",
                   help="fail on spec problems instead of embedding TODOs")
    g.add_argument("--web", action="store_true",
                   help="allow web lookups: geocode places (Nominatim), download "
                        "OSM features (Overpass), find ArcGIS Online layers")

    i = sub.add_parser("inspect", help="show the MapSpec a given input produces")
    i.add_argument("input")
    i.add_argument("--web", action="store_true",
                   help="apply the same web enrichment before showing the spec")

    e = sub.add_parser("examples", help="built-in example descriptions")
    e.add_argument("--list", action="store_true")
    e.add_argument("--run", metavar="NAME", help="generate a script from a named example")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    try:
        if args.cmd == "generate":
            return _generate(args)
        if args.cmd == "inspect":
            spec = parse_any(args.input)
            if getattr(args, "web", False):
                _enrich(spec, args.input, os.getcwd())
            print(f"# detected input kind: {detect_kind(args.input)}")
            print(spec.to_json())
            issues = spec.validate()
            if issues:
                print("\n# issues (fixed as TODOs at generate time unless --strict):",
                      file=sys.stderr)
                for x in issues:
                    print(f"#  - {x}", file=sys.stderr)
            return 0
        if args.cmd == "examples":
            if args.run:
                if args.run not in _EXAMPLES:
                    print(f"unknown example '{args.run}' — try --list", file=sys.stderr)
                    return 2
                print(generate(parse_any(_EXAMPLES[args.run]), strict=False))
            else:
                for k, v in _EXAMPLES.items():
                    print(f"{k:12s} {v}")
            return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"map2arcpy: {e}", file=sys.stderr)
        return 1
    return 2


def _enrich(spec, inp: str, out_dir: str) -> None:
    """Apply the opt-in web pass (NL inputs only)."""
    if spec.source_kind != "natural-language":
        print("map2arcpy: --web currently enriches natural-language inputs only "
              f"(this is '{spec.source_kind}') — skipped", file=sys.stderr)
        return
    from . import web
    text = inp
    if os.path.exists(inp):
        with open(inp, "r", encoding="utf-8-sig") as f:
            text = f.read()
    web.enrich(spec, text, out_dir)


def _generate(args) -> int:
    spec = parse_any(args.input)
    if args.web:
        out_dir = (os.path.dirname(os.path.abspath(args.output))
                   if args.output else os.getcwd())
        _enrich(spec, args.input, out_dir)
    code = generate(spec, strict=args.strict)
    if args.spec:
        with open(args.spec, "w", encoding="utf-8") as f:
            f.write(spec.to_json())
        print(f"spec  -> {args.spec}", file=sys.stderr)
    if args.output:
        out = args.output
        d = os.path.dirname(out)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(code)
        n_todo = code.count("# TODO")
        print(f"script -> {out}  ({len(code.splitlines())} lines"
              + (f", {n_todo} TODOs to review" if n_todo else "") + ")",
              file=sys.stderr)
    else:
        print(code)
    return 0
