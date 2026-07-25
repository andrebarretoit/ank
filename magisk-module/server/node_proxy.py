#!/usr/bin/env python3
"""
ANK Node Proxy - WebSocket and HTTP proxy for remote node communication.

Proxies requests between the master panel and remote ANK nodes.
"""

import json
import urllib.request
import urllib.error


def _log(msg):
    print(f"[PROXY] {msg}", flush=True)


def _http_request(url, method="GET", data=None, headers=None, timeout=15):
    """Send an HTTP request and return (status_code, response_dict_or_bytes, content_type)."""
    if headers is None:
        headers = {}
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
        else:
            body = str(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "json" in ct:
                try:
                    return resp.status, json.loads(raw), ct
                except json.JSONDecodeError:
                    return resp.status, raw, ct
            return resp.status, raw, ct
    except urllib.error.HTTPError as e:
        ct = e.headers.get("Content-Type", "") if e.headers else ""
        raw = e.read() if e.fp else b""
        if "json" in ct:
            try:
                return e.code, json.loads(raw), ct
            except json.JSONDecodeError:
                pass
        return e.code, raw, ct
    except Exception:
        raise


class NodeProxy:
    """Proxies requests between the master panel and remote nodes."""

    def __init__(self, node_manager):
        self.node_manager = node_manager

    def handle_api_proxy(self, node_id, method, path, body=None, headers=None):
        """Proxy an HTTP API request to a remote node.

        Returns: (status_code, response_body, content_type)
        """
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return 404, {"error": "Node not found"}, "application/json"

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")

        url = f"http://{ip}:{port}{path}"
        fwd_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            for k, v in headers.items():
                if k.lower() not in ("authorization", "host", "content-length"):
                    fwd_headers[k] = v

        return _http_request(url, method=method, data=body, headers=fwd_headers, timeout=30)

    def handle_websocket_proxy(self, node_id, ws_path):
        """Get the WebSocket URL to connect to a remote node.

        The browser connects directly to the remote node's WebSocket.
        We just provide the URL with auth token.

        Returns: ws://<ip>:<port><ws_path>?token=...
        """
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return None

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")

        return f"ws://{ip}:{port}{ws_path}?token={token}"

    def get_node_shell_url(self, node_id):
        """Get WebSocket URL for shell on remote node.

        Returns: ws://<ip>:<port>/ws/shell?token=...&cols=...&rows=...
        """
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return None

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")

        return f"ws://{ip}:{port}/ws/shell?token={token}"

    def get_node_terminal_url(self, node_id, container_name):
        """Get WebSocket URL for container terminal on remote node.

        Returns: ws://<ip>:<port>/ws/terminal/<container>?token=...&cols=...&rows=...
        """
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return None

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")

        return f"ws://{ip}:{port}/ws/terminal/{container_name}?token={token}"
