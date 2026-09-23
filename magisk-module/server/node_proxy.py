#!/usr/bin/env python3
"""
ANK Node Proxy - WebSocket and HTTP proxy for remote node communication.

Shares its HTTP client with node_manager.py (_http_request) instead of keeping a
second, drifting copy of the same request/response handling logic.
"""

from node_manager import _http_request


def _log(msg):
    print(f"[PROXY] {msg}", flush=True)


class NodeProxy:
    def __init__(self, node_manager):
        self.node_manager = node_manager

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
