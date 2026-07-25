"""
ANK Installer - Detection Cache
Caches compatibility test results to avoid re-running detection.
"""

import json
import os
import time
from typing import Optional, Dict

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".ank-installer", "cache")
CACHE_TTL = 86400  # 24 hours


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(serial: str) -> str:
    safe_serial = serial.replace(":", "_").replace(".", "_")
    return os.path.join(CACHE_DIR, f"detection_{safe_serial}.json")


def save_detection(serial: str, result_dict: Dict):
    _ensure_cache_dir()
    data = {
        "serial": serial,
        "timestamp": time.time(),
        "result": result_dict,
    }
    with open(_cache_path(serial), "w") as f:
        json.dump(data, f, indent=2)


def load_detection(serial: str) -> Optional[Dict]:
    path = _cache_path(serial)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > CACHE_TTL:
            return None
        return data.get("result")
    except Exception:
        return None


def clear_detection(serial: str):
    path = _cache_path(serial)
    if os.path.exists(path):
        os.remove(path)
