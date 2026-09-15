# ANK Web Panel - Complete UI/UX Redesign

You are redesigning the **entire frontend** of ANK (Android Konteiner) — a Docker-like container management panel for Android devices.

## Files provided
- `index.html` — current HTML structure
- `style.css` — current CSS (you will REPLACE entirely)
- `app.js` — current JavaScript (you will REWRITE the UI layer, but KEEP all API calls identical)

## CRITICAL CONSTRAINTS

### 1. API Endpoints — DO NOT CHANGE
Every `fetch()` or `api()` call must remain exactly as-is. The backend expects these exact paths:

**Auth & Config:**
- `POST /api/auth/login` — body: `{ password }` — returns `{ token }`
- `GET /api/config`
- `POST /api/config` — body: `{ bind_address, refresh_interval, autostart_on_boot, node_name, default_container_password }` or `{ enable_remote_management, manager_ip, ssh_enabled, ssh_port }`
- `POST /api/auth/password` — body: `{ current_password, new_password }`
- `GET /api/protocol` — header: `X-ANK-Client: ank-panel`, `Authorization: Bearer <token>` — returns `{ protocol }`

**System:**
- `GET /api/system/info` — returns `{ device, cpu, ram, disk, kernel, uptime }`
- `GET /api/system/dashboard` — returns `{ containers, running, stopped, total, images, cpu, ram, disk, nodes, ... }`
- `POST /api/system/restart-server`
- `POST /api/system/restart-device`
- `POST /api/system/uninstall`
- `GET /api/health`

**Containers:**
- `GET /api/containers` — list local containers
- `GET /api/containers/all` — list ALL containers (local + remote)
- `GET /api/containers/:name` — inspect container
- `POST /api/containers` — create container (body varies by template)
- `POST /api/containers/:name/start`
- `POST /api/containers/:name/stop`
- `POST /api/containers/:name/restart`
- `DELETE /api/containers/:name`
- `POST /api/containers/:name/update` — body: `{ root_password, cpu_shares, memory_limit, ... }`
- `GET /api/containers/:name/logs`
- `POST /api/containers/:name/exec` (via WebSocket)
- `PUT /api/containers/:name/upload` — multipart FormData

**Images:**
- `GET /api/images`
- `GET /api/images/all`
- `GET /api/images/templates`
- `POST /api/images/pull` — body: `{ version }`
- `POST /api/images/deploy` — body: `{ template, name, root_password }`
- `DELETE /api/images/:name`

**Nodes (remote devices):**
- `GET /api/nodes` — list all nodes
- `GET /api/nodes/manager` — get manager info
- `POST /api/nodes/pairing/send` — body: `{ alias }` — initiate pairing
- `GET /api/nodes/pairing` — list pairing requests
- `POST /api/nodes/pairing/:id/approve`
- `POST /api/nodes/pairing/:id/reject`
- `GET /api/nodes/:id/status` — node live status
- `GET /api/nodes/:id/system/info` — node system info
- `GET /api/nodes/:id/containers` — node containers
- `POST /api/nodes/:id/containers` — create container on node
- `POST /api/nodes/:id/containers/:name/start|stop|restart`
- `DELETE /api/nodes/:id/containers/:name`
- `GET /api/nodes/:id/containers/:name` — inspect remote container
- `GET /api/nodes/:id/containers/:name/logs`
- `POST /api/nodes/:id/containers/:name/exec` (via WebSocket)
- `GET /api/nodes/:id/images`
- `POST /api/nodes/:id/images/transfer` — body: `{ image }`
- `GET /api/nodes/:id/stacks`
- `GET /api/nodes/:id/logs` — node system logs
- `POST /api/nodes/:id/restart` — restart remote device
- `POST /api/nodes/:id/delete` — remove node
- `POST /api/nodes/:id/refresh` — refresh node info

**Stacks:**
- `GET /api/stacks`
- `GET /api/stacks/all`
- `GET /api/stacks/:id`
- `POST /api/stacks` — body: `{ name, services: [...] }`
- `POST /api/stacks/:id/scale` — body: `{ service, replicas }`
- `DELETE /api/stacks/:id`

**Networks:**
- `GET /api/networks`
- `GET /api/networks/info`
- `POST /api/networks` — body: `{ subnet, gateway, bridge, nat }`

**Backups:**
- `GET /api/backups`
- `POST /api/backups` — body: `{ container, type }`
- `POST /api/backups/:id/restore`
- `DELETE /api/backups/:id`

### 2. WebSocket
- Terminal shell uses WebSocket: `ws[s]://host/api/exec?container=<name>&token=<jwt>&cols=<n>&rows=<n>`
- Protocol detected via `GET /api/protocol`

### 3. Authentication
- Login: `POST /api/auth/login` with `{ password }` → returns `{ token }`
- Token stored in `localStorage` as `ank_token`
- All API calls include `Authorization: Bearer <token>` header
- If 401 → show login screen

## WHAT YOU CAN CHANGE

### HTML (index.html)
- **REWRITE entirely** — new structure, new layout, new components
- Keep all the tab sections: Dashboard, Containers, Images, Stacks, Backups, Networks, Nodes, Settings, Logs, Shell
- Keep the login screen
- Keep the container detail modal structure (but redesign visually)
- Keep the node detail modal (but redesign visually)
- **ADD:** Version badge "v2.0" in header or sidebar
- **ADD:** Compatibility badge "Android 7+" in header or sidebar
- **ADD:** Footer with "Powered by andrebarretoit" linking to https://linkedin.com/in/andrebarretoit
- **REMOVE:** Theme toggle button (dark/light) — dark only

### CSS (style.css)
- **REWRITE entirely** — new design system
- Dark-only theme (no light mode, no theme toggle)
- Professional, imposing, premium feel
- Modern animations (fade-in, scale, hover effects)
- Responsive (mobile-first, bottom-sheet modals on mobile)
- Well-organized sidebar with active indicator

### JavaScript (app.js)
- **KEEP:** All `api()` calls, `fetch()` calls, WebSocket logic exactly as-is
- **KEEP:** All data loading functions (loadContainers, loadImages, loadNodes, etc.)
- **KEEP:** All CRUD operations (create, start, stop, restart, delete containers)
- **KEEP:** All modal logic (showContainerDetail, showNodeDetail, customModal)
- **KEEP:** Toast notification system
- **KEEP:** Tab switching logic
- **KEEP:** Authentication flow
- **REWRITE:** Visual rendering functions (renderDashboard, renderContainerList, etc.) to use new HTML structure
- **ADD:** Smooth page transitions (fade-in on tab switch)
- **ADD:** Node health pulse animation
- **ADD:** Skeleton loading states

## DESIGN REQUIREMENTS

### Visual Identity
- **Color palette:** Deep dark backgrounds (#0a0e17, #111827, #1f2937), accent gradient blue→violet (#3b82f6→#8b5cf6)
- **Typography:** System font stack, clear hierarchy with letter-spacing
- **Cards:** Subtle borders, layered shadows, hover-lift effect
- **Buttons:** Glow on hover, press effect, loading spinner
- **Inputs:** Focus glow, smooth transitions
- **Badges:** Rounded, color-coded (green=running, red=stopped, yellow=building)
- **Tables:** Clean rows, hover highlight, sortable headers
- **Modals:** Scale+fade animation, backdrop blur, close on escape
- **Toasts:** Slide-in from right, progress bar, color-coded

### Sidebar
- Fixed left sidebar, collapsible on mobile (hamburger menu)
- Active item: left accent bar + subtle glow
- Logo with gradient text
- Badges for container counts
- Clean section dividers

### Dashboard
- Top stats cards: Running, Stopped, Total containers
- ANK Cluster card: nodes count, total CPU, total RAM, total disk
- Node cards: live status with pulse indicator, CPU/RAM bars
- Container list: compact rows with status badge, node tag, actions

### Mobile
- Sidebar becomes drawer (slide-in from left)
- Modals become bottom-sheets
- Touch targets ≥44px
- Grid reorganizes to single column

## OUTPUT

Return THREE files:
1. `index.html` — complete rewrite
2. `style.css` — complete rewrite  
3. `app.js` — keep API layer, rewrite UI rendering

Do NOT add comments explaining what you did. Just write clean, production-ready code.
