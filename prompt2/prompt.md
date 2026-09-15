# ANK Container Platform — Unified Multi-Node System

## Context

ANK (Android Konteiner) is a container platform for rooted Android devices. It manages Linux containers (Alpine) via:
- **server.py** — Python HTTP API server (port 8001), orchestrates everything
- **container.sh** — Bash script for container lifecycle (create, start, stop, delete)
- **ankd.sh** — Service manager daemon running inside each container as PID 1

The system supports multi-node management: 1 Manager + N Child Nodes. All nodes run the same ANK stack. The goal is to make the entire cluster behave as **one unified system** — the user shouldn't care which node a container lives on.

## The Goal

Transform ANK from single-node to fully unified multi-node:

1. **Containers tab** — Shows ALL containers from ALL nodes in a single list, with node identification. Create containers on any node from this same UI.
2. **Images tab** — Shows images from ALL nodes. Pull images on any node. Transfer images between nodes.
3. **Stacks tab** — Shows stacks from ALL nodes. Manage stacks on any node.
4. **Shell** — Shell node selector switches between nodes. CLI support: `ank node <name>` jumps to that node's shell.
5. **Dashboard** — Aggregated stats from all nodes (CPU, RAM, disk, uptime, container counts).

## Current State

### What EXISTS and WORKS (backend)
- Node CRUD (add/remove/list/inspect) — `node_manager.py`
- Pairing system (send/receive/approve/reject) — `node_manager.py`
- Heartbeat monitoring (online/offline detection) — `node_manager.py`
- Remote container list/start/stop/restart/delete/create — `node_manager.py`
- Remote image list/transfer/pull — `node_manager.py`
- Remote status/system info — `node_manager.py`
- HTTP proxy for generic remote calls — `node_proxy.py`
- All API endpoints wired in `server.py`

### What EXISTS and WORKS (frontend)
- Nodes tab with node list, status dots, role tags
- Node detail modal (device info, containers, images)
- Remote container actions (start/stop/restart/delete)
- Node selector dropdowns for containers/images/shell
- Pairing request management (approve/reject)
- Image transfer between nodes

### What's BROKEN
1. **`api_refresh_node`** (server.py:4650) — just re-reads cached config, doesn't actually poll remote
2. **Dashboard node data** (server.py:4858-4867) — queries fields (`hostname`, `cpu`, `ram`) that don't exist in node config, always shows dashes
3. **Frontend node list** (app.js:2059-2060) — shows `n.cpu`, `n.ram`, `n.disk`, `n.stacks` which are never populated
4. **`_node_api_post`/`_node_api_delete`** (node_manager.py:696-728) — silently swallow non-200 error responses

### What's MISSING
1. **Unified containers view** — containers tab only shows local; needs to aggregate from all nodes
2. **Unified images view** — images tab only shows local; needs to aggregate from all nodes
3. **Unified stacks view** — stacks tab only shows local; needs to aggregate from all nodes
4. **Remote shell** — `onShellNodeChange()` is a stub (shows toast only); needs WebSocket proxy or relay
5. **`api_system_dashboard`** — node data mapping is wrong; needs to use actual remote status data
6. **Create container on remote** — needs to work from unified UI (currently only works from node detail modal)
7. **Real-time node stats** on node list cards — CPU, RAM, disk, uptime from heartbeat/refresh

## Architecture Requirements

### Backend (server.py)
The manager needs to:
1. **Aggregate container lists** from all online nodes on each poll
2. **Route actions** (start/stop/delete/create) to the correct node
3. **Aggregate image lists** from all online nodes
4. **Aggregate stack lists** from all online nodes
5. **Fetch real system info** from each node for dashboard
6. **Maintain node health** via heartbeat (already works)

### Frontend (app.js + index.html)
1. **Containers tab** — Render ALL containers from all nodes with node tag/badge
2. **Images tab** — Render ALL images from all nodes with node tag
3. **Stacks tab** — Render ALL stacks from all nodes with node tag
4. **Create container modal** — Add node selector to pick which node to create on
5. **Node selector** — When "all" is selected, show unified view; when specific node is selected, show only that node's containers/images/stacks
6. **Shell node selector** — Actually switch shell session to remote node
7. **Dashboard** — Show aggregated stats from all nodes

### Data Flow
```
Manager polls GET /containers
  → For each online node: GET /nodes/{id}/containers
  → Merge results, add node field to each container
  → Return unified list

Manager sends POST /containers (create)
  → If target is remote: POST /nodes/{id}/containers with same payload
  → If target is local: regular create
```

## Constraints

- Android host environment (SELinux, limited /proc access)
- Containers run Alpine Linux (BusyBox ash shell)
- No systemd/systemctl
- Max 3-4 nodes expected (performance not critical)
- Direct HTTP between nodes (no message queue)
- Keep existing single-node functionality working
- Do NOT break existing API contracts (add new endpoints, don't change existing ones)
- BusyBox ash compatible shell scripts

## Files to Modify

### Backend
- `server/server.py` — Add unified aggregation endpoints, fix dashboard mapping, fix error handling
- `server/node_manager.py` — Fix error handling in `_node_api_post`/`_node_api_delete`, fix `api_refresh_node`
- `server/node_proxy.py` — Deduplicate code with node_manager.py

### Frontend
- `server/static/app.js` — Unified container/image/stack rendering, create container with node selector, shell node switching
- `server/static/index.html` — Update containers/images/stacks tab structure for unified view

### NOT modifying
- `server/container.sh` — No changes needed for multi-node
- `server/ankd/ankd.sh` — No changes needed for multi-node

## UI Design

### Containers Tab
```
[Node Selector: All | local | node-1 | node-2 | node-3]
[+ Create Container]

Container List:
| Name       | Node    | Status  | Image        | Ports    | Actions    |
|------------|---------|---------|--------------|----------|------------|
| php-8.2    | local   | running | php-8.2      | 2204     | [▶][⏹][🗑] |
| nginx-web  | node-1  | running | nginx        | 2201     | [▶][⏹][🗑] |
| python-api | node-2  | stopped | python-3.12  | 2203     | [▶][⏹][🗑] |
```

### Images Tab
```
[Node Selector: All | local | node-1 | node-2 | node-3]

| Image             | Node   | Size    | Actions              |
|-------------------|--------|---------|----------------------|
| alpine-3.20       | local  | 44 MB   | [Deploy] [Send→]     |
| nginx             | local  | 44 MB   | [Deploy] [Send→]     |
| alpine-3.20       | node-1 | 44 MB   | [Deploy]             |
| php-8.2           | node-2 | 44 MB   | [Deploy] [Pull]      |
```

### Create Container Modal
```
[Node: local ▼]  ← dropdown to pick target node
[Name: my-app]
[Image: alpine-3.20 ▼]
[Root Password: ****]
[✓ Create]
```

### Shell Tab
```
[Node Selector: local | node-1 | node-2 | node-3]
[Terminal area — connects to selected node's shell]
```

### Dashboard
```
Nodes: 4 online | Containers: 12 running, 3 stopped
CPU: 45% avg | RAM: 2.1 GB / 8 GB | Disk: 32 GB / 128 GB

Node Cards:
| Node    | Status | CPU  | RAM      | Disk     | Containers |
|---------|--------|------|----------|----------|------------|
| local   | 🟢     | 32%  | 1.2/4 GB | 20/64 GB | 5          |
| node-1  | 🟢     | 45%  | 0.8/2 GB | 8/32 GB  | 3          |
| node-2  | 🟢     | 28%  | 0.3/1 GB | 4/16 GB  | 4          |
| node-3  | 🔴     | -    | -        | -        | -          |
```
