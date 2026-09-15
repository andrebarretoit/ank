# ANK Container Status Bug — CRITICAL

## Problem
Container is RUNNING (sshd listening, services up, SSH accessible) but the web UI shows status "stopped" with PID "-". This causes the Start button to be locked, forcing the user to restart "on top" which causes SSH port collisions.

## Architecture
- Android device running Magisk + BusyBox sh
- Containers are chroot-based (shared_host mode = no namespaces)
- Python HTTP server (server.py) runs on device, serves web panel
- container.sh manages containers (create/start/stop/delete)
- ankd.sh runs INSIDE each container as service manager
- All containers share host network (shared_host mode)

## Container Lifecycle
1. `api_create_container()` → writes config.json with `"pid": null` → calls `container.sh create`
2. `api_start_container()` → sets status="starting" → calls `container.sh start` in thread
3. `container.sh start` → `nohup chroot ... &` → captures `$!` → scans /proc for real PID → writes PID via `sed -i` to config.json
4. `api_start_container` thread completes → re-reads config → sets status="running", saves
5. Frontend polls `GET /containers` → `api_list_containers()` → for each running container calls `should_mark_stopped()`

## Detection Chain (server.py)
```python
def check_container_running(name):
    pid = _pid_alive(name)      # reads config["pid"], does kill -0
    if pid: return True
    tcp = _sshd_port_open(name) # TCP connect to 127.0.0.1:ssh_port
    if tcp: return True
    health = _health_file_status(name)  # reads merged/tmp/ank-health
    if health: return True
    if pid is False: return False
    if tcp is False and health is not True: return False
    return True  # ambiguous, default to running
```

## Diagnostic Data (from device)
```
Config PIDs vs Real PIDs (ps -ef):
apache-static | config_pid=13114 | real_pid=13114 | ssh_port=2203 | MATCH ✓
nginx-static  | config_pid=13223 | real_pid=13223 | ssh_port=2201 | MATCH ✓
node.js-20    | config_pid=null  | real_pid=26089 | ssh_port=2205 | PID NULL ✗
php-8.2       | config_pid=12349 | real_pid=12349 | ssh_port=2204 | MATCH ✓
python-3.12   | config_pid=28206 | real_pid=28206 | ssh_port=2202 | MATCH ✓
```

ALL 5 containers are RUNNING (ps shows ankd.sh + sshd for each). But some show "stopped" in UI.

## What We've Tried (ALL FAILED to fix the status)

### Attempt 1: Health file (ankd writes UP/DOWN)
- ankd.sh writes to `$ANK_HEALTH_FILE` which was set to `/data/local/ank/containers/{name}/health`
- **FAILED**: ankd runs inside chroot, that path doesn't exist inside the container
- Fix: Changed to `/tmp/ank-health` (exists inside Alpine), server reads `merged/tmp/ank-health`
- **STILL FAILED**: SELinux blocks Python from reading files inside merged/

### Attempt 2: PID check via `kill -0`
- `container.sh` captures `$!` from `nohup chroot ... &`
- **FAILED**: `$!` might be the nohup wrapper PID, not the actual chroot process
- Fix: Added `/proc` scan — find process whose `/proc/<pid>/root` matches container rootfs
- **STILL FAILED**: Status still drops. The PID in config matches real PID (verified), but `check_container_running` STILL returns False somehow

### Attempt 3: TCP port check as definitive fallback
- If sshd port is listening → container is running
- **STILL FAILED**: Even with TCP check, status drops

### Attempt 4: Re-read config after start
- `api_start_container` was reading config BEFORE container.sh updated PID
- Fix: Re-read config after `run_script("container.sh", "start")` returns
- **STILL FAILED**

### Attempt 5: Debounce (should_mark_stopped)
- Requires 3 consecutive failures + 12s grace window after start
- **STILL FAILED**: Debounce doesn't help if the check ALWAYS returns False

## Critical Question
Given that:
1. PID in config matches real PID (verified with ps)
2. `kill -0 <PID>` should succeed (process is alive)
3. TCP port check should succeed (sshd is listening)
4. Container IS running (ssh works, services up)

**WHY does `check_container_running` return False?**

Possible causes we haven't ruled out:
- Is `load_container_config()` returning stale data? (race condition with concurrent writes?)
- Is `save_container_config()` in `api_list_containers` overwriting the PID to null?
- Is there a timing issue where the config is read while another thread is writing?
- Does the `/proc` scan for real PID actually work on this Android device?

## What We Need
A robust, bulletproof status detection that CANNOT produce false negatives. The container is either alive or dead. If it's alive, status MUST be "running". No exceptions.

Constraints:
- Must work on Android (BusyBox sh, no systemd, no cgroups available)
- Must survive concurrent config reads/writes
- Must not break existing functionality
- SELinux may block reading files inside container rootfs

## Files (copied to this folder)
- `server.py` — status detection, pull image, container CRUD, image management
- `container.sh` — container lifecycle (create/start/stop), PID capture, port allocation
- `ankd.sh` — service manager running INSIDE containers
- `app.js` — frontend (container cards, pull modal, detail modal)
- `index.html` — UI structure

## Other Known Issues (fix these too)

### Issue 2: Pull Image — Log doesn't stream during download phase
- `run_script_stream()` uses Popen with line-by-line reading
- Download phase (curl output) should stream in real-time but doesn't appear until build phase

### Issue 3: Container detail modal — PID shows "-" even when running
- The detail modal reads `config.pid` which may be null even when container is alive
- Should show actual PID from process scan, not just config value

## What We Need
A robust, bulletproof status detection that CANNOT produce false negatives. The container is either alive or dead. If it's alive, status MUST be "running". No exceptions.
