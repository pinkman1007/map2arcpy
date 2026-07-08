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
import re
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
    g.add_argument("--no-profile", action="store_true",
                   help="ignore the saved ArcGIS Pro profile (map2arcpy probe)")
    g.add_argument("--depict", metavar="TEXT",
                   help="plain-English instruction for what a DATA input should "
                        "show, e.g. \"choropleth of pop_density, clip to "
                        "boundary.shp, titled 'Density'\"")
    g.add_argument("--systems", action="store_true",
                   help="add systems-thinking analysis: causal drivers, "
                        "stock/flow discipline, boundary critique, feedback loops")
    st = g.add_argument_group("style overrides (how the map should look)")
    st.add_argument("--title"), st.add_argument("--subtitle")
    st.add_argument("--ramp", help="greens|blues|reds|oranges|viridis|red_blue|brown_teal")
    st.add_argument("--color", help="#RRGGBB for simple-rendered layers")
    st.add_argument("--basemap", help="Imagery|Topographic|Streets|OpenStreetMap|"
                                      "'Dark Gray Canvas'|'Light Gray Canvas'|none")
    st.add_argument("--page", help="A4P|A4L|A3P|A3L|LetterP|LetterL")
    st.add_argument("--dpi", type=int)
    st.add_argument("--format", dest="fmt", help="pdf|png|jpg")

    i = sub.add_parser("inspect", help="show the MapSpec a given input produces")
    i.add_argument("input")
    i.add_argument("--web", action="store_true",
                   help="apply the same web enrichment before showing the spec")

    e = sub.add_parser("examples", help="built-in example descriptions")
    e.add_argument("--list", action="store_true")
    e.add_argument("--run", metavar="NAME", help="generate a script from a named example")

    dy = sub.add_parser("dynamics", help="classify a time series against the "
                                         "systems-dynamics behaviour archetypes")
    dy.add_argument("series", help="comma-separated numbers, e.g. "
                                   "\"120,138,161,190,224\" (a stock over time)")
    dy.add_argument("--kind", choices=["stock", "problem"], default="stock",
                    help="'stock' (accumulation) or 'problem' (symptom metric)")
    dy.add_argument("--times", help="optional matching times, e.g. "
                                    "\"2015,2016,2017,2018,2019\"")
    dy.add_argument("--vs", help="a second series for two-actor archetypes "
                                 "(success-to-successful / escalation)")

    pr = sub.add_parser("probe", help="sync with ArcGIS Pro: write the one-time "
                                      "environment probe script")
    pr.add_argument("-o", "--output", default="map2arcpy_probe.py",
                    help="where to write the probe script (default: ./map2arcpy_probe.py)")
    pr.add_argument("--show", action="store_true",
                    help="show the currently saved profile instead")

    s = sub.add_parser("serve", help="run the local API + web dashboard")
    s.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1 — no auth, keep it local)")
    s.add_argument("--port", type=int, default=8760)
    s.add_argument("--web", action="store_true",
                   help="allow web enrichment for requests that ask for it")
    s.add_argument("--no-browser", action="store_true",
                   help="don't auto-open the dashboard in a browser")

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
        if args.cmd == "dynamics":
            return _dynamics(args)
        if args.cmd == "probe":
            return _probe(args)
        if args.cmd == "serve":
            from .server import serve
            serve(host=args.host, port=args.port, web=args.web,
                  open_browser=not args.no_browser)
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


def _dynamics(args) -> int:
    import json as _json
    from . import dynamics

    def _nums(s):
        return [float(v) for v in re.split(r"[,\s]+", s.strip()) if v]
    try:
        series = _nums(args.series)
    except ValueError:
        print("dynamics: series must be numbers", file=sys.stderr)
        return 1
    if args.vs:
        res = dynamics.classify_pair(series, _nums(args.vs))
    else:
        times = _nums(args.times) if args.times else None
        res = dynamics.classify(series, times, kind=args.kind)
    print(_json.dumps(res, indent=2))
    return 0


def _probe(args) -> int:
    from .probe import probe_script, load_profile, summary, profile_path
    if args.show:
        prof = load_profile()
        if prof:
            print(f"profile ({profile_path()}):")
            print("  " + (summary(prof) or ""))
            print(f"  captured: {prof.get('captured')}")
        else:
            print("no profile saved yet — run the probe inside ArcGIS Pro first:",
                  file=sys.stderr)
            print("  map2arcpy probe -o map2arcpy_probe.py", file=sys.stderr)
        return 0
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(probe_script())
    print(f"probe -> {args.output}")
    print("Now run it ONCE inside ArcGIS Pro (Python window or notebook):")
    print(f"  exec(open(r'{os.path.abspath(args.output)}').read())")
    print("After that, every generated script is matched to your Pro "
          "version, licenses and portal.")
    return 0


def _generate(args) -> int:
    spec = parse_any(args.input)
    if args.web:
        out_dir = (os.path.dirname(os.path.abspath(args.output))
                   if args.output else os.getcwd())
        _enrich(spec, args.input, out_dir)
    if getattr(args, "depict", None) and spec.source_kind != "natural-language":
        from .intent import apply_intent
        apply_intent(spec, args.depict)
    style = {k: v for k, v in {
        "title": args.title, "subtitle": args.subtitle, "ramp": args.ramp,
        "color": args.color, "basemap": args.basemap, "page": args.page,
        "dpi": args.dpi, "format": args.fmt}.items() if v}
    if style:
        from .style import apply_style
        apply_style(spec, style)
    if getattr(args, "systems", False):
        from . import systems
        systems.apply(spec, getattr(args, "depict", "") or args.input)
    profile = None
    if not getattr(args, "no_profile", False):
        from .probe import load_profile, summary
        profile = load_profile()
        if profile:
            print(f"using Pro profile: {summary(profile)}", file=sys.stderr)
    code = generate(spec, strict=args.strict, profile=profile)
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
