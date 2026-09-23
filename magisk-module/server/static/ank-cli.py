#!/data/local/ank/ankfs/usr/bin/python3
import sys, urllib.request, urllib.error, json, os
ANK_DIR = "/data/local/ank"
port = 8001
try:
    with open(f"{ANK_DIR}/logs/port.conf") as f:
        port = int(f.read().strip())
except Exception:
    pass

CONFIG_FILE = os.path.join(ANK_DIR, "config.json")
BASE = f"http://127.0.0.1:{port}"

def _load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _login():
    cfg = _load_config()
    user = cfg.get("username") or "ank"
    pwd = cfg.get("password") or "ank123"
    data = json.dumps({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json", "X-ANK-Client": "ank-cli"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read()).get("token", "")
    except Exception:
        return ""

prog = sys.argv[0].split("/")[-1]
args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
cmd = f"{prog} {args}".strip()
payload = json.dumps({"command": cmd}).encode()
headers = {"Content-Type": "application/json", "X-ANK-Client": "ank-cli"}

token = _login()
if token:
    headers["Authorization"] = f"Bearer {token}"

req = urllib.request.Request(
    f"{BASE}/api/system/shell",
    data=payload,
    headers=headers,
)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    if result.get("stdout"):
        sys.stdout.write(result["stdout"])
        if not result["stdout"].endswith("\n"):
            sys.stdout.write("\n")
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])
    sys.exit(result.get("code", 0))
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace")
    try:
        msg = json.loads(body).get("error", body)
    except Exception:
        msg = body or str(e)
    sys.stderr.write(f"Error: {msg}\n")
    sys.exit(1)
except Exception as e:
    sys.stderr.write(f"Error: {e}\n")
    sys.exit(1)
