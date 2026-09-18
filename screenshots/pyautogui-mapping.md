# ANK Browser Automation Mapping

## Resolution: 1920x1080, Browser: Brave (maximized)

## Login Page Coordinates
- **USERNAME field**: x=1300, y=192 (but Selenium JS is more reliable)
- **Sign In button**: x=1300, y=237
- **Password field**: appears after entering username + clicking Sign In
- **Footer**: "ANK · Android Konteiner v2.0.0 · Powered by ANDREBARRETOIT"

## Navigation Approach
The SPA uses `navigateTo(page)` JS function. PyAutoGUI clicks on nav icons DON'T work (Brave blocks synthetic events). **Use Selenium** for all automation:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.binary_location = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
options.add_argument("--no-sandbox")
options.add_argument("--window-size=1920,1080")
driver = webdriver.Chrome(options=options)

# Login
import requests
resp = requests.post("http://10.171.0.205:8001/api/auth/login",
    json={"username": "admin", "password": "admin123"},
    headers={"Content-Type": "application/json", "X-ANK-Client": "ank-panel"})
token = resp.json()["token"]

driver.get("http://10.171.0.205:8001")
driver.execute_script(f"localStorage.setItem('ank_token', '{token}')")
driver.execute_script("location.reload()")

# Navigate pages
driver.execute_script("navigateTo('containers')")
driver.save_screenshot("containers.png")
```

## Page Routes
| Page | navigateTo() | Description |
|------|-------------|-------------|
| Dashboard | `dashboard` | Device info, resources, container overview |
| Containers | `containers` | Container list + detail panel |
| Images | `images` | Quick Deploy / Ankfile Build / Ank Images |
| Nodes | `nodes` | Multi-device cluster management |
| Stacks | `stacks` | Multi-container stack management |
| Backups | `backups` | Backup routines with 3-step wizard |
| Networks | `networks` | Network management (ank0 = shared_host) |
| Shell | `shell` | Web terminal (xterm.js, connects to ankd) |
| Logs | `logs` | Live server logs with filters |
| Settings | `settings` | Account, Server, ANK Manager, Remote & SSH, Cache, About |

## Settings Sub-sections
- `showSettingsSection('account')` — Password change form
- `showSettingsSection('server')` — Server config
- `showSettingsSection('ank-manager')` — ANK Manager panel (Start/Stop/Restart)
- `showSettingsSection('remote')` — Remote & SSH config
- `showSettingsSection('cache')` — Cache management
- `showSettingsSection('about')` — About page

## Screenshots Directory
All screenshots saved to: `E:/Ank/screenshots/mapping/`
- `login.png` — Login page (two-step: username → password)
- `dashboard.png` — Dashboard with device info, resources, containers
- `containers.png` — Container list + "Select a container to manage"
- `images.png` — Images page (Quick Deploy, Ankfile Build, Ank Images)
- `nodes.png` — Nodes page ("No nodes" empty state)
- `stacks.png` — Stacks page ("No stacks" empty state)
- `backups.png` — Backups page with "Create Routine" CTA
- `networks.png` — Networks page (ank0 shared_host)
- `shell.png` — Working terminal shell (root@ank-shell)
- `logs.png` — Live server logs with filter controls
- `settings.png` — Settings page (Account section)
