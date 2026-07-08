"""API server tests — a real server on an ephemeral localhost port."""
import ast
import base64
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from map2arcpy import server as srv
from conftest import EXAMPLES

BASE = None
_httpd = None


@pytest.fixture(scope="module", autouse=True)
def live_server():
    global BASE, _httpd
    srv._Handler.web_enabled = False
    srv._Handler.upload_dir = tempfile.mkdtemp(prefix="m2a_test_uploads_")
    _httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
    t = threading.Thread(target=_httpd.serve_forever, daemon=True)
    t.start()
    BASE = f"http://127.0.0.1:{_httpd.server_address[1]}"
    yield
    _httpd.shutdown()


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, json.loads(r.read().decode() or "{}") if "json" in r.headers.get("Content-Type", "") else (r.status, r.read())


def _post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_health_and_dashboard():
    status, j = _get("/health")
    assert status == 200 and j["ok"] is True and j["web_enabled"] is False
    with urllib.request.urlopen(BASE + "/", timeout=10) as r:
        html = r.read().decode()
    assert r.status == 200 and "map2arcpy" in html and "/api/generate" in html


def test_examples_endpoint():
    status, j = _get("/api/examples")
    assert status == 200 and "choropleth" in j


def test_generate_from_description():
    status, j = _post("/api/generate", {
        "input": "buffer schools.shp by 500 m, epsg 32644, titled 'Walkability'"})
    assert status == 200
    ast.parse(j["script"])
    assert j["filename"] == "walkability.py"
    assert j["spec"]["crs_epsg"] == 32644
    assert "PairwiseBuffer" in j["script"]


def test_inspect_uploaded_lyrx():
    with open(os.path.join(EXAMPLES, "landuse.lyrx"), "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    status, j = _post("/api/inspect", {"file": {"name": "landuse.lyrx",
                                                "content_b64": b64}})
    assert status == 200
    assert j["spec"]["source_kind"] == "lyrx"
    assert j["spec"]["layers"][0]["renderer"]["type"] == "unique"


def test_web_request_without_web_server_gets_note():
    status, j = _post("/api/inspect", {"input": "parks.shp in Visakhapatnam",
                                       "web": True})
    assert status == 200
    assert any("without --web" in n for n in j["spec"]["notes"])


def test_bad_requests_are_clean_errors():
    status, j = _post("/api/generate", {})
    assert status == 400 and "error" in j
    status, j = _post("/api/generate", {"file": {"name": "x.exe", "content_b64": "aGk="}})
    assert status == 400 and "unsupported upload type" in j["error"]
    status, j = _post("/api/generate", {"file": {"name": "a.lyrx", "content_b64": "%%%"}})
    assert status == 400 and "base64" in j["error"]
    status, j = _post("/api/nope", {"input": "x"})
    assert status == 404


def test_strict_mode_via_api_returns_422():
    # buffer with no recognisable data source -> op input unresolved -> invalid
    status, j = _post("/api/generate", {"input": "buffer by 500 m", "strict": True})
    assert status == 422 and "error" in j
    # same input without strict generates with TODOs instead
    status, j = _post("/api/generate", {"input": "buffer by 500 m"})
    assert status == 200 and j["todos"] >= 1
