"""Local editor for the power set spec. Binds to 127.0.0.1 only.

usage: python editor/serve.py [--port 8765] [--spec spec/spirit_binding.json]
then open http://localhost:8765
"""
import argparse
import datetime
import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from generate import Gen  # noqa: E402

CONFIG = os.path.join(HERE, "local_config.json")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/catalog.json": ("catalog.json", "application/json")}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    spec_path = None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _local_only(self):
        # Reject DNS-rebinding style requests from pages that aren't this editor.
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("localhost", "127.0.0.1"):
            self.send_error(403, "localhost only")
            return False
        return True

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._local_only():
            return
        if self.path in STATIC:
            name, ctype = STATIC[self.path]
            p = os.path.join(HERE, name)
            if not os.path.exists(p):
                return self._send(404, {"error": f"{name} missing. Run tools/build_catalog.py."})
            with open(p, "rb") as f:
                return self._send(200, f.read(), ctype)
        if self.path == "/api/spec":
            return self._send(200, load_json(self.spec_path, {}))
        if self.path == "/api/config":
            return self._send(200, load_json(CONFIG, {"data_root": ""}))
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        if not self._local_only():
            return
        try:
            body = self._body()
        except json.JSONDecodeError as e:
            return self._send(400, {"error": f"bad JSON: {e}"})
        if self.path == "/api/spec":
            if body.get("schema") != 1 or not isinstance(body.get("pets"), list):
                return self._send(400, {"error": "not a schema-1 spec"})
            hist = os.path.join(ROOT, "spec", "history")
            os.makedirs(hist, exist_ok=True)
            if os.path.exists(self.spec_path):
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(self.spec_path, os.path.join(hist, f"{stamp}.json"))
            save_json(self.spec_path, body)
            return self._send(200, {"ok": True})
        if self.path == "/api/config":
            save_json(CONFIG, {"data_root": str(body.get("data_root", ""))})
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._local_only():
            return
        if self.path != "/api/generate":
            return self._send(404, {"error": "not found"})
        data_root = load_json(CONFIG, {}).get("data_root", "")
        if not data_root or not os.path.isdir(data_root):
            return self._send(400, {"error": "Set the data root (the maintainers' source tree) first."})
        spec = load_json(self.spec_path, {})
        catalog = load_json(os.path.join(HERE, "catalog.json"), {})
        out = os.path.join(ROOT, "out")
        g = Gen(spec, data_root, catalog).run()
        g.write(out)
        self._send(200, {"errors": g.errors, "warnings": g.warnings, "notes": g.notes,
                         "files": sorted(g.outputs), "out": out, "report": g.report()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--spec", default=os.path.join(ROOT, "spec", "spirit_binding.json"))
    a = ap.parse_args()
    Handler.spec_path = os.path.abspath(a.spec)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Spirit set editor: http://localhost:{a.port}  (spec: {Handler.spec_path})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
