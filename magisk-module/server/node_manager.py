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
        os.chmod(CONFIG_FILE, 0o600)
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

    @staticmethod
    def _outbound_token(config):
        """Token used for calls WE make to the peer. A manager-role record keeps the
        token we use to call home in manager_token (minted by the manager), while
        token holds the peer-minted token they use to call us."""
        if config.get("role") == "manager":
            return config.get("manager_token") or config.get("token", "")
        return config.get("token", "")

    def _relogin(self, config):
        """Re-authenticate with a node whose token stopped working (peer restart,
        24h expiry, revoked pairing). Needs user+password stored in the node config."""
        if config.get("role") == "manager":
            return False
        user = config.get("user", "")
        password = config.get("password", "")
        if not user or not password:
            return False
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        try:
            code, body, _ = _http_request(
                f"http://{ip}:{port}/api/auth/login",
                method="POST",
                data={"username": user, "password": password},
                timeout=10,
            )
        except Exception:
            return False
        if code == 200 and isinstance(body, dict) and body.get("token"):
            config["token"] = body["token"]
            config["fail_count"] = 0
            _log(f"Re-authenticated with node {ip}:{port}")
            return True
        return False

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
            token = self._outbound_token(config)
            url = f"http://{ip}:{port}/api/status"
            online = False
            code = None
            try:
                headers = {"Authorization": f"Bearer {token}"}
                code, body, _ = _http_request(url, headers=headers, timeout=5)
                online = (code == 200)
            except Exception:
                online = False

            # Auth died (restart/expiry/revocation) -> try a fresh login once
            if not online and code in (401, 403) and self._relogin(config):
                token = self._outbound_token(config)
                try:
                    headers = {"Authorization": f"Bearer {token}"}
                    code, body, _ = _http_request(url, headers=headers, timeout=5)
                    online = (code == 200)
                except Exception:
                    online = False

            if online:
                config["status"] = "online"
                config["fail_count"] = 0
            else:
                if config.get("status") != "pending":
                    config["fail_count"] = config.get("fail_count", 0) + 1
                    if config["fail_count"] >= 3:
                        config["status"] = "offline"
            config["last_seen"] = _utcnow()

            if online:
                try:
                    self._fetch_and_store_node_stats(node_id, config)
                except Exception as e:
                    _log(f"Stats refresh failed for {node_id}: {e}")

            self._save_node_config(node_id, config)

    def _fetch_and_store_node_stats(self, node_id, config):
        """Poll a node's live /api/status + /api/system/info (and container/image/stack
        counts) and cache the result onto its config so list_nodes()/the dashboard reflect
        real, current numbers instead of placeholder dashes."""
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = self._outbound_token(config)
        headers = {"Authorization": f"Bearer {token}"}

        try:
            code, status, _ = _http_request(f"http://{ip}:{port}/api/status", headers=headers, timeout=8)
            if code == 200 and isinstance(status, dict):
                config["cpu_percent"] = status.get("cpu_usage", 0)
                config["containers_total"] = status.get("containers_total", 0)
                config["containers_running"] = status.get("containers_running", 0)
                disk = status.get("disk", {}) or {}
                config["disk_used_gb"] = disk.get("used", 0)
                config["disk_total_gb"] = disk.get("total", 0)
                config["uptime_seconds"] = status.get("uptime", 0)
        except Exception as e:
            _log(f"stats(status) failed for {node_id}: {e}")

        try:
            code, info, _ = _http_request(f"http://{ip}:{port}/api/system/info", headers=headers, timeout=8)
            if code == 200 and isinstance(info, dict):
                mem = info.get("memory", {}) or {}
                total_kb = mem.get("total_kb", 0)
                avail_kb = mem.get("available_kb", 0)
                if total_kb:
                    used_kb = max(total_kb - avail_kb, 0)
                    config["mem_total_gb"] = round(total_kb / (1024 * 1024), 2)
                    config["mem_used_gb"] = round(used_kb / (1024 * 1024), 2)
                    config["mem_percent"] = round(used_kb / total_kb * 100, 1)
                config["cpu_cores"] = info.get("cpu_cores", 0)
                if info.get("device_model"):
                    config["device_model"] = info.get("device_model")
                if info.get("kernel"):
                    config["kernel"] = info.get("kernel")
        except Exception as e:
            _log(f"stats(system/info) failed for {node_id}: {e}")

        try:
            images = self._node_api_get(node_id, "/api/images")
            config["images_count"] = len(images) if isinstance(images, list) else 0
        except Exception:
            pass

        try:
            stacks = self.get_node_stacks(node_id)
            config["stacks_count"] = len(stacks) if isinstance(stacks, list) else 0
        except Exception:
            pass

        return config

    def refresh_node(self, node_id):
        """Actively poll a node right now (used by the manual Refresh button), instead of
        just re-serving whatever the last heartbeat cycle happened to cache."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        try:
            headers = {"Authorization": f"Bearer {self._outbound_token(config)}"}
            code, body, _ = _http_request(f"http://{ip}:{port}/api/status", headers=headers, timeout=8)
            if code in (401, 403) and self._relogin(config):
                headers = {"Authorization": f"Bearer {self._outbound_token(config)}"}
                code, body, _ = _http_request(f"http://{ip}:{port}/api/status", headers=headers, timeout=8)
            if code == 200:
                config["status"] = "online"
                config["fail_count"] = 0
                self._fetch_and_store_node_stats(node_id, config)
            else:
                config["fail_count"] = config.get("fail_count", 0) + 1
                if config["fail_count"] >= 3:
                    config["status"] = "offline"
        except Exception as e:
            _log(f"refresh_node failed for {node_id}: {e}")
            config["fail_count"] = config.get("fail_count", 0) + 1
            if config["fail_count"] >= 3:
                config["status"] = "offline"
        config["last_seen"] = _utcnow()
        self._save_node_config(node_id, config)
        return self._sanitize_node(config)

    def _sync_manager_info(self):
        for node_id in self._list_node_ids():
            config = self._load_node_config(node_id)
            if not config or config.get("role") != "manager":
                continue
            ip = config.get("ip", "")
            port = config.get("port", 8001)
            token = self._outbound_token(config)
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

    def get_node_connection(self, node_id):
        """Unsanitized connection info (ip/port/token) for proxies that need to talk to
        the node directly, e.g. the remote-shell WebSocket relay."""
        config = self._load_node_config(node_id)
        if not config:
            return None
        return {
            "ip": config.get("ip", ""),
            "port": config.get("port", 8001),
            "token": config.get("token", ""),
            "alias": config.get("alias", ""),
            "status": config.get("status", "")
        }

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
            "password": password,
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
            "manager_token": config.get("manager_token", ""),
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
            "password": password,
            "token": token,
            "manager_token": config.get("manager_token", ""),
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
        manager_token = data.get("manager_token", "")
        device_model = data.get("device_model", "")
        kernel = data.get("kernel", "")

        req_id = f"req-{_generate_id()}"
        req = {
            "id": req_id,
            "manager_name": manager_name,
            "manager_ip": manager_ip,
            "alias": alias,
            "token": token,
            "manager_token": manager_token,
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
            "manager_token": req.get("manager_token", ""),
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

    def get_node_stacks(self, node_id):
        result = self._node_api_get(node_id, "/api/stacks")
        if isinstance(result, dict):
            return result.get("stacks", [])
        if isinstance(result, list):
            return result
        return []

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
        """Build the manager-side aggregate view from each node's cached heartbeat stats
        (see _fetch_and_store_node_stats). This avoids re-polling every node on every
        dashboard load and uses field names that actually exist on node config."""
        total_containers = 0
        running = 0
        stopped = 0
        images = 0
        stacks = 0
        node_list = []

        for node_config in self.list_nodes():
            status = node_config.get("status", "offline")
            is_online = status == "online"

            containers_total = node_config.get("containers_total", 0) if is_online else 0
            containers_running = node_config.get("containers_running", 0) if is_online else 0
            images_count = node_config.get("images_count", 0) if is_online else 0
            stacks_count = node_config.get("stacks_count", 0) if is_online else 0

            node_entry = {
                "id": node_config["id"],
                "alias": node_config.get("alias", ""),
                "status": status,
                "role": node_config.get("role", "managed"),
                "ip": node_config.get("ip", ""),
                "cpu_percent": node_config.get("cpu_percent", 0) if is_online else 0,
                "mem_percent": node_config.get("mem_percent", 0) if is_online else 0,
                "mem_used_gb": node_config.get("mem_used_gb", 0) if is_online else 0,
                "mem_total_gb": node_config.get("mem_total_gb", 0) if is_online else 0,
                "disk_used_gb": node_config.get("disk_used_gb", 0) if is_online else 0,
                "disk_total_gb": node_config.get("disk_total_gb", 0) if is_online else 0,
                "uptime_seconds": node_config.get("uptime_seconds", 0) if is_online else 0,
                "containers_running": containers_running,
                "containers_total": containers_total,
                "images_count": images_count,
                "stacks_count": stacks_count,
                "device_model": node_config.get("device_model", ""),
                "kernel": node_config.get("kernel", "")
            }

            total_containers += containers_total
            running += containers_running
            stopped += max(containers_total - containers_running, 0)
            images += images_count
            stacks += stacks_count
            node_list.append(node_entry)

        return {
            "total_containers": total_containers,
            "running": running,
            "stopped": stopped,
            "images": images,
            "stacks": stacks,
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
            os.chmod(path, 0o600)
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

    def _extract_error_message(self, body, code):
        if isinstance(body, dict):
            return body.get("error") or body.get("message") or f"Remote node returned HTTP {code}"
        if isinstance(body, bytes):
            try:
                text = body.decode("utf-8", "replace").strip()
                return text[:300] if text else f"Remote node returned HTTP {code}"
            except Exception:
                pass
        return f"Remote node returned HTTP {code}"

    def _node_api_post(self, node_id, path, data):
        config = self._load_node_config(node_id)
        if not config:
            return {"error": "Node not found", "status_code": 404}
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, method="POST", data=data, headers=headers, timeout=30)
            if 200 <= code < 300:
                return body if isinstance(body, (dict, list)) else {"ok": True}
            err_msg = self._extract_error_message(body, code)
            _log(f"API POST {node_id}{path} -> HTTP {code}: {err_msg}")
            return {"error": err_msg, "status_code": code}
        except Exception as e:
            _log(f"API POST failed for {node_id}{path}: {e}")
            return {"error": str(e), "status_code": 502}

    def _node_api_delete(self, node_id, path):
        config = self._load_node_config(node_id)
        if not config:
            return {"error": "Node not found", "status_code": 404}
        ip = config.get("ip", "")
        port = config.get("port", 8001)
        token = config.get("token", "")
        url = f"http://{ip}:{port}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            code, body, _ = _http_request(url, method="DELETE", headers=headers, timeout=15)
            if 200 <= code < 300:
                return body if isinstance(body, (dict, list)) else {"ok": True}
            err_msg = self._extract_error_message(body, code)
            _log(f"API DELETE {node_id}{path} -> HTTP {code}: {err_msg}")
            return {"error": err_msg, "status_code": code}
        except Exception as e:
            _log(f"API DELETE failed for {node_id}{path}: {e}")
            return {"error": str(e), "status_code": 502}

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
