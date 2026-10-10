#!/usr/bin/env python3
"""ank_portproxy.py - userspace TCP port forwarder for isolated containers.

Replaces the iptables DNAT/REDIRECT rules previously applied by
network.sh apply_ports / container.sh setup_ssh_forward. Each mapping is a
small TCP listener on 0.0.0.0:host_port that pumps bytes to
target_ip:target_port - no root networking required, works the same on
every device.

Can also be imported as a module:
    from ank_portproxy import PortProxyManager
    ppm = PortProxyManager()
    ppm.ensure(30001, "10.20.30.3", 80)
    ppm.reconcile({30001: ("10.20.30.3", 80)})
    ppm.release(30001)
"""

import select
import socket
import threading
from datetime import datetime, timezone

BUFFER_SIZE = 65536          # pump buffer (same as ank_lb)
ACCEPT_TIMEOUT = 1.0         # accept loop wakeup so stop() is snappy
CONNECT_TIMEOUT = 5.0        # outbound connect to the container


# ---------------------------------------------------------------------------
# One forwarded port
# ---------------------------------------------------------------------------

class _ProxyEntry:
    """A single 0.0.0.0:host_port listener pumping to target_ip:target_port."""

    __slots__ = ("host_port", "target_ip", "target_port", "_sock",
                 "_running", "_accept_thread")

    def __init__(self, host_port: int, target_ip: str, target_port: int):
        self.host_port = host_port
        self.target_ip = target_ip
        self.target_port = target_port
        self._sock = None
        self._running = False
        self._accept_thread = None

    @property
    def target(self) -> str:
        return f"{self.target_ip}:{self.target_port}"

    def start(self, log) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self.host_port))
            sock.listen(64)
        except OSError as e:
            try:
                sock.close()
            except OSError:
                pass
            log(f"port {self.host_port} unavailable ({e}) - skipping forward "
                f"to {self.target}")
            return False
        sock.settimeout(ACCEPT_TIMEOUT)
        self._sock = sock
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, args=(log,), daemon=True,
            name=f"pp-{self.host_port}")
        self._accept_thread.start()
        log(f"forward 0.0.0.0:{self.host_port} -> {self.target}")
        return True

    def stop(self, log):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        log(f"stopped forward 0.0.0.0:{self.host_port} -> {self.target}")

    def _accept_loop(self, log):
        while self._running:
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._handle_client, args=(client, log),
                                 daemon=True)
            t.start()

    def _handle_client(self, client: socket.socket, log):
        upstream = None
        try:
            upstream = socket.create_connection(
                (self.target_ip, self.target_port), timeout=CONNECT_TIMEOUT)
            client.settimeout(None)
            upstream.settimeout(None)
            t = threading.Thread(
                target=self._pump, args=(client, upstream), daemon=True)
            t.start()
            self._pump(upstream, client)
            t.join(timeout=5)
        except Exception as e:
            log(f"forward {self.host_port} -> {self.target}: {e}")
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

    @staticmethod
    def _pump(src: socket.socket, dst: socket.socket):
        """Copy src -> dst until EOF; half-close dst's write side so the
        peer sees the EOF even when the other direction is still open."""
        try:
            while True:
                r, _, _ = select.select([src], [], [], 60)
                if not r:
                    break
                data = src.recv(BUFFER_SIZE)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class PortProxyManager:
    """Owns all forward entries; ensure/release/reconcile are idempotent."""

    def __init__(self, log=None):
        self._lock = threading.Lock()
        self._entries: dict[int, _ProxyEntry] = {}
        self._log_fn = log

    # -- logging ------------------------------------------------------------

    def _log(self, msg: str):
        if self._log_fn is not None:
            self._log_fn(msg)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            print(f"{ts} portproxy {msg}", flush=True)

    # -- public API ---------------------------------------------------------

    def ensure(self, host_port: int, target_ip: str, target_port: int) -> bool:
        """Make sure host_port forwards to target_ip:target_port. Returns
        False only when the port cannot be bound (already in use)."""
        host_port = int(host_port)
        target_port = int(target_port)
        with self._lock:
            entry = self._entries.get(host_port)
            if entry is not None:
                if (entry.target_ip == target_ip
                        and entry.target_port == target_port
                        and entry._running):
                    return True  # already correct - idempotent
                entry.stop(self._log)  # target changed or dead listener
            entry = _ProxyEntry(host_port, target_ip, target_port)
            if not entry.start(self._log):
                self._entries.pop(host_port, None)
                return False
            self._entries[host_port] = entry
            return True

    def release(self, host_port: int):
        """Stop the forward on host_port (no-op when absent)."""
        host_port = int(host_port)
        with self._lock:
            entry = self._entries.pop(host_port, None)
        if entry is not None:
            entry.stop(self._log)

    def reconcile(self, desired: dict):
        """Apply the full desired mapping: ensure every entry, release
        every stale one. desired: {host_port: (target_ip, target_port)}."""
        norm = {}
        for hp, tgt in desired.items():
            ip, tp = tgt
            norm[int(hp)] = (str(ip), int(tp))
        with self._lock:
            stale = [hp for hp in self._entries if hp not in norm]
        for hp in stale:
            self.release(hp)
        for hp, (ip, tp) in norm.items():
            self.ensure(hp, ip, tp)

    def stop_all(self):
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.stop(self._log)

    def snapshot(self) -> dict:
        """{host_port: "ip:port"} for status endpoints / tests."""
        with self._lock:
            return {hp: e.target for hp, e in self._entries.items()}


# ---------------------------------------------------------------------------
# Standalone entry point (optional; server.py runs it in-process)
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ank-portproxy: TCP forwarder")
    parser.add_argument("--port", type=int, required=True,
                        help="Host port to listen on")
    parser.add_argument("--target", type=str, required=True,
                        help="Target ip:port inside the container network")
    args = parser.parse_args()
    tip, tport = args.target.rsplit(":", 1)

    ppm = PortProxyManager()
    if not ppm.ensure(args.port, tip, int(tport)):
        raise SystemExit(1)
    try:
        while True:
            import time
            time.sleep(3600)
    except KeyboardInterrupt:
        ppm.stop_all()


if __name__ == "__main__":
    main()
