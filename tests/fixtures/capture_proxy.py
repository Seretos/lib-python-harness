"""R0's live-probe capture channel (ticket #41, plan "Capture channel").

A tiny threaded localhost HTTP server that forwards every request verbatim
to `https://api.anthropic.com` (headers included — so whatever auth the
real `claude` CLI attaches, OAuth or API key, reaches the real API
unmodified) and streams the upstream response straight back, chunk for
chunk. Its only side effect beyond forwarding: any request body that JSON-
decodes and carries a top-level `"system"` key gets that key's value
appended, unmasked, as one line of a JSONL file — the one channel that
observes the literal bytes the CLI sent, as opposed to asking the model to
self-report its own instructions (unreliable per #37).

Never imported by `src/`; only `tests/test_base_prompt_live.py` (and this
module's own `claude_via_proxy.py` sibling) touch it. Not marked
`requires_claude` itself — it has no test functions — but every test that
starts it is.
"""
from __future__ import annotations

import http.client
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

UPSTREAM_HOST = "api.anthropic.com"
UPSTREAM_PORT = 443

# Headers that must never be copied verbatim between hops (either they
# describe *this* hop's framing, which the other side recomputes itself, or
# they would otherwise be duplicated).
_HOP_BY_HOP = {"connection", "transfer-encoding", "content-length", "host"}


class _ForwardingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Quiets the default per-request stdout logging; the JSONL capture file
    # is the record that matters here, not a request log on the console.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def _capture_system(self, body: bytes) -> None:
        if not body:
            return
        try:
            payload = json.loads(body)
        except ValueError:
            return
        if not isinstance(payload, dict) or "system" not in payload:
            return
        record = {"path": self.path, "system": payload["system"]}
        capture_path = Path(self.server.capture_path)  # type: ignore[attr-defined]
        with capture_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def _forward(self, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(content_length) if content_length else b""

        self._capture_system(body)

        conn = http.client.HTTPSConnection(
            UPSTREAM_HOST,
            UPSTREAM_PORT,
            context=ssl.create_default_context(),
            timeout=180,
        )
        forward_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in _HOP_BY_HOP
        }
        forward_headers["Host"] = UPSTREAM_HOST
        if body:
            forward_headers["Content-Length"] = str(len(body))
        try:
            conn.request(method, self.path, body=body or None, headers=forward_headers)
            upstream = conn.getresponse()
        except OSError as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"capture_proxy: upstream error: {exc}".encode())
            return

        chunked = "chunked" in (upstream.getheader("Transfer-Encoding") or "").lower()
        self.send_response(upstream.status, upstream.reason)
        for name, value in upstream.getheaders():
            if name.lower() in _HOP_BY_HOP:
                continue
            self.send_header(name, value)
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        try:
            while True:
                chunk = upstream.read(4096)
                if not chunk:
                    break
                if chunked:
                    self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii"))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                else:
                    self.wfile.write(chunk)
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            # The client (claude CLI) went away mid-stream; nothing more to
            # forward, and nothing this proxy should raise about.
            pass
        finally:
            conn.close()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        self._forward("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._forward("GET")


class CaptureProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    capture_path: str


def start_capture_proxy(capture_path: str | Path) -> tuple[CaptureProxyServer, threading.Thread, int]:
    """Start the proxy on an OS-assigned localhost port.

    Returns `(server, thread, port)`. The caller owns the server's
    lifetime — call `server.shutdown()` then `thread.join()` to stop it.
    """
    capture_file = Path(capture_path)
    capture_file.parent.mkdir(parents=True, exist_ok=True)
    server = CaptureProxyServer(("127.0.0.1", 0), _ForwardingHandler)
    server.capture_path = str(capture_file)
    thread = threading.Thread(target=server.serve_forever, name="capture-proxy", daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def stop_capture_proxy(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


if __name__ == "__main__":
    import sys
    import time

    out = sys.argv[1] if len(sys.argv) > 1 else "capture.jsonl"
    srv, th, port = start_capture_proxy(out)
    print(f"capture_proxy listening on 127.0.0.1:{port}, capturing to {out}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop_capture_proxy(srv, th)
