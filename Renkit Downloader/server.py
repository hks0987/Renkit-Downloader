"""The tiny local receiver (127.0.0.1:18123) that your browser extension talks to."""
import re
import json
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from common import (RepairError, check_url, get_setting, log_error, safe_int)


def start_local_server(app):
    extension_origins = ("chrome-extension://", "moz-extension://")

    class ExtensionHandler(BaseHTTPRequestHandler):
        def _host_ok(self):
            return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost")

        def _allowed(self):
            """Only your browser extension may talk to this server. A web page can never forge an
            extension Origin, so that is accepted as-is; otherwise a special header is required."""
            if not self._host_ok():
                return False
            origin = self.headers.get("Origin")
            if origin:
                return origin.startswith(extension_origins)
            return self.headers.get("X-ResumeFetch") == "1"

        def _reply(self, code, body=b""):
            self.send_response(code)
            origin = self.headers.get("Origin")
            if origin and origin.startswith(extension_origins):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ResumeFetch")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_OPTIONS(self):
            self._reply(204 if self._allowed() else 403)

        def do_GET(self):
            if self.path.split("?")[0] == "/ping":
                return self._reply(200, b'{"ok": true, "app": "Renkit"}') if self._host_ok() else self._reply(403, b"{}")
            if self.path.split("?")[0] != "/config":
                return self._reply(404, b"{}")
            if not self._allowed():
                return self._reply(403, b"{}")
            types = [x.strip().lower() for x in str(get_setting("file_types")).split() if x.strip()]
            sites = [x for x in str(get_setting("exclude_sites")).split() if x]
            self._reply(200, json.dumps({"enabled": True, "catch_all": bool(get_setting("catch_all")),
                                         "types": types, "exclude_sites": sites}).encode())

        def do_POST(self):
            try:
                if not self._allowed() or "json" not in (self.headers.get("Content-Type") or "").lower():
                    return self._reply(403, b'{"status":"forbidden"}')
                length = safe_int(self.headers.get("Content-Length"))
                if length <= 0 or length > 65536:
                    return self._reply(400, b'{"status":"bad request"}')
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict):
                    return self._reply(400, b'{"status":"bad request"}')
                check_url(data.get("url"))
                payload = {"url": data["url"]}
                for key, limit in (("filename", 300), ("referer", 2000), ("cookie", 8000), ("user_agent", 500), ("mime", 100)):
                    v = data.get(key)
                    if isinstance(v, str) and v.strip():
                        payload[key] = re.sub(r"[\r\n]", "", v.strip())[:limit]
                if "referer" in payload and not payload["referer"].lower().startswith(("http://", "https://")):
                    payload.pop("referer")
                if isinstance(data.get("size"), int) and data["size"] > 0:
                    payload["size"] = data["size"]
                app.events.put(("ext_link", payload))
                self._reply(200, b'{"status":"success"}')
            except RepairError:
                self._reply(400, b'{"status":"bad url"}')
            except Exception:
                self._reply(500)

        def log_message(self, format, *args):
            pass

    def run_server():
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 18123), ExtensionHandler)
            server.daemon_threads = True
            app.events.put(("server_ok", None))
            server.serve_forever()
        except OSError as e:
            app.events.put(("server_error", str(e)))
        except Exception:
            log_error("local server")

    threading.Thread(target=run_server, daemon=True).start()
