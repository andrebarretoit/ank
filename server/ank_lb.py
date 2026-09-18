#!/usr/bin/env python3
"""ank-lb.py - Lightweight HTTP load balancer / reverse proxy for container stacks.

Usage:
    python3 ank-lb.py --port 30001 --backends "10.20.30.3:80,10.20.30.4:80" \
                       --algo least_conn --stack-name apache-static

Can also be imported as a module:
    from ank_lb import LoadBalancer
    lb = LoadBalancer(port=30001, backends=["10.20.30.3:80"], algo="round_robin")
    lb.start()
"""

import argparse
import hashlib
import http.server
import json
import os
import select
import socket
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEALTH_CHECK_INTERVAL = 5          # seconds between health‑check sweeps
HEALTH_CHECK_TIMEOUT  = 3          # seconds to wait for a single probe
HEALTH_FAIL_THRESHOLD = 3          # consecutive failures before removal
BACKEND_TIMEOUT       = 30         # seconds for proxy request to backend
BUFFER_SIZE           = 65536      # read buffer for proxy responses

VALID_ALGOS = ("round_robin", "least_connections", "ip_hash")


# ---------------------------------------------------------------------------
# Backend state
# ---------------------------------------------------------------------------

class BackendState:
    """Tracks runtime state for a single upstream backend."""

    __slots__ = (
        "addr", "healthy", "active_conns", "total_requests",
        "consecutive_failures", "lock",
    )

    def __init__(self, addr: str):
        self.addr = addr
        self.healthy = True
        self.active_conns = 0
        self.total_requests = 0
        self.consecutive_failures = 0
        self.lock = threading.Lock()

    def inc_conns(self):
        with self.lock:
            self.active_conns += 1

    def dec_conns(self):
        with self.lock:
            self.active_conns = max(0, self.active_conns - 1)

    def inc_requests(self):
        with self.lock:
            self.total_requests += 1

    def mark_healthy(self):
        with self.lock:
            self.healthy = True
            self.consecutive_failures = 0

    def mark_unhealthy(self):
        with self.lock:
            self.healthy = False

    def bump_failure(self) -> int:
        """Increment consecutive failure counter and return new count."""
        with self.lock:
            self.consecutive_failures += 1
            return self.consecutive_failures

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "addr": self.addr,
                "healthy": self.healthy,
                "active_conns": self.active_conns,
                "total_requests": self.total_requests,
                "consecutive_failures": self.consecutive_failures,
            }

    def __repr__(self):
        return f"<BackendState {self.addr} healthy={self.healthy} conns={self.active_conns}>"


# ---------------------------------------------------------------------------
# Load balancer core
# ---------------------------------------------------------------------------

class LoadBalancer:
    """Main load balancer that manages backends, selection algorithms and
    health checking.  Designed to be used as a module or run standalone."""

    def __init__(self, port: int, backends: list, algo: str = "round_robin",
                 stack_name: str = ""):
        if algo not in VALID_ALGOS:
            raise ValueError(f"algo must be one of {VALID_ALGOS}, got {algo!r}")

        self.port = port
        self.algo = algo
        self.stack_name = stack_name
        self._backends_lock = threading.Lock()
        self._backends: dict[str, BackendState] = {}
        self._rr_index = 0  # round‑robin cursor
        self._rr_lock = threading.Lock()  # dedicated lock for round-robin counter

        self._server = None
        self._server_thread = None
        self._health_thread = None
        self._running = False

        for addr in backends:
            self.add_backend(addr)

    # -- backend management -------------------------------------------------

    def add_backend(self, addr: str):
        addr = addr.strip()
        if not addr:
            return
        with self._backends_lock:
            if addr not in self._backends:
                self._backends[addr] = BackendState(addr)
                self._log(f"Added backend {addr}")

    def remove_backend(self, addr: str):
        addr = addr.strip()
        with self._backends_lock:
            if addr in self._backends:
                del self._backends[addr]
                self._log(f"Removed backend {addr}")

    def update_backends(self, backends: list):
        new_addrs = {b.strip() for b in backends if b.strip()}
        with self._backends_lock:
            # remove stale
            for addr in list(self._backends.keys()):
                if addr not in new_addrs:
                    del self._backends[addr]
            # add new
            for addr in new_addrs:
                if addr not in self._backends:
                    self._backends[addr] = BackendState(addr)

    def _healthy_addrs(self) -> list[str]:
        with self._backends_lock:
            return [addr for addr, st in self._backends.items() if st.healthy]

    def _get_state(self, addr: str) -> BackendState | None:
        with self._backends_lock:
            return self._backends.get(addr)

    # -- selection algorithms -----------------------------------------------

    def _pick_backend(self, client_ip: str = "") -> BackendState | None:
        healthy = self._healthy_addrs()
        if not healthy:
            return None

        with self._backends_lock:
            states = {addr: self._backends[addr] for addr in healthy}

        if self.algo == "round_robin":
            return self._pick_round_robin(states)
        elif self.algo == "least_connections":
            return self._pick_least_conn(states)
        elif self.algo == "ip_hash":
            return self._pick_ip_hash(states, client_ip)
        return None

    def _pick_round_robin(self, states: dict) -> BackendState | None:
        addrs = list(states.keys())
        if not addrs:
            return None
        with self._rr_lock:
            idx = self._rr_index % len(addrs)
            self._rr_index += 1
        return states[addrs[idx]]

    def _pick_least_conn(self, states: dict) -> BackendState | None:
        best = None
        for st in states.values():
            if best is None or st.active_conns < best.active_conns:
                best = st
        return best

    def _pick_ip_hash(self, states: dict, client_ip: str) -> BackendState | None:
        addrs = list(states.keys())
        if not addrs:
            return None
        h = int(hashlib.md5(client_ip.encode()).hexdigest(), 16)
        idx = h % len(addrs)
        return states[addrs[idx]]

    # -- health checking ----------------------------------------------------

    def _health_check_loop(self):
        while self._running:
            time.sleep(HEALTH_CHECK_INTERVAL)
            if not self._running:
                break
            with self._backends_lock:
                addrs = list(self._backends.keys())
            for addr in addrs:
                self._probe(addr)

    def _probe(self, addr: str):
        host, port_str = addr.rsplit(":", 1)
        try:
            port_num = int(port_str)
        except ValueError:
            self._log(f"Health check bad port {addr}")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(HEALTH_CHECK_TIMEOUT)
        try:
            sock.connect((host, port_num))
            # Try a quick HTTP GET on / or /health
            req = f"GET /health HTTP/1.0\r\nHost: {addr}\r\n\r\n"
            sock.sendall(req.encode())
            resp = sock.recv(1024)
            st = self._get_state(addr)
            if st and self._is_healthy_status(resp):
                st.mark_healthy()
            else:
                self._record_failure(addr)
        except Exception:
            self._record_failure(addr)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _is_healthy_status(resp: bytes) -> bool:
        """Parse HTTP response status line to check for 2xx status code."""
        try:
            status_line = resp.split(b"\r\n", 1)[0]
            parts = status_line.split(b" ", 2)
            if len(parts) >= 2:
                code = int(parts[1])
                return 200 <= code < 300
        except (ValueError, IndexError):
            pass
        return False

    def _record_failure(self, addr: str):
        st = self._get_state(addr)
        if st is None:
            return
        fails = st.bump_failure()
        if fails >= HEALTH_FAIL_THRESHOLD:
            st.mark_unhealthy()
            self._log(f"Backend {addr} marked unhealthy after {fails} failures")

    # -- proxy logic --------------------------------------------------------

    def _proxy_request(self, handler: "LBHandler"):
        client_ip = handler.client_address[0]
        backend = self._pick_backend(client_ip)
        if backend is None:
            handler.send_error(503, "No healthy backends available")
            return

        backend.inc_conns()
        backend.inc_requests()
        try:
            self._do_proxy(handler, backend)
        finally:
            backend.dec_conns()

    def _do_proxy(self, handler: "LBHandler", backend: BackendState):
        req = handler.request
        method = req.command
        path = req.path or "/"
        url = f"http://{backend.addr}{path}"

        # Read request body if present
        content_length = int(req.headers.get("Content-Length", 0))
        body = req.rfile.read(content_length) if content_length > 0 else None

        # Build headers to forward
        headers = {}
        for key in req.headers:
            if key.lower() in ("host", "transfer-encoding"):
                continue
            headers[key] = req.headers[key]
        headers["Host"] = backend.addr
        headers["X-Forwarded-For"] = handler.client_address[0]
        headers["X-Forwarded-Proto"] = "http"
        if self.stack_name:
            headers["X-LB-Stack"] = self.stack_name

        out_req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            resp = urllib.request.urlopen(out_req, timeout=BACKEND_TIMEOUT)
            status = resp.getcode()
            resp_headers = resp.headers.items()
            resp_body = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = e.headers.items() if e.headers else []
            resp_body = e.read() if hasattr(e, "read") else b""
        except Exception as e:
            self._log(f"Backend {backend.addr} error: {e}")
            handler.send_error(502, f"Bad Gateway: {e}")
            return

        # Send response
        handler.send_response(status)
        skip = {"transfer-encoding", "connection", "content-length"}
        for key, val in resp_headers:
            if key.lower() not in skip:
                handler.send_header(key, val)
        handler.send_header("Content-Length", str(len(resp_body)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(resp_body)

        self._log(f"{method} {path} -> {backend.addr} {status}")

    # -- metrics ------------------------------------------------------------

    def get_metrics(self) -> dict:
        with self._backends_lock:
            backends = [st.to_dict() for st in self._backends.values()]
        return {
            "stack_name": self.stack_name,
            "algo": self.algo,
            "port": self.port,
            "backends": backends,
        }

    # -- start / stop -------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True

        server_class = _make_server_class(self)
        self._server = server_class(("0.0.0.0", self.port), LBHandler)

        self._server_thread = threading.Thread(target=self._server.serve_forever,
                                               daemon=True, name="lb-serve")
        self._server_thread.start()

        self._health_thread = threading.Thread(target=self._health_check_loop,
                                               daemon=True, name="lb-health")
        self._health_thread.start()

        self._log(f"Load balancer started on port {self.port} algo={self.algo}")

    def stop(self):
        self._running = False
        if self._server:
            self._server.shutdown()
        self._log("Load balancer stopped")

    def _log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        prefix = f"[{self.stack_name}] " if self.stack_name else ""
        print(f"{ts} {prefix}LB {msg}", flush=True)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class LBHandler(http.server.BaseHTTPRequestHandler):
    """Handle a single inbound HTTP request and proxy it upstream."""

    # Set by _make_server_class so every handler instance can reach the LB.
    lb: LoadBalancer = None  # type: ignore[assignment]

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_OPTIONS(self):
        self._handle()

    def _handle(self):
        if self.path == "/_lb/metrics":
            self._serve_metrics()
            return
        if self.path == "/_lb/health":
            self._serve_self_health()
            return
        self.lb._proxy_request(self)

    def _serve_metrics(self):
        data = json.dumps(self.lb.get_metrics(), indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_self_health(self):
        data = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # Suppress default access log; we do our own logging in _do_proxy.
        pass


# ---------------------------------------------------------------------------
# Threaded server (allows concurrent requests)
# ---------------------------------------------------------------------------

class _ThreadedHTTPServer(http.server.HTTPServer):
    """HTTPServer subclass that spawns a thread per request."""

    daemon_threads = True
    allow_reuse_address = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address),
                             daemon=True)
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def _make_server_class(lb: LoadBalancer):
    """Return a server class with the *lb* reference baked in."""
    class _Server(_ThreadedHTTPServer):
        pass
    _Server.lb = lb  # type: ignore[attr-defined]
    return _Server


# Patch handler class to carry the lb reference from the server.
_orig_handler_init = LBHandler.__init__

def _patched_handler_init(self, *args, **kwargs):
    _orig_handler_init(self, *args, **kwargs)
    # The server that created us carries the lb reference.
    if hasattr(self, "server") and hasattr(self.server, "lb"):
        self.__class__.lb = self.server.lb

LBHandler.__init__ = _patched_handler_init  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ank-lb: lightweight HTTP load balancer")
    parser.add_argument("--port", type=int, required=True,
                        help="Port to listen on (30000‑39999)")
    parser.add_argument("--backends", type=str, default="",
                        help="Comma‑separated list of ip:port backends")
    parser.add_argument("--algo", type=str, default="round_robin",
                        choices=list(VALID_ALGOS),
                        help="Load balancing algorithm")
    parser.add_argument("--stack-name", type=str, default="",
                        help="Logical stack name for logging / metrics")
    args = parser.parse_args()

    backend_list = [b.strip() for b in args.backends.split(",") if b.strip()]

    lb = LoadBalancer(
        port=args.port,
        backends=backend_list,
        algo=args.algo,
        stack_name=args.stack_name,
    )
    lb.start()

    # Keep main thread alive so daemon threads keep running.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        lb.stop()


if __name__ == "__main__":
    main()
