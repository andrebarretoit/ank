# ANK Container Platform — Container Status Bug

## Context

ANK is a container platform for rooted Android devices. It manages Linux containers (Alpine) via:
- **server.py** — Python HTTP API server (port 8001), orchestrates everything
- **container.sh** — Bash script for container lifecycle (create, start, stop, delete)
- **ankd.sh** — Service manager daemon running inside each container as PID 1

The platform runs on Android with BusyBox, no systemd, limited /proc access, and SELinux restrictions.

## The Bug

Container status flips from `running` to `stopped` while the container is actually alive and working (SSH accessible, services running). This happens intermittently — sometimes seconds after start, sometimes minutes.

## How Status Works (Current Flow)

### Status State Machine
```
building → stopped (after create)
stopped → starting → running (after start)
running → stopping → stopped (after stop)
running → stopped (auto-detection by api_list_containers)
```

### 1. Container Start Flow
```
Frontend → POST /containers/{name}/start
  → api_start_container():
      1. Sets config.status = "starting", saves to config.json
      2. Spawns background thread:
         a. Runs: container.sh start {name}
         b. container.sh creates PID via chroot (captures $! as PID)
         c. container.sh writes marker: echo "running" > $ROOTFS/tmp/ankd-running
         d. container.sh writes PID to config.json: sed -i "pid": $PID
         e. Thread loads config, sets status = "running", saves
  → Frontend polls via pollContainerStatus()
```

### 2. Auto-Detection (the problem)
```
Every 15s, frontend calls GET /containers
  → api_list_containers():
      For each container:
        1. Load config.json
        2. If config.status == "running":
           → Call check_container_running(name)
           → If returns False: set status = "stopped", pid = None, save
        3. Return config to frontend
```

### 3. check_container_running() (current code)
```python
def check_container_running(name):
    # Check 1: marker file
    marker = os.path.join(CONTAINERS_DIR, name, "merged", "tmp", "ankd-running")
    try:
        if os.path.exists(marker):
            return True
    except Exception:
        pass
    # Check 2: PID alive via kill -0
    config = load_container_config(name)
    if not config:
        return False
    pid = config.get("pid")
    if pid:
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ProcessLookupError, ValueError):
            pass
    return False
```

### 4. Stop Flow
```
Frontend → POST /containers/{name}/stop
  → api_stop_container():
      1. Sets config.status = "stopping", saves
      2. Spawns thread:
         a. Runs: container.sh stop {name}
         b. container.sh kills processes in phases (ankd, services, sweep)
         c. container.sh removes marker: rm -f $ROOTFS/tmp/ankd-running
         d. container.sh sets status = "stopped", pid = null in config.json
         e. Thread also sets status = "stopped", pid = None, saves
```

## Why Status Might Flip to "stopped" Incorrectly

Both check mechanisms are failing:

### Marker File Issue
- container.sh creates marker at `$CONTAINERS_DIR/{name}/merged/tmp/ankd-running` from HOST side
- server.py checks the same path via os.path.exists()
- But the file might not be visible because:
  - In isolated/shared_network mode: overlayfs mounts the rootfs. The host writes to `merged/tmp/` which goes to upperdir. If overlay isn't set up correctly, host might not see the file.
  - In shared_host mode: rootfs is a plain `cp -a` copy, so the file SHOULD be visible
  - Android SELinux might block file access between the Python process and the shell-created file
  - The marker file might be inside a mount namespace that Python can't see

### PID Issue
- PID is captured as `$!` after `nohup chroot ... &` in container.sh
- This is the PID of the outer shell process that runs chroot
- In shared_host mode (no PID namespace), this PID should be visible from host
- But: if ankd restarts sshd or other services, the original PID might die while children keep running
- Also: `os.kill(int(pid), 0)` might fail on Android due to SELinux even when process is alive

### Race Conditions
- api_start_container thread sets status = "running" AFTER container.sh returns
- But api_list_containers might poll during the "starting" window and not find marker yet
- If api_list_containers runs right after thread finishes but before next save, it might see old status

## Environment Constraints

- **Android host**: SELinux enforcing, limited /proc access, no systemd
- **Alpine containers**: BusyBox (ash shell), no bash
- **shared_host mode**: No PID namespace, no network namespace, chroot only. All PIDs visible from host.
- **overlayfs**: Only in isolated/shared_network modes. In shared_host mode, rootfs is just a copied directory.
- **Files live at**: `/data/local/ank/containers/{name}/merged/`
- **Config at**: `/data/local/ank/containers/{name}/config.json`

## What We Need

Fix `check_container_running()` and the status flow so that:

1. Status NEVER flips to "stopped" while the container is actually running
2. The check works reliably across all modes (shared_host, shared_network, isolated)
3. No false positives from race conditions
4. Handle Android SELinux restrictions gracefully
5. Consider using `/proc/{PID}/status` or `/proc/{PID}/ns/pid` as alternative checks

## Files to Modify

- `server/server.py` — Main file. Functions: `check_container_running()`, `api_list_containers()`, `api_start_container()`, `api_stop_container()`
- `server/container.sh` — Marker creation/removal, PID capture
- `server/ankd/ankd.sh` — Service management daemon (if PID tracking needs changes)

## Constraints for the Fix

- Must work on Android with BusyBox ash shell
- Cannot rely on /proc/*/cmdline (SELinux blocks it)
- Cannot use pgrep/pkill (might not be available or reliable)
- The Python server runs as root on the Android host
- Keep the fix simple — prefer robustness over elegance
- Do NOT use exec -a (breaks sshd re-exec)
- Do NOT add new dependencies
