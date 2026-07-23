# ANK - Android Konteiner

Ultra-light container engine for Android. Zero compilation. Shell scripts + Python HTTP server.

## Requirements

- Android device with **Magisk** (root)
- Magisk v20.4+

## Install

### Option 1: Windows Installer (recommended)

1. Download `ANK-Installer.exe` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Connect your device via USB with ADB debugging enabled
3. Run `ANK-Installer.exe` and follow the steps

### Option 2: Magisk Module

1. Download `ank-magisk.zip` from [Releases](https://github.com/andrebarretoit/ank/releases)
2. Open Magisk app > Install > Select `ank-magisk.zip`
3. Reboot device

## Access

After install, open browser:

- **URL:** `https://localhost:8001`
- **Username:** `admin`
- **Password:** `admin123`

## Features

- Web panel with container management (create, start, stop, delete)
- Image templates: Alpine, Nginx, Apache, Python, Node.js, PHP
- Container templates with pre-configured packages
- File explorer with upload/download
- Real-time container logs
- xterm.js interactive terminal
- WebSocket shell
- SSH container access
- Network management
- CLI commands
- Lite mode (non-root PRoot)
- HTTPS with auto-generated self-signed certificate

## Architecture

- **Shell scripts** - container lifecycle (create, start, stop, delete)
- **Python HTTP server** - web panel API + static files
- **Magisk module** - rootfs extraction + boot scripts
- **Web panel** - HTML/CSS/JS with xterm.js

## Default Credentials

```
Username: admin
Password: admin123
```

## License

MIT
