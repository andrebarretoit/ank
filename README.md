<div align="center">

# ANK

**Android Konteiner**

Docker-like container platform for Android — runs Linux containers via chroot/PRoot with a full web UI, REST API, and CLI.

[![Shell](https://img.shields.io/badge/Shell-100%25-4EAA25?style=flat&logo=gnu-bash&logoColor=white)](https://www.gnu.org/software/bash/)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Magisk](https://img.shields.io/badge/Magisk-20.4%2B-F44336?style=flat&logo=android&logoColor=white)](https://www.magiskapp.com/)
[![License](https://img.shields.io/badge/License-AKSAL--1.0-FF6B35.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-2.0.0-2196F3)](https://github.com/andrebarretoit/ank)
[![Platform](https://img.shields.io/badge/Platform-Android-3DDC84?style=flat&logo=android&logoColor=white)](https://www.android.com/)

<br>

[andrebarreto.work](https://andrebarreto.work) · [GitHub](https://github.com/andrebarretoit) · [LinkedIn](https://linkedin.com/in/andrebarretoit)

</div>

---

## What is ANK?

**ANK** (**A**ndroid **K**onteiner) is a container engine for Android that runs Linux containers via Magisk root + chroot. It also works without root via PRoot (Lite mode). No compilation needed — everything is shell scripts and a Python HTTP server with a Portainer-style web panel.

```
 ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                            ANK ENGINE                                            │
 │                                                                                                  │
 │               Web Panel (Port 8001)    │    REST API    │    Magisk Module / PRoot               │
 │              HTML/CSS/JS + xterm.js     │    Python3     │    post-fs-data / bootstrap           │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                                    Bridge ank0 │ iptables NAT                                    │
 ├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│                          Alpine Linux (Chroot / PRoot) │ ankd service daemon                     │
  │                          ank-alpinebase: openssh + bash + busybox + shadow + openssl + python3   │
 │                          Python 3.12 | ~20MB rootfs | SSL/TLS                                    │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Features

- **Chroot/PRoot containers** — Alpine Linux rootfs with Python 3 pre-installed
- **GUI Installer** — Graphical installer for Windows (PySide6/Qt6 + ADB)
- **5 enterprise tiers** — Progressive isolation based on kernel capability
- **Lite mode** — Works without root via PRoot (userspace emulation)
- **Web panel** — Portainer-style dark UI on `localhost:8001`
- **Interactive terminal** — xterm.js + WebSocket for host shell and container terminal
- **Container SSH** — Direct SSH access via web terminal or external SSH client
- **Image templates** — One-click deploy: Python, Nginx, Apache, PHP, Node.js
- **Ankfile** — Build custom images from Ankfile (like Dockerfile) with `PASSWD` support
- **Pull Image** — Download and build images from the web panel (Alpine, ank-alpinebase)
- **File Explorer** — Browse, edit, create, rename and delete files inside containers
- **File upload** — Upload static sites directly to containers (HTML/CSS/JS/ZIP)
- **Shell** — `ank` and `ank-core` commands from the web terminal + real host commands
- **Realtime log streaming** — Build/deploy/start/stop output via 1s polling
- **Realtime stats** — CPU, memory, uptime, container status
- **Port mapping** — Forward device ports to containers (TCP)
- **Auto port increment** — Conflicting ports auto-increment (+1)
- **Auto-start** — ANK server and services restore on boot via Magisk (`service.d`)
- **ankd service daemon** — Lightweight service management via shell scripts
- **Security** — Token Bearer auth, self-signed HTTPS, rate limiting, security headers
- **Complete uninstall** — Uninstall via panel with full removal
- **Stacks** — Manage container groups with load balancing and auto-scaling
- **Load Balancer** — Python reverse proxy for stacks with health check
- **Auto-scaling** — Automatic scaling based on triggers (CPU, memory, requests/sec)
- **Backups** — Backup routines via sshpass+scp with scheduling and retention
- **Multi-device nodes** — Manage multiple remote ANK devices via HTTP API
- **Shared volumes** — Bind mount from host into stack containers
- **Ankfile in Stacks** — Deploy custom images via Ankfile within stacks

---

## Screenshots

> Screenshots are generated during release builds (`screenshots/`).

---

## Requirements

| Requirement | Rooted (Full) | No Root (Lite) |
|------------|---------------|----------------|
| Android | Any device with Magisk | Any Android 5+ |
| Magisk | v20.4+ | None |
| Kernel | 3.10+ | N/A |
| ADB | Required for install | Required for install |
| Storage | ~200MB for rootfs + containers | ~150MB for rootfs |
| RAM | ~50MB for the server | ~30MB for the server |

---

## Installation

### Option 1: GUI Installer (Recommended — Windows)

1. Download `ANK-Installer.exe` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Connect your Android device via USB with ADB enabled
3. Run the installer — it detects your device, kernel tier, and installs automatically
4. Access `http://<device-ip>:8001`

### Option 2: Magisk Module (Rooted Devices)

1. Download `ank-magisk.zip` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Open Magisk Manager → Modules → Install from storage → select the zip
3. Reboot your device
4. Open `http://localhost:8001`
5. Login with `admin` / `admin123`

### Option 3: Lite Mode (No Root)

1. Download `ANK-Installer.exe` or use `adb push` to send rootfs + PRoot to the device
2. Run `ank-lite-bootstrap.sh` on the device:
   ```bash
   adb shell sh /data/local/ank/scripts/ank-lite-bootstrap.sh
   ```
3. Start the server:
   ```bash
   adb shell sh /data/local/ank/scripts/start-lite.sh
   ```
4. Access `http://localhost:8001`

---

## Quick Start

1. **Install** ANK using one of the methods above
2. **Open** the web panel at `http://<device-ip>:8001`
3. **Login** with `admin` / `admin123`
4. **Pull an image** — Go to Images → Pull `alpine-3.20` or `ank-alpinebase`
5. **Deploy a container** — Go to Containers → Create, or use a template:
   ```bash
   ank deploy nginx my-site
   ```
6. **Access your container** — Open the terminal in the web panel or use SSH:
   ```bash
   ssh root@<device-ip> -p 2200
   ```

---

## Web Panel

The web panel is the primary interface for managing ANK.

| Setting | Value |
|---------|-------|
| URL | `http://<device-ip>:8001` |
| Username | `admin` |
| Password | `admin123` |
| Config file | `/data/local/ank/config.json` |

> Change the default password immediately via Settings in the web panel.

---

## SSH Access

Each container gets an SSH server. Connect via:

```bash
# Host ANK SSH (port from config ssh_port, default 2200)
ssh root@<device-ip> -p 2200

# Container SSH (auto-assigned from 2201+; see ank inspect <name>)
ssh root@<device-ip> -p <container-ssh-port>

# Password is set per-container (default: the password defined at deploy time)
```

You can also access containers directly from the web terminal — no SSH client needed.

---

## CLI Commands

### `ank` — Container Management

| Command | Description |
|---------|-------------|
| `ank ps` | List containers (name, status, IP) |
| `ank start <name>` | Start a container |
| `ank stop <name>` | Stop a container |
| `ank restart <name>` | Restart a container |
| `ank rm <name>` | Delete a container |
| `ank logs <name>` | View container logs |
| `ank exec <name> <cmd>` | Execute command inside container |
| `ank inspect <name>` | Show container info (JSON) |
| `ank images` | List downloaded images |
| `ank templates` | List available templates |
| `ank deploy <template> <name>` | Deploy a template |
| `ank build -i <file>` | Build image from custom Ankfile |
| `ank pull <image>` | Download base image |

### `ank-core` — System Administration

| Command | Description |
|---------|-------------|
| `ank-core status` | Engine status + container counts |
| `ank-core restart` | Restart the ANK server |
| `ank-core shell` | Host shell (outside chroot) |
| `ank-core info` | Device info (kernel, memory, CPU) |
| `ank-core network` | Network configuration |
| `ank-core clean` | Clean orphaned containers |
| `ank-core logs` | View server logs |
| `ank --man <cmd>` | Detailed help for a command |

---

## Container Management

### Deploy from Templates

| Template | Packages | Port | ANK Page |
|----------|----------|------|----------|
| Alpine 3.20 | Base image | — | — |
| Python 3.12 | python3, pip | 5000 | Yes |
| Nginx Static | nginx | 8080 | Yes |
| Apache Static | apache2 | 8080 | Yes |
| PHP 8.2 | php82, php82-mbstring, php82-json | 8080 | Yes |
| Node.js 20 | nodejs, npm | 3000 | Yes |

Deploy from the web panel or via CLI:

```bash
ank deploy nginx my-site
```

### Build Custom Images (Ankfile)

Create an `Ankfile` (similar to a Dockerfile):

```dockerfile
FROM alpine-3.20
RUN apk add --allow-untrusted nginx
RUN mkdir -p /var/www/html
RUN echo "<h1>Custom ANK Image</h1>" > /var/www/html/index.html
PASSWD mysecretpass
EXPOSE 8080
```

| Instruction | Description |
|-------------|-------------|
| `FROM <image>` | Base image (required) |
| `RUN <cmd>` | Execute command during build |
| `EXPOSE <port>` | Expose port |
| `WORKDIR <path>` | Set working directory |
| `PASSWD <password>` | Set container root password |

Build with:

```bash
ank build -i my-site.ankfile
```

---

## Enterprise Tiers

ANK automatically detects the highest isolation tier supported by your device kernel.

| Tag | Tier | NETNS | PIDNS | Overlay | Network | Root |
|-----|------|:-----:|:-----:|:-------:|:-------:|:----:|
| X | **Isolated** | Yes | Yes | Yes | Isolated namespace | Yes |
| Y | **Shared Network** | No | Yes | Yes | Host | Yes |
| Z | **Shared Host** | No | No | Yes | Host | Yes |
| W | **Native Host** | No | No | No | Host | Yes |
| L | **Lite** | No | No | No | Host | No (PRoot) |

| Feature | Lite (L) | Shared Host (Z) | Shared Network (Y) | Isolated (X) |
|---------|:--------:|:---------------:|:-------------------:|:------------:|
| Chroot | PRoot | Yes | Yes | Yes |
| iptables NAT | No | Yes | Yes | Yes |
| Port Mapping | No | Yes | Yes | Yes |
| Network Isolation | No | No | No | Yes (NET_NS) |
| PID Isolation | No | No | Yes (PID_NS) | Yes (PID_NS) |
| OverlayFS | No | Yes | Yes | Yes |
| cgroups | No | Yes | Yes | Yes |
| No Root Required | Yes | No | No | No |

---

## Stacks & Orchestration

Manage groups of identical containers with load balancing and auto-scaling.

| Feature | Description |
|---------|-------------|
| Creation | Create stacks from templates or custom Ankfiles |
| Scale up/down | Add or remove containers manually |
| Auto-scaling | Automatic scaling by CPU, memory or requests/sec |
| Load Balancer | Python reverse proxy with `round_robin`, `least_connections` (alias `least_conn`) and `ip_hash` algorithms |
| Shared Volume | Bind mount from host to share data between containers |
| Ankfile | Deploy custom images via Ankfile within stacks |

Access from the web panel in the **Stacks** tab.

---

## Backups

Automate your data backups with scheduling and retention.

| Feature | Description |
|---------|-------------|
| Routines | Create routines with source, SSH destination and schedule |
| Execution | Run manually or via cron |
| Retention | Automatic cleanup policy for old backups |
| Browsing | Browse remote backup files from the web panel |
| sshpass+scp | Secure transfer via SSH without interaction |

Access from the web panel in the **Backups** tab.

---

## Multi-Device Management

Manage multiple ANK devices from a central panel.

| Feature | Description |
|---------|-------------|
| Connection | Connect via HTTP API (URL + remote panel credentials) |
| Heartbeat | Monitoring every 30s with online/offline status |
| Dashboard | Aggregated view of all nodes (CPU, RAM, disk, containers) |
| Containers | Create, start, stop and delete containers on remote nodes |
| Proxy | Transparent HTTP/WS communication between nodes |

Access from the web panel in the **Nodes** tab.

---

## API Reference

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Engine status + uptime + CPU |
| `GET` | `/api/config` | Get panel configuration |
| `POST` | `/api/config` | Update panel config |
| `GET` | `/api/system/info` | Device info |
| `POST` | `/api/system/shell` | Execute shell command |
| `GET` | `/api/system/dashboard` | Aggregated dashboard (all nodes) |
| `POST` | `/api/system/uninstall` | Uninstall ANK |
| `GET` | `/api/logs` | Server logs |
| `GET` | `/api/protocol` | Active protocol (HTTP/HTTPS) |

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Authenticate |
| `POST` | `/api/auth/password` | Change credentials |

### Containers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/containers` | List containers |
| `POST` | `/api/containers` | Create container |
| `GET` | `/api/containers/:id` | Inspect container |
| `GET` | `/api/containers/:id/logs` | Logs (tail 8KB) |
| `POST` | `/api/containers/:id/start` | Start |
| `POST` | `/api/containers/:id/stop` | Stop |
| `POST` | `/api/containers/:id/restart` | Restart |
| `POST` | `/api/containers/:id/update` | Update settings |
| `POST` | `/api/containers/:id/exec` | Execute command |
| `DELETE` | `/api/containers/:id` | Delete |

### Files

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/containers/:id/files` | List files |
| `GET` | `/api/containers/:id/files/content` | Read file content |
| `POST` | `/api/containers/:id/files/write` | Write file |
| `POST` | `/api/containers/:id/files/mkdir` | Create directory |
| `POST` | `/api/containers/:id/files/rename` | Rename file |
| `DELETE` | `/api/containers/:id/files` | Delete file |
| `PUT` | `/api/containers/:id/upload` | Upload files |

### Images

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/images` | List images |
| `GET` | `/api/images/templates` | List templates |
| `POST` | `/api/images/deploy` | Deploy template |
| `POST` | `/api/images/ankfile` | Build from Ankfile |
| `POST` | `/api/images/pull` | Download image |

### Network

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/networks` | Network config |
| `POST` | `/api/networks` | Configure network |

### Stacks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/stacks` | List stacks |
| `GET` | `/api/stacks/:id` | Inspect stack |
| `POST` | `/api/stacks` | Create stack |
| `POST` | `/api/stacks/:id/scale` | Scale stack up |
| `POST` | `/api/stacks/:id/scale-down` | Scale stack down |
| `POST` | `/api/stacks/:id/update` | Update stack |
| `POST` | `/api/stacks/:id/delete` | Delete stack |
| `GET` | `/api/stacks/:id/logs` | Stack logs |
| `GET` | `/api/stacks/:id/metrics` | Stack metrics |

### Backups

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/backups` | List backup routines |
| `GET` | `/api/backups/:id` | Inspect routine |
| `POST` | `/api/backups` | Create backup routine |
| `POST` | `/api/backups/:id/execute` | Execute backup |
| `POST` | `/api/backups/:id/delete` | Delete routine |
| `GET` | `/api/backups/:id/browse` | Browse remote files |

### Nodes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/nodes` | List nodes |
| `GET` | `/api/nodes/:id` | Inspect node |
| `POST` | `/api/nodes` | Add node |
| `POST` | `/api/nodes/:id/delete` | Remove node |
| `POST` | `/api/nodes/:id/refresh` | Refresh node data |
| `GET` | `/api/nodes/:id/containers` | Remote node containers |
| `GET` | `/api/nodes/:id/stacks` | Remote node stacks |

### WebSocket

| Protocol | Endpoint | Description |
|----------|----------|-------------|
| `WS` | `/ws/shell` | Host terminal |
| `WS` | `/ws/terminal/:name` | Container terminal |

### curl Examples

```bash
# List containers
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/containers

# Deploy a template
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"template":"nginx","name":"my-site"}' \
  http://localhost:8001/api/images/templates

# List files in a container
curl -H "Authorization: Bearer <token>" \
  http://localhost:8001/api/containers/my-site/files?path=/

# Download an image
curl -H "Authorization: Bearer <token>" -X POST \
  -H "Content-Type: application/json" \
  -d '{"image":"alpine-3.20"}' \
  http://localhost:8001/api/images/pull
```

---

## Configuration

The global configuration is stored at `/data/local/ank/config.json` on the device.

Key options:

| Field | Description | Default |
|-------|-------------|---------|
| `username` | Web panel username | `admin` |
| `password` | Web panel password | `admin123` |
| `panel_port` | Server port | `8001` |
| `network.subnet` | Container subnet | `10.20.30.0/24` |
| `network.gateway` | Container gateway | `10.20.30.1` |

Change settings via the web panel under **Settings**, or edit the file directly:

```bash
adb shell su -c "cat /data/local/ank/config.json"
```

---

## Troubleshooting

### Check kernel support

```bash
# Namespace support
adb shell su -c "zcat /proc/config.gz | grep NAMESPACES"

# OverlayFS support
adb shell su -c "zcat /proc/config.gz | grep OVERLAY"
```

### Check detected tier

```bash
adb shell cat /data/local/ank/mode
```

### View logs

```bash
# Server logs
adb shell cat /data/local/ank/logs/server.log

# Container logs
adb shell cat /data/local/ank/logs/<name>.log
```

### Rebuild ank-alpinebase

```bash
# Remove the base image to trigger a lazy rebuild
adb shell su -c "rm -rf /data/local/ank/images/ank-alpinebase"
```

### Verify Python in ankfs

```bash
adb shell su -c "mount -t proc proc /data/local/ank/ankfs/proc; \
  chroot /data/local/ank/ankfs /usr/bin/python3 -c 'import pty; print(\"OK\")'"
```

### Manual cleanup

```bash
adb shell su -c "sh /data/local/ank/scripts/cleanup.sh"
```

---

## Project Structure

```
ank/
├── magisk-module/
│   ├── module.prop               # Module metadata
│   ├── post-fs-data.sh           # Boot hook (bridge ank0, iptables)
│   ├── service.sh                # Boot service (starts server)
│   ├── install.sh                # Installer (two-path: tarball or build from scratch)
│   ├── ankfs/                    # Pre-built rootfs (Alpine + Python + openssh)
│   │   └── ankcore-armv7.tar.gz  # Rootfs tarball
│   ├── server/
│   │   ├── server.py             # Python3 HTTP server (stdlib, no Flask)
│   │   ├── stack_manager.py      # Stack management (CRUD, scale, auto-scale)
│   │   ├── ank_orchestrator.py   # Background auto-scaling loop
│   │   ├── ank_lb.py             # Python load balancer (reverse proxy + health check)
│   │   ├── node_manager.py       # Multi-node management (heartbeat, HTTP API)
│   │   ├── node_proxy.py         # HTTP/WS proxy for remote nodes
│   │   ├── backup_manager.py     # Backup routines (CRUD, history)
│   │   ├── backup_runner.py      # Backup executor (tar.gz + scp + retention)
│   │   └── static/
│   │       ├── index.html        # Web panel UI
│   │       ├── style.css         # Dark/light theme + responsive
│   │       ├── app.js            # Client-side JS (xterm.js, WebSocket, modals)
│   │       ├── ank-cli.py        # CLI scripts (bin/ank, bin/ank-core)
│   │       ├── ank-profile.sh    # WS shell profile
│   │       └── favicon.svg       # App icon
│   └── scripts/
│       ├── container.sh          # Container lifecycle + _ensure_ankbase
│       ├── network.sh            # Namespaces + iptables
│       ├── resources.sh          # Cgroups (memory/cpu)
│       ├── cleanup.sh            # Garbage collector
│       ├── detect.sh             # Kernel/mode detection
│       ├── download-rootfs.sh    # Download Alpine minirootfs
│       ├── executor.sh           # Command executor
│       ├── uninstall.sh          # Complete uninstaller
│       ├── ank-lite-bootstrap.sh # PRoot bootstrap (non-root)
│       ├── start-lite.sh         # Start Lite server
│       ├── ank-shell.sh          # Interactive host shell (TAB + history)
│       ├── restart-server.sh     # Server restart helper
│       └── wifi-watchdog.sh      # WiFi reconnect watchdog
├── installer/
│   ├── main.py                   # GUI installer entry point
│   ├── ANK-Installer.spec        # PyInstaller spec
│   ├── core/
│   │   ├── adb.py                # ADB wrapper
│   │   ├── detector.py           # Capability detection + tier
│   │   ├── installer_lite.py     # Non-root install via PRoot
│   │   └── installer_manual.py   # Manual Magisk install helpers
│   └── ui/
│       ├── app.py                # Main window + sidebar (PySide6/Qt6)
│       ├── theme.py              # Colors, fonts, layout
│       ├── step_connect.py       # Connect device
│       ├── step_detect.py        # Detect compatibility
│       ├── step_mode_select.py   # Choose install mode
│       ├── step_clone.py         # Clone/migrate
│       ├── step_confirm.py       # Confirm installation
│       ├── step_install.py       # Installing
│       ├── step_reboot.py        # Rebooting
│       └── step_done.py          # Done
├── LICENSE                       # AKSAL-1.0
├── README.md
└── build_zip.py                  # ank-magisk.zip builder
```

### Device Paths

```
/data/local/ank/
├── ankfs/                        # Server rootfs (Alpine + Python)
├── images/                       # Base images
│   ├── alpine-3.20/              # Clean Alpine minirootfs
│   └── ank-alpinebase/           # Container base (openssh + bash + python3)
├── containers/<name>/            # Per-container data
│   ├── config.json               # Config (status, port, IP, password)
│   ├── merged/                   # Container rootfs
│   ├── upper/                    # Overlay upper layer
│   └── work/                     # Overlay work layer
├── logs/                         # server.log, server.pid, <container>.log
├── stacks/                       # Stack data
│   └── <name>/
│       ├── data/                 # Shared volume (bind mount in containers)
│       └── config.json           # Stack config
├── backups/                      # Backup data
│   ├── routines/                 # Backup routines (JSON)
│   └── history/                  # Execution history
├── nodes/                        # Remote node configs
│   └── node-*.json               # Per-node config (ip, port, token)
├── cache/                        # alpine-minirootfs-<arch>.tar.gz
├── config.json                   # Global config (subnet, port, credentials)
├── mode                          # Detected tier (JSON)
├── protocol                      # HTTP or HTTPS
└── cert.pem / key.pem            # HTTPS certificate (auto-generated)
```

---

## Releases

| Version | Status | Download |
|---------|--------|----------|
| v2.0.0 | **Latest** | [ank-magisk.zip](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ank-magisk.zip) + [ANK-Installer.exe](https://github.com/andrebarretoit/ank/releases/download/v2.0.0/ANK-Installer.exe) |

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes
4. Push to your branch and open a Pull Request

For development setup, see `DEVELOPMENT.md` (if available).

---

## License

[![License: AKSAL-1.0](https://img.shields.io/badge/License-AKSAL--1.0-FF6B35.svg)](LICENSE)

**Android Konteiner Source Available License 1.0** — free to use for any purpose. Selling or distributing the software is not permitted. See [LICENSE](LICENSE) for details.

---

## Credits

**Created by [Andre Barreto](https://github.com/andrebarretoit)**

[GitHub](https://github.com/andrebarretoit) · [LinkedIn](https://linkedin.com/in/andrebarretoit) · [andrebarreto.work](https://andrebarreto.work)

---

**ANK** — Containers on Android. No PC needed.
