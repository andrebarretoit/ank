#!/usr/bin/env python3
"""
ANK Node Manager - Multi-node management for ANK (Proxmox-style).

Manages remote ANK nodes, heartbeats, pairing, and aggregated dashboard.
"""

import os
import json
import time
import threading
import urllib.request
import urllib.error
import secrets
import tarfile
import io
from datetime import datetime, timezone
from urllib.parse import urlencode

ANK_DIR = os.environ.get("ANK_DIR", "/data/local/ank")
NODES_DIR = os.path.join(ANK_DIR, "nodes")
PAIRING_DIR = os.path.join(NODES_DIR, "pairing")
IMAGES_DIR = os.path.join(ANK_DIR, "images")
CONFIG_FILE = os.path.join(ANK_DIR, "config.json")


def _log(msg):
    print(f"[NODE] {msg}", flush=True)


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_id():
    return secrets.token_hex(12)


def _load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o666)
    except Exception:
        pass


def _http_request(url, method="GET", data=None, headers=None, timeout=10):
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
    except Exception:
        raise


class NodeManager:
    def __init__(self):
        os.makedirs(NODES_DIR, exist_ok=True)
        os.makedirs(PAIRING_DIR, exist_ok=True)
        self._heartbeat_thread = None
        self._running = False
        self._lock = threading.Lock()

    # ============================================================
    # Heartbeat
    # ============================================================

    def start_heartbeat(self, interval=30):
        if self._running:
            return
        self._running = True
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(interval,), daemon=True)
        self._heartbeat_thread.start()
        _log(f"Heartbeat started (interval={interval}s)")

    def stop_heartbeat(self):
        self._running = False
        _log("Heartbeat stopped")

    def _heartbeat_loop(self, interval):
        while self._running:
            try:
                self._check_all_nodes()
                self._sync_manager_info()
            except Exception as e:
                _log(f"Heartbeat error: {e}")
            time.sleep(interval)

    def _check_all_nodes(self):
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
                    if config.get("status") != "pending":
                        config["fail_count"] = config.get("fail_count", 0) + 1
                        if config["fail_count"] >= 3:
                            config["status"] = "offline"
                    config["last_seen"] = _utcnow()
            except Exception:
                if config.get("status") != "pending":
                    config["fail_count"] = config.get("fail_count", 0) + 1
                    if config["fail_count"] >= 3:
                        config["status"] = "offline"
                config["last_seen"] = _utcnow()
            self._save_node_config(node_id, config)

    def _sync_manager_info(self):
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if not config or config.get("role") != "manager":
                continue
            ip = config.get("ip", "")
            port = config.get("port", 8001)
            token = config.get("token", "")
            try:
                headers = {"Authorization": f"Bearer {token}"}
                code, info, _ = _http_request(f"http://{ip}:{port}/api/system/info", headers=headers, timeout=10)
                if code == 200 and isinstance(info, dict):
                    new_name = info.get("node_name", "")
                    if new_name and new_name != config.get("alias"):
                        config["alias"] = new_name
                        config["managed_by"] = new_name
                        self._save_node_config(node_id, config)
            except Exception:
                pass

    # ============================================================
    # Node CRUD
    # ============================================================

    def list_nodes(self):
        nodes = []
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if config:
                nodes.append(self._sanitize_node(config))
        return nodes

    def get_node(self, node_id):
        config = self._load_node_config(node_id)
        if not config:
            return None
        return self._sanitize_node(config)

    def get_manager_info(self):
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if config and config.get("role") == "manager":
                return {
                    "alias": config.get("alias", ""),
                    "ip": config.get("ip", ""),
                    "managed_by": config.get("managed_by", ""),
                    "status": config.get("status", ""),
                    "last_seen": config.get("last_seen", ""),
                    "device_model": config.get("device_model", "")
                }
        return None

    def revoke_manager(self):
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if config and config.get("role") == "manager":
                self._delete_node_config(node_id)
                _log(f"Manager revoked: {config.get('alias', node_id)}")
                return True
        return False

    def _delete_node_config(self, node_id):
        path = self._node_config_path(node_id)
        if os.path.isfile(path):
            os.remove(path)

    def add_node(self, config):
        ip = config.get("ip", "")
        port = int(config.get("port", 8001))
        user = config.get("user", "")
        password = config.get("password", "")
        alias = config.get("alias", "")
        my_name = _load_config().get("node_name", "")

        if not ip:
            raise ValueError("IP address is required")

        url = f"http://{ip}:{port}/api/auth/login"
        login_data = {"username": user, "password": password}
        code, body, _ = _http_request(url, method="POST", data=login_data, timeout=10)
        if code != 200 or not isinstance(body, dict):
            raise ConnectionError(f"Failed to authenticate with node {ip}:{port} (HTTP {code})")
        token = body.get("token", "")
        if not token:
            raise ConnectionError("No token received from node")

        device_model = ""
        kernel = ""
        node_name = ""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            code, info, _ = _http_request(f"http://{ip}:{port}/api/system/info", headers=headers, timeout=10)
            if code == 200 and isinstance(info, dict):
                device_model = info.get("device_model", info.get("model", ""))
                kernel = info.get("kernel", info.get("kernel_version", ""))
                node_name = info.get("node_name", "")
                if not alias:
                    alias = node_name or device_model or ip
        except Exception:
            if not alias:
                alias = ip

        node_id = f"node-{_generate_id()}"
        node_config = {
            "id": node_id,
            "alias": alias,
            "ip": ip,
            "port": port,
            "user": user,
            "token": token,
            "status": "online",
            "role": "managed",
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
        path = self._node_config_path(node_id)
        if os.path.isfile(path):
            os.remove(path)
            _log(f"Node removed: {node_id}")
            return True
        return False

    # ============================================================
    # Pairing (Manager side - sends request to remote)
    # ============================================================

    def send_pairing_request(self, config):
        ip = config.get("ip", "")
        port = int(config.get("port", 8001))
        user = config.get("user", "")
        password = config.get("password", "")
        alias = config.get("alias", "")
        my_name = _load_config().get("node_name", "ANK Manager")

        if not ip:
            raise ValueError("IP address is required")

        url = f"http://{ip}:{port}/api/auth/login"
        login_data = {"username": user, "password": password}
        code, body, _ = _http_request(url, method="POST", data=login_data, timeout=10)
        if code != 200 or not isinstance(body, dict):
            raise ConnectionError(f"Failed to authenticate with node {ip}:{port} (HTTP {code})")
        token = body.get("token", "")
        if not token:
            raise ConnectionError("No token received from node")

        device_model = ""
        kernel = ""
        node_name = ""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            code, info, _ = _http_request(f"http://{ip}:{port}/api/system/info", headers=headers, timeout=10)
            if code == 200 and isinstance(info, dict):
                device_model = info.get("device_model", info.get("model", ""))
                kernel = info.get("kernel", info.get("kernel_version", ""))
                node_name = info.get("node_name", "")
                if not alias:
                    alias = node_name or device_model or ip
        except Exception:
            if not alias:
                alias = ip

        pairing_payload = {
            "manager_name": my_name,
            "manager_ip": config.get("manager_ip", "") or self._detect_own_ip(ip),
            "alias": alias,
            "token": token,
            "device_model": device_model,
            "kernel": kernel
        }
        code2, body2, _ = _http_request(
            f"http://{ip}:{port}/api/nodes/pairing/request",
            method="POST", data=pairing_payload, headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        if code2 != 200:
            raise ConnectionError(f"Node rejected pairing request (HTTP {code2})")

        node_id = f"node-{_generate_id()}"
        node_config = {
            "id": node_id,
            "alias": alias,
            "ip": ip,
            "port": port,
            "user": user,
            "token": token,
            "status": "pending",
            "role": "managed",
            "last_seen": _utcnow(),
            "fail_count": 0,
            "device_model": device_model,
            "kernel": kernel,
            "created_at": _utcnow()
        }
        self._save_node_config(node_id, node_config)
        _log(f"Pairing request sent: {alias} @ {ip}:{port}")
        return self._sanitize_node(node_config)

    # ============================================================
    # Pairing (Remote side - receives and manages requests)
    # ============================================================

    def receive_pairing_request(self, data):
        manager_name = data.get("manager_name", "Unknown Manager")
        manager_ip = data.get("manager_ip", "")
        alias = data.get("alias", "")
        token = data.get("token", "")
        device_model = data.get("device_model", "")
        kernel = data.get("kernel", "")

        req_id = f"req-{_generate_id()}"
        req = {
            "id": req_id,
            "manager_name": manager_name,
            "manager_ip": manager_ip,
            "alias": alias,
            "token": token,
            "device_model": device_model,
            "kernel": kernel,
            "status": "pending",
            "created_at": _utcnow()
        }
        path = os.path.join(PAIRING_DIR, f"{req_id}.json")
        with open(path, "w") as f:
            json.dump(req, f, indent=2)
        _log(f"Pairing request received from {manager_name} ({manager_ip})")
        return req

    def list_pairing_requests(self):
        requests = []
        if not os.path.isdir(PAIRING_DIR):
            return requests
        for fname in os.listdir(PAIRING_DIR):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(PAIRING_DIR, fname)) as f:
                        req = json.load(f)
                    if req.get("status") == "pending":
                        requests.append(req)
                except Exception:
                    pass
        return requests

    def approve_pairing_request(self, req_id):
        path = os.path.join(PAIRING_DIR, f"{req_id}.json")
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            req = json.load(f)
        if req.get("status") != "pending":
            return None

        req["status"] = "approved"
        req["approved_at"] = _utcnow()
        with open(path, "w") as f:
            json.dump(req, f, indent=2)

        node_id = f"node-{_generate_id()}"
        mgr_alias = req.get("manager_name", "") or req.get("device_model", "") or req.get("manager_ip", "Manager")
        node_config = {
            "id": node_id,
            "alias": mgr_alias,
            "ip": req.get("manager_ip", ""),
            "port": 8001,
            "user": "",
            "token": req.get("token", ""),
            "status": "online",
            "role": "manager",
            "last_seen": _utcnow(),
            "fail_count": 0,
            "device_model": req.get("device_model", ""),
            "kernel": req.get("kernel", ""),
            "managed_by": mgr_alias,
            "created_at": _utcnow()
        }
        self._save_node_config(node_id, node_config)
        _log(f"Pairing approved: {req.get('manager_name')} ({req_id})")
        return self._sanitize_node(node_config)

    def reject_pairing_request(self, req_id):
        path = os.path.join(PAIRING_DIR, f"{req_id}.json")
        if not os.path.isfile(path):
            return False
        with open(path) as f:
            req = json.load(f)
        req["status"] = "rejected"
        req["rejected_at"] = _utcnow()
        with open(path, "w") as f:
            json.dump(req, f, indent=2)
        _log(f"Pairing rejected: {req.get('manager_name')} ({req_id})")
        return True

    def is_remote_management_enabled(self):
        config = _load_config()
        return config.get("enable_remote_management", False)

    def set_remote_management(self, enabled):
        config = _load_config()
        config["enable_remote_management"] = bool(enabled)
        _save_config(config)

    # ============================================================
    # Remote node queries
    # ============================================================

    def get_node_containers(self, node_id):
        return self._node_api_get(node_id, "/api/containers")

    def get_node_images(self, node_id):
        return self._node_api_get(node_id, "/api/images")

    def get_node_status(self, node_id):
        return self._node_api_get(node_id, "/api/status")

    def get_node_system_info(self, node_id):
        return self._node_api_get(node_id, "/api/system/info")

    def get_node_logs(self, node_id):
        return self._node_api_get(node_id, "/api/logs")

    # ============================================================
    # Remote container management
    # ============================================================

    def create_container_on_node(self, node_id, config):
        return self._node_api_post(node_id, "/api/containers", config)

    def start_container_on_node(self, node_id, container_name):
        return self._node_api_post(node_id, f"/api/containers/{container_name}/start", {})

    def stop_container_on_node(self, node_id, container_name):
        return self._node_api_post(node_id, f"/api/containers/{container_name}/stop", {})

    def restart_container_on_node(self, node_id, container_name):
        return self._node_api_post(node_id, f"/api/containers/{container_name}/restart", {})

    def delete_container_on_node(self, node_id, container_name):
        return self._node_api_delete(node_id, f"/api/containers/{container_name}")

    def exec_container_on_node(self, node_id, container_name, cmd):
        return self._node_api_post(node_id, f"/api/containers/{container_name}/exec", {"command": cmd})

    def get_container_logs_on_node(self, node_id, container_name):
        return self._node_api_get(node_id, f"/api/containers/{container_name}/logs")

    # ============================================================
    # Remote image management
    # ============================================================

    def pull_image_on_node(self, node_id, version):
        return self._node_api_post(node_id, "/api/images/pull", {"version": version})

    def transfer_image_to_node(self, node_id, image_name):
        config = self._load_node_config(node_id)
        if not config:
            return {"error": "Node not found"}

        src_path = os.path.join(IMAGES_DIR, image_name)
        if not os.path.isdir(src_path):
            return {"error": f"Image '{image_name}' not found locally"}

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            tar.add(src_path, arcname=image_name)
        tar_data = tar_buffer.getvalue()

        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}/api/images/upload"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
        req = urllib.request.Request(url, data=tar_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                try:
                    return json.loads(raw)
                except Exception:
                    return {"ok": True, "message": f"Image '{image_name}' transferred"}
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # Aggregate dashboard
    # ============================================================

    def aggregate_dashboard(self):
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
                "role": node_config.get("role", "managed"),
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
                        node_entry["cpu_percent"] = info.get("cpu_usage", info.get("cpu_percent", 0))
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
                        node_entry["containers_running"] = sum(1 for c in containers if c.get("status") == "running")
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
        return {k: v for k, v in config.items() if k != "password" and k != "token"}

    def _node_api_get(self, node_id, path):
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

    def _detect_own_ip(self, remote_ip=""):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if remote_ip:
                s.connect((remote_ip, 80))
            else:
                s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass
        try:
            hostname = socket.gethostname()
            return socket.gethostbyname(hostname)
        except Exception:
            return ""
