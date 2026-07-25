#!/data/local/ank/ankfs/usr/bin/python3
import sys, urllib.request, json
ANK_DIR = "/data/local/ank"
port = 8001
try:
    with open(f"{ANK_DIR}/logs/port.conf") as f:
        port = int(f.read().strip())
except Exception:
    pass
prog = sys.argv[0].split("/")[-1]
args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
cmd = f"{prog} {args}".strip()
data = json.dumps({"command": cmd}).encode()
req = urllib.request.Request(
    f"http://127.0.0.1:{port}/api/shell",
    data=data,
    headers={"Content-Type": "application/json"}
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
except Exception as e:
    sys.stderr.write(f"Error: {e}\n")
    sys.exit(1)
