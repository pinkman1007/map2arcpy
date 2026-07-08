"""
Local API server + web dashboard — stdlib only, zero extra installs.

    map2arcpy serve                 # http://127.0.0.1:8760, opens the browser
    map2arcpy serve --port 9000 --web --no-browser

Endpoints (JSON):

    GET  /            the dashboard (single self-contained HTML page)
    GET  /health      {ok, version, web_enabled}
    GET  /api/examples {name: description}
    POST /api/inspect  {input | file:{name,content_b64}, web?} -> {spec, issues}
    POST /api/generate {input | file:{name,content_b64}, web?, strict?}
                       -> {script, spec, issues, todos, filename}

Security posture (deliberate, documented):
* binds 127.0.0.1 by default — this is a personal tool UI, not a service
* no auth — do NOT expose it beyond localhost/intranet without a proxy
* request bodies capped (default 64 MB) so a stray upload can't OOM it
* uploads land in a per-process temp dir that is cleaned on exit
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from . import __version__
from .detect import parse_any
from .generator import generate
from .spec import MapSpec

MAX_BODY = 64 * 1024 * 1024
DEFAULT_PORT = 8760

_ALLOWED_UPLOAD_EXT = (".aprx", ".lyrx", ".mapx", ".geojson", ".json", ".shp",
                       ".dbf", ".prj", ".txt", ".tif", ".tiff", ".png", ".jpg",
                       ".jpeg", ".pdf", ".gpkg", ".kml", ".kmz", ".gpx", ".csv",
                       ".dxf", ".dwg", ".dgn", ".nc", ".asc", ".agr", ".flt",
                       ".bil", ".bip", ".bsq", ".hdr", ".hgt", ".jp2", ".ecw",
                       ".sid", ".dem", ".img", ".zip")


def _dashboard_html() -> bytes:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(path, "rb") as f:
        return f.read()


class _Handler(BaseHTTPRequestHandler):
    # set by serve():
    web_enabled = False
    upload_dir = None

    server_version = "map2arcpy/" + __version__

    # ------------------------------------------------------------------ util
    def log_message(self, fmt, *args):                       # quieter default log
        print("[server] " + (fmt % args))

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json({"error": "empty request body"}, 400)
            return None
        if length > MAX_BODY:
            self._json({"error": f"request body over {MAX_BODY // (1024*1024)} MB limit"}, 413)
            return None
        raw = self.rfile.read(length)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json({"error": "body is not valid JSON"}, 400)
            return None
        if not isinstance(doc, dict):
            self._json({"error": "body must be a JSON object"}, 400)
            return None
        return doc

    def _resolve_input(self, doc: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Return (input_for_parse_any, nl_text_for_web) or None after erroring."""
        # local-path mode: the server runs on this machine, so it can read
        # the data IN PLACE — no copy, generated scripts point at the
        # original location (zips extract to a sibling _unzipped folder)
        local = doc.get("path")
        if isinstance(local, str) and local.strip():
            p = local.strip().strip('"').strip("'")
            if not os.path.exists(p):
                self._json({"error": f"path not found on this machine: {p}"}, 400)
                return None
            return p, ""
        f = doc.get("file")
        if isinstance(f, dict) and f.get("content_b64"):
            name = os.path.basename(str(f.get("name", "upload")))
            name = re.sub(r"[^\w. -]", "_", name) or "upload"
            ext = os.path.splitext(name)[1].lower()
            if ext not in _ALLOWED_UPLOAD_EXT:
                self._json({"error": f"unsupported upload type '{ext}'"}, 400)
                return None
            try:
                blob = base64.b64decode(f["content_b64"], validate=True)
            except Exception:                                 # noqa: BLE001
                self._json({"error": "content_b64 is not valid base64"}, 400)
                return None
            path = os.path.join(self.upload_dir, name)
            with open(path, "wb") as out:
                out.write(blob)
            return path, ""
        text = doc.get("input")
        if not isinstance(text, str) or not text.strip():
            self._json({"error": "provide 'input' (text) or 'file' {name, content_b64}"}, 400)
            return None
        return text, text

    def _parse(self, doc: Dict[str, Any]) -> Optional[MapSpec]:
        resolved = self._resolve_input(doc)
        if resolved is None:
            return None
        inp, nl_text = resolved
        try:
            spec = parse_any(inp)
        except (ValueError, FileNotFoundError) as e:
            self._json({"error": str(e)}, 400)
            return None
        if doc.get("web"):
            if not self.web_enabled:
                spec.notes.append("web: this server was started without --web, "
                                  "so web enrichment is disabled")
            elif spec.source_kind != "natural-language":
                spec.notes.append("web: enrichment applies to natural-language "
                                  "inputs only — skipped")
            else:
                from . import web
                text = nl_text
                if not text and os.path.exists(inp):
                    with open(inp, "r", encoding="utf-8-sig", errors="ignore") as fh:
                        text = fh.read()
                web.enrich(spec, text, self.upload_dir)
        # depict instruction: plain-English intent riding along with a data
        # input ("choropleth of pop_density, clip to boundary, titled ...")
        depict = doc.get("depict")
        if not depict and (doc.get("path") or doc.get("file")):
            depict = doc.get("input")              # text box + file = intent
        if isinstance(depict, str) and depict.strip() \
                and spec.source_kind != "natural-language":
            from .intent import apply_intent
            apply_intent(spec, depict)
        st = doc.get("style")
        if isinstance(st, dict) and st:
            from .style import apply_style
            apply_style(spec, st)
        if doc.get("systems"):
            from . import systems
            systems.apply(spec, str(depict or doc.get("input") or ""))
        return spec

    def _dynamics(self, doc):
        import re as _re
        from . import dynamics as dyn

        def _nums(s):
            if isinstance(s, (list, tuple)):
                return [float(v) for v in s]
            return [float(v) for v in _re.split(r"[,\s]+", str(s).strip()) if v]
        try:
            series = _nums(doc.get("series", ""))
        except (ValueError, TypeError):
            self._json({"error": "series must be numbers"}, 400)
            return
        if len(series) < 3:
            self._json({"error": "give at least 3 numbers (one per time epoch)"}, 400)
            return
        try:
            if doc.get("vs"):
                res = dyn.classify_pair(series, _nums(doc["vs"]))
            else:
                times = _nums(doc["times"]) if doc.get("times") else None
                res = dyn.classify(series, times, kind=doc.get("kind", "stock"))
        except (ValueError, TypeError) as e:
            self._json({"error": str(e)}, 400)
            return
        res["series"] = series
        self._json(res)

    # -------------------------------------------------------------- handlers
    def do_GET(self):                                         # noqa: N802
        if self.path in ("/", "/index.html"):
            body = _dashboard_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            from .probe import load_profile, summary
            self._json({"ok": True, "version": __version__,
                        "web_enabled": self.web_enabled,
                        "pro_profile": summary(load_profile())})
        elif self.path == "/api/examples":
            from .cli import _EXAMPLES
            self._json(_EXAMPLES)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):                                        # noqa: N802
        if self.path not in ("/api/inspect", "/api/generate", "/api/dynamics",
                             "/api/discover"):
            self._json({"error": "not found"}, 404)
            return
        # CSRF guard: browsers cannot send application/json cross-origin
        # without a CORS preflight (which this server never grants), so
        # requiring it blocks hostile web pages from driving a local server
        # that can read file paths.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            self._json({"error": "Content-Type must be application/json"}, 415)
            return
        doc = self._read_body()
        if doc is None:
            return
        if self.path == "/api/dynamics":
            self._dynamics(doc)
            return
        spec = self._parse(doc)
        if spec is None:
            return
        issues = spec.validate()
        if self.path == "/api/discover":
            from .discover import suggest
            from .probe import load_profile
            self._json({"suggestions": suggest(spec, load_profile()),
                        "source_kind": spec.source_kind,
                        "layers": [l.name for l in spec.layers if l.kind != "basemap"]})
            return
        if self.path == "/api/inspect":
            self._json({"spec": spec.to_dict(), "issues": issues})
            return
        from .probe import load_profile
        try:
            code = generate(spec, strict=bool(doc.get("strict")),
                            profile=load_profile())
        except ValueError as e:                               # strict-mode failure
            self._json({"error": str(e), "issues": issues}, 422)
            return
        fname = re.sub(r"\W+", "_", spec.layout.title.lower()).strip("_") or "map_script"
        self._json({"script": code, "spec": spec.to_dict(), "issues": issues,
                    "todos": code.count("# TODO"), "filename": fname + ".py"})


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          web: bool = False, open_browser: bool = True,
          data_dir: Optional[str] = None) -> None:
    # Uploads must OUTLIVE the server: generated scripts reference these
    # paths (zip extractions especially), so a temp dir that vanishes on
    # exit would break every script the moment the server stops.
    base = data_dir or os.path.join(os.path.expanduser("~"), "map2arcpy_data")
    upload_dir = os.path.join(base, datetime.datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    os.makedirs(upload_dir, exist_ok=True)
    _Handler.web_enabled = web
    _Handler.upload_dir = upload_dir
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"map2arcpy dashboard -> {url}")
    print(f"uploaded data kept in: {upload_dir}")
    print(f"web enrichment: {'ENABLED' if web else 'off (start with --web to enable)'}")
    print("Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        httpd.server_close()
        try:                                    # remove only if nothing was uploaded
            if not os.listdir(upload_dir):
                os.rmdir(upload_dir)
        except OSError:
            pass
        print(f"your uploaded data stays in {upload_dir} — generated scripts "
              "reference it; delete old run_* folders there when done")
