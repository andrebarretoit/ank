#!/usr/bin/env python3
"""
ANK Node Manager - Multi-node management for ANK (Proxmox-style).

Manages remote ANK nodes, heartbeats, and aggregated dashboard.
"""

import os
import json
import time
import threading
import urllib.request
import urllib.error
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
NODES_DIR = os.path.join(ANK_DIR, "nodes")


def _log(msg):
    print(f"[NODE] {msg}", flush=True)


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_id():
    return secrets.token_hex(12)


def _http_request(url, method="GET", data=None, headers=None, timeout=10):
    """Send an HTTP request and return (status_code, response_dict_or_bytes, content_type)."""
    if headers is None:
        headers = {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
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
    except Exception as e:
        raise


class NodeManager:
    def __init__(self):
        os.makedirs(NODES_DIR, exist_ok=True)
        self._heartbeat_thread = None
        self._running = False
        self._lock = threading.Lock()

    # ============================================================
    # Heartbeat
    # ============================================================

    def start_heartbeat(self, interval=30):
        """Start background heartbeat checker."""
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(interval,), daemon=True)
        self._heartbeat_thread.start()
        _log(f"Heartbeat started (interval={interval}s)")

    def stop_heartbeat(self):
        """Stop heartbeat."""
        self._running = False
        _log("Heartbeat stopped")

    def _heartbeat_loop(self, interval):
        while self._running:
            try:
                self._check_all_nodes()
            except Exception as e:
                _log(f"Heartbeat error: {e}")
            time.sleep(interval)

    def _check_all_nodes(self):
        """Ping all nodes, update status, mark offline after 3 consecutive failures."""
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if not config:
                continue
            ip = config.get("ip", "")
            port = config.get("port", 8001)
            token = config.get("token", "")
            url = f"http://{ip}:{port}/api/status"
            try:
                headers = {"Authorization": f"Bearer {token}"}
                code, body, _ = _http_request(url, headers=headers, timeout=5)
                if code == 200:
                    config["status"] = "online"
                    config["fail_count"] = 0
                    config["last_seen"] = _utcnow()
                else:
                    config["fail_count"] = config.get("fail_count", 0) + 1
                    if config["fail_count"] >= 3:
                        config["status"] = "offline"
                    config["last_seen"] = _utcnow()
            except Exception:
                config["fail_count"] = config.get("fail_count", 0) + 1
                if config["fail_count"] >= 3:
                    config["status"] = "offline"
                config["last_seen"] = _utcnow()
            self._save_node_config(node_id, config)

    # ============================================================
    # Node CRUD
    # ============================================================

    def list_nodes(self):
        """List all nodes with status."""
        nodes = []
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if config:
                nodes.append(self._sanitize_node(config))
        return nodes

    def get_node(self, node_id):
        """Get node details."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        return self._sanitize_node(config)

    def add_node(self, config):
        """Register a new node.

        config: {
            "ip": "192.168.1.50",
            "port": 8001,
            "user": "admin",
            "password": "admin123",
            "alias": "ank-prod01"  # optional
        }
        """
        ip = config.get("ip", "")
        port = int(config.get("port", 8001))
        user = config.get("user", "")
        password = config.get("password", "")
        alias = config.get("alias", "")

        if not ip:
            raise ValueError("IP address is required")

        # Step 1: Authenticate
        url = f"http://{ip}:{port}/api/auth/login"
        login_data = {"username": user, "password": password}
        code, body, _ = _http_request(url, method="POST", data=login_data, timeout=10)
        if code != 200 or not isinstance(body, dict):
            raise ConnectionError(f"Failed to authenticate with node {ip}:{port} (HTTP {code})")
        token = body.get("token", "")
        if not token:
            raise ConnectionError("No token received from node")

        # Step 2: Get device info
        device_model = ""
        kernel = ""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            code, info, _ = _http_request(f"http://{ip}:{port}/api/system/info", headers=headers, timeout=10)
            if code == 200 and isinstance(info, dict):
                device_model = info.get("device_model", info.get("model", ""))
                kernel = info.get("kernel", info.get("kernel_version", ""))
                if not alias:
                    alias = device_model or ip
        except Exception:
            if not alias:
                alias = ip

        # Step 3: Save node config
        node_id = f"node-{_generate_id()}"
        node_config = {
            "id": node_id,
            "alias": alias,
            "ip": ip,
            "port": port,
            "user": user,
            "token": token,
            "status": "online",
            "last_seen": _utcnow(),
            "fail_count": 0,
            "device_model": device_model,
            "kernel": kernel,
            "created_at": _utcnow()
        }
        self._save_node_config(node_id, node_config)
        _log(f"Node added: {node_id} ({alias} @ {ip}:{port})")
        return self._sanitize_node(node_config)

    def remove_node(self, node_id):
        """Remove a node."""
        path = self._node_config_path(node_id)
        if os.path.isfile(path):
            os.remove(path)
            _log(f"Node removed: {node_id}")
            return True
        return False

    # ============================================================
    # Remote node queries
    # ============================================================

    def get_node_containers(self, node_id):
        """Get containers from remote node."""
        return self._node_api_get(node_id, "/api/containers")

    def get_node_images(self, node_id):
        """Get images from remote node."""
        return self._node_api_get(node_id, "/api/images")

    def get_node_status(self, node_id):
        """Get full status (cpu, mem, disk, uptime, containers)."""
        return self._node_api_get(node_id, "/api/status")

    def get_node_system_info(self, node_id):
        """Get system info from node."""
        return self._node_api_get(node_id, "/api/system/info")

    def get_node_logs(self, node_id):
        """Get server logs from node."""
        return self._node_api_get(node_id, "/api/logs")

    # ============================================================
    # Remote container management
    # ============================================================

    def create_container_on_node(self, node_id, config):
        """Create container on remote node."""
        return self._node_api_post(node_id, "/api/containers", config)

    def start_container_on_node(self, node_id, container_name):
        """Start a container on remote node."""
        return self._node_api_post(node_id, f"/api/containers/{container_name}/start", {})

    def stop_container_on_node(self, node_id, container_name):
        """Stop a container on remote node."""
        return self._node_api_post(node_id, f"/api/containers/{container_name}/stop", {})

    def delete_container_on_node(self, node_id, container_name):
        """Delete a container on remote node."""
        return self._node_api_delete(node_id, f"/api/containers/{container_name}")

    # ============================================================
    # Aggregate dashboard
    # ============================================================

    def aggregate_dashboard(self):
        """Aggregate data from all online nodes for the master dashboard."""
        total_containers = 0
        running = 0
        stopped = 0
        images = 0
        node_list = []

        for node_config in self.list_nodes():
            node_id = node_config["id"]
            status = node_config.get("status", "offline")

            node_entry = {
                "id": node_id,
                "alias": node_config.get("alias", ""),
                "status": status,
                "ip": node_config.get("ip", ""),
                "cpu_percent": 0,
                "mem_percent": 0,
                "mem_used": "0 GB",
                "mem_total": "0 GB",
                "disk_used": "0 GB",
                "disk_total": "0 GB",
                "uptime": "0s",
                "containers_running": 0,
                "containers_total": 0,
                "device_model": node_config.get("device_model", ""),
                "kernel": node_config.get("kernel", "")
            }

            if status == "online":
                try:
                    info = self.get_node_status(node_id)
                    if isinstance(info, dict):
                        node_entry["cpu_percent"] = info.get("cpu_percent", 0)
                        node_entry["mem_percent"] = info.get("mem_percent", 0)
                        node_entry["mem_used"] = info.get("mem_used", "0 GB")
                        node_entry["mem_total"] = info.get("mem_total", "0 GB")
                        node_entry["disk_used"] = info.get("disk_used", "0 GB")
                        node_entry["disk_total"] = info.get("disk_total", "0 GB")
                        node_entry["uptime"] = info.get("uptime", "0s")
                        node_entry["containers_running"] = info.get("containers_running", 0)
                        node_entry["containers_total"] = info.get("containers_total", 0)
                except Exception:
                    pass

                try:
                    containers = self.get_node_containers(node_id)
                    if isinstance(containers, list):
                        node_entry["containers_total"] = len(containers)
                        node_cont_running = sum(1 for c in containers if c.get("status") == "running")
                        node_entry["containers_running"] = node_cont_running
                except Exception:
                    pass

                try:
                    img_list = self.get_node_images(node_id)
                    if isinstance(img_list, list):
                        images += len(img_list)
                except Exception:
                    pass

            total_containers += node_entry["containers_total"]
            running += node_entry["containers_running"]
            stopped += node_entry["containers_total"] - node_entry["containers_running"]
            node_list.append(node_entry)

        return {
            "total_containers": total_containers,
            "running": running,
            "stopped": stopped,
            "images": images,
            "nodes": node_list
        }

    # ============================================================
    # Proxy helpers
    # ============================================================

    def proxy_request(self, node_id, method, path, data=None):
        """Proxy an HTTP request to a remote node.

        Returns: (status_code, response_body, content_type)
        """
        config = self._load_node_config(node_id)
        if not config:
            return 404, {"error": "Node not found"}, "application/json"

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        return _http_request(url, method=method, data=data, headers=headers, timeout=30)

    def proxy_websocket_url(self, node_id, path):
        """Get WebSocket URL for a remote node.

        Returns: ws://<ip>:<port><path>?token=...
        """
        config = self._load_node_config(node_id)
        if not config:
            return None

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        return f"ws://{ip}:{port}{path}?token={token}"

    # ============================================================
    # Internal helpers
    # ============================================================

    def _list_node_ids(self):
        """List all registered node IDs from disk."""
        ids = []
        if not os.path.isdir(NODES_DIR):
            return ids
        for fname in os.listdir(NODES_DIR):
            if fname.endswith(".json"):
                ids.append(fname[:-5])
        return ids

    def _node_config_path(self, node_id):
        return os.path.join(NODES_DIR, f"{node_id}.json")

    def _load_node_config(self, node_id):
        path = self._node_config_path(node_id)
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_node_config(self, node_id, config):
        os.makedirs(NODES_DIR, exist_ok=True)
        path = self._node_config_path(node_id)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        try:
            os.chmod(path, 0o666)
        except Exception:
            pass

    def _sanitize_node(self, config):
        """Return node config without exposing password."""
        return {k: v for k, v in config.items() if k != "password"}

    def _node_api_get(self, node_id, path):
        """GET request to a remote node, returns parsed JSON or None."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, headers=headers, timeout=15)
            if code == 200 and isinstance(body, (dict, list)):
                return body
        except Exception as e:
            _log(f"API GET failed for {node_id}{path}: {e}")
        return None

    def _node_api_post(self, node_id, path, data):
        """POST request to a remote node, returns parsed JSON or None."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, method="POST", data=data, headers=headers, timeout=30)
            if isinstance(body, (dict, list)):
                return body
        except Exception as e:
            _log(f"API POST failed for {node_id}{path}: {e}")
        return None

    def _node_api_delete(self, node_id, path):
        """DELETE request to a remote node, returns parsed JSON or None."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, method="DELETE", headers=headers, timeout=15)
            if isinstance(body, (dict, list)):
                return body
        except Exception as e:
            _log(f"API DELETE failed for {node_id}{path}: {e}")
        return None
