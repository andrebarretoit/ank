#!/usr/bin/env python3
"""
ANK Node Proxy - WebSocket and HTTP proxy for remote node communication.
"""

import json
import urllib.request
import urllib.error


def _log(msg):
    print(f"[PROXY] {msg}", flush=True)


def _http_request(url, method="GET", data=None, headers=None, timeout=15):
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
    def __init__(self, node_manager):
        self.node_manager = node_manager

    def handle_api_proxy(self, node_id, method, path, body=None, headers=None):
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

    def get_node_shell_url(self, node_id):
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        return f"ws://{ip}:{port}/ws/shell?token={token}"

    def get_node_terminal_url(self, node_id, container_name):
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        return f"ws://{ip}:{port}/ws/terminal/{container_name}?token={token}"

    def get_containers(self, node_id):
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return []
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}/api/containers"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, headers=headers, timeout=15)
            if code == 200 and isinstance(body, list):
                return body
            elif code == 200 and isinstance(body, dict):
                return body.get("containers", [])
        except Exception as e:
            _log(f"get_containers failed: {e}")
        return []

    def get_stacks(self, node_id):
        config = self.node_manager._load_node_config(node_id)
        if not config:
            return []
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}/api/stacks"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, headers=headers, timeout=15)
            if code == 200 and isinstance(body, dict):
                return body.get("stacks", [])
            elif code == 200 and isinstance(body, list):
                return body
        except Exception as e:
            _log(f"get_stacks failed: {e}")
        return []
