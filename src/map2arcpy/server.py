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
import json
import os
import re
import shutil
import tempfile
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
                       ".sid", ".dem", ".img")


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
        return spec

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
            self._json({"ok": True, "version": __version__,
                        "web_enabled": self.web_enabled})
        elif self.path == "/api/examples":
            from .cli import _EXAMPLES
            self._json(_EXAMPLES)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):                                        # noqa: N802
        if self.path not in ("/api/inspect", "/api/generate"):
            self._json({"error": "not found"}, 404)
            return
        doc = self._read_body()
        if doc is None:
            return
        spec = self._parse(doc)
        if spec is None:
            return
        issues = spec.validate()
        if self.path == "/api/inspect":
            self._json({"spec": spec.to_dict(), "issues": issues})
            return
        try:
            code = generate(spec, strict=bool(doc.get("strict")))
        except ValueError as e:                               # strict-mode failure
            self._json({"error": str(e), "issues": issues}, 422)
            return
        fname = re.sub(r"\W+", "_", spec.layout.title.lower()).strip("_") or "map_script"
        self._json({"script": code, "spec": spec.to_dict(), "issues": issues,
                    "todos": code.count("# TODO"), "filename": fname + ".py"})


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
          web: bool = False, open_browser: bool = True) -> None:
    upload_dir = tempfile.mkdtemp(prefix="map2arcpy_uploads_")
    _Handler.web_enabled = web
    _Handler.upload_dir = upload_dir
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"map2arcpy dashboard -> {url}")
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
        shutil.rmtree(upload_dir, ignore_errors=True)
