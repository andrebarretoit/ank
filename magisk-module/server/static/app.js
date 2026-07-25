/**
 * ANK - Android Konteiner
 * Web Panel - No alerts, custom modals & toasts
 */
const API = '/api';

async function btnLoading(btn, fn) {
    if (!btn) return fn();
    const orig = btn.innerHTML;
    const origDisabled = btn.disabled;
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> ' + orig.replace(/<[^>]+>/g, '').trim();
    try { return await fn(); } finally { btn.disabled = origDisabled; btn.innerHTML = orig; }
}
let ankToken = localStorage.getItem('ank_token') || '';
let isLoggedIn = !!ankToken;

async function api(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' };
    if (ankToken) headers['Authorization'] = 'Bearer ' + ankToken;
    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API}${path}`, opts);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) { logout(); throw new Error('Unauthorized'); }
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

function toast(msg, type = 'info') {
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    const icons = { success: 'bi-check-circle-fill', error: 'bi-exclamation-circle-fill', info: 'bi-info-circle-fill', warning: 'bi-exclamation-triangle-fill' };
    el.className = `toast toast-${type}`;
    el.innerHTML = `<i class="bi ${icons[type] || icons.info}"></i> ${msg}`;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(100%)'; setTimeout(() => el.remove(), 300); }, 4000);
}

function confirmAction(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        document.getElementById('confirm-title').textContent = title;
        document.getElementById('confirm-message').textContent = message;
        modal.classList.remove('hidden');
        const okBtn = document.getElementById('confirm-ok');
        const cancelBtn = document.getElementById('confirm-cancel');
        const closeBtns = modal.querySelectorAll('.modal-close');
        function cleanup() {
            modal.classList.add('hidden');
            okBtn.replaceWith(okBtn.cloneNode(true));
            cancelBtn.replaceWith(cancelBtn.cloneNode(true));
            closeBtns.forEach(b => b.replaceWith(b.cloneNode(true)));
        }
        document.getElementById('confirm-ok').addEventListener('click', () => { cleanup(); resolve(true); });
        document.getElementById('confirm-cancel').addEventListener('click', () => { cleanup(); resolve(false); });
        modal.querySelectorAll('.modal-close').forEach(b => b.addEventListener('click', () => { cleanup(); resolve(false); }));
        modal.querySelector('.modal-overlay').addEventListener('click', () => { cleanup(); resolve(false); });
    });
}

function inputModal(title, message, defaultValue = '') {
    return new Promise((resolve) => {
        const modal = document.getElementById('input-modal');
        document.getElementById('input-title').textContent = title;
        document.getElementById('input-message').textContent = message;
        const field = document.getElementById('input-field');
        field.value = defaultValue;
        modal.classList.remove('hidden');
        setTimeout(() => field.focus(), 50);
        const okBtn = document.getElementById('input-ok');
        const cancelBtn = document.getElementById('input-cancel');
        const closeBtns = modal.querySelectorAll('.modal-close');
        function cleanup() {
            modal.classList.add('hidden');
            okBtn.replaceWith(okBtn.cloneNode(true));
            cancelBtn.replaceWith(cancelBtn.cloneNode(true));
            closeBtns.forEach(b => b.replaceWith(b.cloneNode(true)));
            field.replaceWith(field.cloneNode(true));
        }
        function submit() {
            const val = field.value.trim();
            cleanup();
            resolve(val || null);
        }
        document.getElementById('input-ok').addEventListener('click', submit);
        document.getElementById('input-cancel').addEventListener('click', () => { cleanup(); resolve(null); });
        document.getElementById('input-field').addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
        modal.querySelectorAll('.modal-close').forEach(b => b.addEventListener('click', () => { cleanup(); resolve(null); }));
        modal.querySelector('.modal-overlay').addEventListener('click', () => { cleanup(); resolve(null); });
    });
}

function customModal(title, fields) {
    return new Promise((resolve) => {
        const modal = document.getElementById('input-modal');
        document.getElementById('input-title').textContent = title;
        document.getElementById('input-message').textContent = '';
        const container = document.getElementById('input-field').parentElement;
        const origField = document.getElementById('input-field');
        origField.style.display = 'none';
        const customFields = fields.map(f => {
            const input = document.createElement('input');
            input.type = f.type || 'text';
            input.id = f.id;
            input.value = f.value || '';
            input.placeholder = f.label;
            input.style.cssText = 'width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);margin-bottom:8px;font-size:14px;';
            input.className = 'custom-modal-field';
            container.appendChild(input);
            return input;
        });
        modal.classList.remove('hidden');
        setTimeout(() => customFields[0].focus(), 50);
        const okBtn = document.getElementById('input-ok');
        const cancelBtn = document.getElementById('input-cancel');
        const closeBtns = modal.querySelectorAll('.modal-close');
        function cleanup() {
            modal.classList.add('hidden');
            origField.style.display = '';
            customFields.forEach(el => el.remove());
            okBtn.replaceWith(okBtn.cloneNode(true));
            cancelBtn.replaceWith(cancelBtn.cloneNode(true));
            closeBtns.forEach(b => b.replaceWith(b.cloneNode(true)));
        }
        function submit() {
            const result = {};
            let allFilled = true;
            fields.forEach((f, i) => {
                result[f.id] = customFields[i].value.trim();
                if (!result[f.id]) allFilled = false;
            });
            cleanup();
            resolve(allFilled ? result : null);
        }
        document.getElementById('input-ok').addEventListener('click', submit);
        document.getElementById('input-cancel').addEventListener('click', () => { cleanup(); resolve(null); });
        document.getElementById('input-field').addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
        customFields[customFields.length - 1].addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
        modal.querySelectorAll('.modal-close').forEach(b => b.addEventListener('click', () => { cleanup(); resolve(null); }));
        modal.querySelector('.modal-overlay').addEventListener('click', () => { cleanup(); resolve(null); });
    });
}

function logout() {
    ankToken = '';
    localStorage.removeItem('ank_token');
    isLoggedIn = false;
    showScreen('login-screen');
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const user = document.getElementById('username-input').value;
    const pass = document.getElementById('password-input').value;
    const err = document.getElementById('login-error');
    err.textContent = '';
    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
            body: JSON.stringify({ username: user, password: pass })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Login failed');
        ankToken = data.token;
        localStorage.setItem('ank_token', ankToken);
        isLoggedIn = true;
        showScreen('app-screen');
        loadAll();
        if (data.force_change) toast('Altere sua senha padrao nas Configuracoes.', 'info');
    } catch (e) {
        err.textContent = e.message || 'Invalid username or password';
    }
});

document.getElementById('logout-btn').addEventListener('click', logout);

document.getElementById('sidebar-expand').addEventListener('click', () => {
    const sidebar = document.querySelector('.sidebar');
    sidebar.classList.toggle('expanded');
    const icon = document.querySelector('#sidebar-expand i');
    icon.className = sidebar.classList.contains('expanded') ? 'bi bi-chevron-double-left' : 'bi bi-chevron-double-right';
});

/* Mobile off-canvas drawer */
function openDrawer() {
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-backdrop').classList.add('open');
}
function closeDrawer() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-backdrop').classList.remove('open');
}
document.getElementById('drawer-open-btn')?.addEventListener('click', openDrawer);
document.getElementById('sidebar-backdrop')?.addEventListener('click', closeDrawer);

window.addEventListener('resize', () => {
    const sidebar = document.querySelector('.sidebar');
    if (window.innerWidth > 1100) {
        sidebar.classList.remove('expanded');
        sidebar.style.width = '';
    }
    if (window.innerWidth > 640) closeDrawer();
});

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        item.classList.add('active');
        document.getElementById(`tab-${item.dataset.tab}`).classList.add('active');
        if (item.dataset.tab === 'networks') loadNetworks();
        if (item.dataset.tab === 'logs') { logsOffset = 0; loadLogs(false); startLogsPoll(); }
        if (item.dataset.tab === 'shell') initCoreTerminal();
        if (item.dataset.tab !== 'logs') stopLogsPoll();
        if (window.innerWidth <= 640) closeDrawer();
    });
});

function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    document.getElementById(id).classList.remove('hidden');
}
function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
function hideModal(id) { document.getElementById(id).classList.add('hidden'); }

function fmtBytes(b) {
    if (!b || b === 0) return '0 B';
    const k = 1024, s = ['B','KB','MB','GB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return (b / Math.pow(k, i)).toFixed(1) + ' ' + s[i];
}
function fmtUptime(sec) {
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}
function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(() => copyTextFallback(text));
    } else {
        copyTextFallback(text);
    }
}
function copyTextFallback(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
}

async function loadAll() {
    try {
        const [containers, images, status, info] = await Promise.all([
            api('GET', '/containers'),
            api('GET', '/images'),
            api('GET', '/status'),
            api('GET', '/system/info')
        ]);
        document.getElementById('version').textContent = `v${status.version}`;
        const mode = info.mode?.mode || 'shared_host';
        const badge = document.getElementById('mode-badge');
        badge.textContent = mode;
        badge.className = 'mode-badge mode-' + mode;
        const notice = document.getElementById('mode-notice');
        const noticeTitle = document.getElementById('mode-notice-title');
        const noticeBody = document.getElementById('mode-notice-body');
        const i18n = {
            shared_hostTitle: 'Shared Host Mode Active',
            shared_hostBody: 'No namespace isolation. Containers share host network and PID.',
            shared_networkTitle: 'Shared Network Mode Active',
            shared_networkBody: 'PID namespace + overlay active. Host networking.',
            isolatedTitle: 'Isolated Mode Active',
            isolatedBody: 'Full isolation with network namespace, PID and overlay.'
        };
        if (mode === 'shared_host' || mode === 'native_host') {
            notice.classList.remove('hidden');
            notice.className = 'compat-warning';
            noticeTitle.textContent = i18n.shared_hostTitle;
            noticeBody.textContent = i18n.shared_hostBody;
        } else if (mode === 'shared_network') {
            notice.classList.remove('hidden');
            notice.className = 'compat-warning mode-enhanced-notice';
            noticeTitle.textContent = i18n.shared_networkTitle;
            noticeBody.textContent = i18n.shared_networkBody;
        } else {
            notice.classList.add('hidden');
        }
        document.getElementById('stat-running').textContent = status.containers_running;
        document.getElementById('stat-stopped').textContent = status.containers_stopped || 0;
        document.getElementById('stat-total').textContent = status.containers_total;
        document.getElementById('stat-images').textContent = images.length;
        document.getElementById('stat-uptime').textContent = fmtUptime(status.uptime || 0);
        document.getElementById('stat-cpu').textContent = (info.cpu_usage != null ? info.cpu_usage + '%' : '-');
        document.getElementById('stat-cpu-cores').textContent = (info.cpu_cores || 0) > 0 ? info.cpu_cores + ' cores — ' : '';
        document.getElementById('info-device').textContent = info.device || '-';
        document.getElementById('info-kernel').textContent = info.kernel || '-';
        const memT = info.memory?.total_kb || 0;
        const memA = info.memory?.available_kb || 0;
        if (memT > 0 && memA > 0) {
            const used = memT - memA;
            const pct = Math.round(used / memT * 100);
            document.getElementById('stat-memory').textContent = `${fmtBytes(used * 1024)} / ${fmtBytes(memT * 1024)} (${pct}%)`;
        } else if (memT > 0) {
            document.getElementById('stat-memory').textContent = fmtBytes(memT * 1024);
        } else {
            document.getElementById('stat-memory').textContent = '-';
        }
        document.getElementById('info-subnet').textContent = (info.network?.subnet || '-') + '/24';
        const bat = info.battery;
        document.getElementById('info-battery').textContent = (bat != null && bat >= 0) ? bat + '%' : '-';
        const disk = status.disk;
        if (disk && disk.total > 0) {
            document.getElementById('stat-disk').textContent = `${disk.used} / ${disk.total} GB`;
        } else {
            document.getElementById('stat-disk').textContent = '-';
        }
        renderContainers(containers);
        renderImages(images);
        populateImageSelect(images);
        renderDashboardContainers(containers);
        loadTemplates();
    } catch (e) { console.error('Load failed:', e); }
}

function renderContainers(containers) {
    const list = document.getElementById('containers-list');
    if (containers.length === 0) {
        list.innerHTML = `<div class="empty-state"><i class="bi bi-box-seam"></i><p>No containers yet. Click "New Container".</p></div>`;
        return;
    }
    list.innerHTML = containers.map(c => {
        const isBuilding = c.status === 'building';
        const isFailed = c.status === 'failed';
        const statusClass = isBuilding ? 'status-building' : isFailed ? 'status-failed' : `status-${c.status}`;
        const statusText = isBuilding ? 'Building...' : isFailed ? 'Failed' : c.status === 'starting' ? 'Starting...' : c.status === 'stopping' ? 'Stopping...' : c.status;
        const disabled = isBuilding || isFailed || c.status === 'starting' || c.status === 'stopping';
        return `
        <div class="container-card ${isBuilding ? 'building' : ''}" data-name="${c.name}" style="${isBuilding ? 'opacity:0.7' : ''}">
            <div class="container-info">
                <span class="container-name"><i class="bi bi-box-seam" style="margin-right:6px;color:var(--accent)"></i>${c.name}</span>
                <div class="container-meta">
                    <span><i class="bi bi-image"></i> ${c.template_name || c.image || '-'}</span>
                    <span><i class="bi bi-globe2"></i> ${c.ip_address || 'N/A'}</span>
                    ${c.stats && c.stats.memory_bytes ? `<span><i class="bi bi-memory"></i> ${fmtBytes(c.stats.memory_bytes)}</span>` : ''}
                </div>
            </div>
            <div class="container-actions">
                <span class="status-badge ${statusClass}">${isBuilding ? '<i class="bi bi-arrow-repeat spin"></i> ' : ''}${statusText}</span>
                ${c.status === 'running' || c.status === 'starting'
                    ? `<button class="btn btn-warning btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); stopContainer('${c.name}')"><i class="bi bi-stop-fill"></i></button>`
                    : `<button class="btn btn-success btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); startContainer('${c.name}')"><i class="bi bi-play-fill"></i></button>`
                }
            </div>
        </div>`;
    }).join('');
    list.querySelectorAll('.container-card').forEach(card => {
        card.addEventListener('click', () => showContainerDetail(card.dataset.name));
    });
}

function renderImages(images) {
    const el = document.getElementById('images-list');
    if (!images || images.length === 0) {
        el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-stack"></i><p>No images available</p></div>';
        return;
    }
    el.innerHTML = images.map(img => `
        <div class="image-card">
            <div class="image-icon"><i class="bi bi-hdd-stack"></i></div>
            <div class="image-info">
                <span class="image-name">${esc(img.name)}</span>
                <span class="image-size">${img.size_human || fmtBytes(img.size || 0)}</span>
            </div>
        </div>
    `).join('');
}

function populateImageSelect(images) {
    const sel = document.getElementById('container-image');
    const baseOptions = images.map(i => `<option value="${i.name}">${i.name}${i.complete ? ' (complete)' : ''}</option>`).join('');
    const templateOptions = `
        <optgroup label="--- Templates ---">
            <option value="template:python">Python 3.12 (Alpine + Python)</option>
            <option value="template:nginx">Nginx Static (Web server :8080)</option>
            <option value="template:apache">Apache Static (Web server :8080)</option>
            <option value="template:php">PHP 8.2 (Alpine + PHP :8080)</option>
            <option value="template:node">Node.js 20 (Alpine + Node :3000)</option>
        </optgroup>
    `;
    sel.innerHTML = baseOptions + templateOptions;
}

function renderDashboardContainers(containers) {
    const el = document.getElementById('dashboard-containers');
    if (!el) return;
    if (!containers || containers.length === 0) {
        el.innerHTML = '<div class="empty-state"><p style="font-size:13px;color:var(--text-muted)">No containers created yet</p></div>';
        return;
    }
    el.innerHTML = `<div class="dash-conn-list">${containers.map(c => {
        const isBuilding = c.status === 'building';
        const isFailed = c.status === 'failed';
        const statusClass = isBuilding ? 'status-building' : isFailed ? 'status-failed' : `status-${c.status}`;
        const statusText = isBuilding ? 'Building...' : isFailed ? 'Failed' : c.status === 'starting' ? 'Starting...' : c.status === 'stopping' ? 'Stopping...' : c.status;
        const disabled = isBuilding || isFailed || c.status === 'starting' || c.status === 'stopping';
        return `
        <div class="dash-conn-item ${isBuilding ? 'building' : ''}" onclick="showContainerDetail('${c.name}')" style="${isBuilding ? 'opacity:0.7' : ''}">
            <i class="bi bi-box-seam" style="color:var(--accent);font-size:16px"></i>
            <span class="dash-conn-name">${esc(c.name)}</span>
            <span class="dash-conn-ip">${esc(c.ip_address || '-')}</span>
            <span class="status-badge ${statusClass}">${isBuilding ? '<i class="bi bi-arrow-repeat spin"></i> ' : ''}${statusText}</span>
            <div class="dash-conn-actions">
                ${c.status === 'running' || c.status === 'starting'
                    ? `<button class="btn btn-warning btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); stopContainer('${c.name}')"><i class="bi bi-stop-fill"></i></button>`
                    : `<button class="btn btn-success btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); startContainer('${c.name}')"><i class="bi bi-play-fill"></i></button>`
                }
            </div>
        </div>`;
    }).join('')}</div>`;
}

let coreTerminal = null;
let coreWs = null;
let wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';

async function detectWsProtocol() {
    try {
        const res = await fetch(API + '/protocol', { headers: { 'X-ANK-Client': 'ank-panel', 'Authorization': 'Bearer ' + ankToken } });
        if (res.ok) {
            const data = await res.json();
            wsProtocol = data.protocol === 'https' ? 'wss:' : 'ws:';
        }
    } catch (e) {}
}

function initCoreTerminal() {
    const el = document.getElementById('core-terminal');
    if (!el) return;
    if (coreTerminal) { try { coreTerminal.dispose(); } catch(e){} coreTerminal = null; }
    if (coreWs) { try { coreWs.close(); } catch(e){} coreWs = null; }
    el.innerHTML = '';
    try {
        coreTerminal = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: "'Cascadia Code','Fira Code',monospace",
            theme: {
                background: '#0a0d12',
                foreground: '#d3d9e3',
                cursor: '#58a6ff'
            },
            allowProposedApi: true,
            scrollback: 5000
        });
        coreTerminal.open(el);
        coreTerminal.writeln('\x1b[1;36m  ANK Core Shell\x1b[0m');
        coreTerminal.writeln('\x1b[90m  Connecting...\x1b[0m\r\n');
        coreTerminal.focus();
        _connectCoreWs(el);
        const resize = () => {
            const rect = el.getBoundingClientRect();
            const cols = Math.floor(rect.width / 8.4);
            const rows = Math.floor(rect.height / 18);
            if (cols > 0 && rows > 0) {
                coreTerminal.resize(cols, rows);
                if (coreWs && coreWs.readyState === WebSocket.OPEN) coreWs.send(JSON.stringify({ type: 'resize', cols: cols, rows: rows }));
            }
        };
        window.addEventListener('resize', resize);
        setTimeout(resize, 100);
    } catch (e) {
        el.innerHTML = '<div style="color:#f85149;padding:20px">xterm.js failed to load. Check internet connection.</div>';
    }
}

async function _connectCoreWs(el) {
    await detectWsProtocol();
    const url = wsProtocol + '//' + location.host + '/ws/shell?cols=' + (coreTerminal ? coreTerminal.cols : 80) + '&rows=' + (coreTerminal ? coreTerminal.rows : 24) + '&token=' + encodeURIComponent(ankToken);
    console.log('WS Connecting:', url);
    coreWs = new WebSocket(url);
    coreWs.onopen = () => {
        if (coreTerminal) {
            coreTerminal.writeln('\x1b[90m  Connected. Type commands below.\x1b[0m\r\n');
            coreTerminal.focus();
        }
    };
    coreWs.onmessage = (ev) => {
        if (coreTerminal) coreTerminal.write(ev.data);
    };
    coreWs.onclose = () => {
        if (coreTerminal) {
            coreTerminal.writeln('\r\n\x1b[31m[Connection closed — click Shell tab to reconnect]\x1b[0m');
        }
    };
    coreWs.onerror = () => {
        if (coreTerminal) {
            coreTerminal.writeln('\r\n\x1b[31m[Connection error — check server is running]\x1b[0m');
        }
    };
    if (coreTerminal) {
        coreTerminal.onData((data) => {
            if (coreWs && coreWs.readyState === WebSocket.OPEN) coreWs.send(JSON.stringify({ type: 'input', data: data }));
        });
    }
}

document.getElementById('shell-clear-btn')?.addEventListener('click', () => {
    if (coreTerminal) { try { coreTerminal.clear(); } catch(e){} }
});

let containerBusy = {};

function setContainerLoading(name, action) {
    containerBusy[name] = action;
    const labelText = action === 'start' ? 'Starting...' : action === 'stop' ? 'Stopping...' : action === 'restart' ? 'Restarting...' : 'Working...';
    document.querySelectorAll(`.container-card[data-name="${name}"] button, .dash-conn-item[onclick*="${name}"] button`).forEach(b => b.disabled = true);
    const cardBadge = document.querySelector(`.container-card[data-name="${name}"] .status-badge`);
    if (cardBadge && action) { cardBadge.className = 'status-badge status-loading'; cardBadge.textContent = labelText; }
    const dashBadge = document.querySelector(`.dash-conn-item[onclick*="${name}"] .status-badge`);
    if (dashBadge && action) { dashBadge.className = 'status-badge status-loading'; dashBadge.textContent = labelText; }
    const detailBadge = document.getElementById('detail-status');
    if (detailBadge && action) { detailBadge.className = 'status-badge status-loading'; detailBadge.textContent = labelText; }
    ['detail-start', 'detail-stop', 'detail-restart', 'detail-delete'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = true;
    });
}

function clearContainerLoading(name) {
    delete containerBusy[name];
    document.querySelectorAll(`.container-card[data-name="${name}"] button, .dash-conn-item[onclick*="${name}"] button`).forEach(b => b.disabled = false);
    ['detail-start', 'detail-stop', 'detail-restart', 'detail-delete'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = false;
    });
    pollContainerStatus(name, 0);
}

async function pollContainerStatus(name, attempt) {
    if (attempt > 30) { loadAll(); return; }
    try {
        const c = await api('GET', `/containers/${name}`);
        if (c.status === 'building' || c.status === 'starting' || c.status === 'stopping') {
            setTimeout(() => pollContainerStatus(name, attempt + 1), 2000);
        } else {
            loadAll();
        }
    } catch (e) { loadAll(); }
}

async function startContainer(name) {
    setContainerLoading(name, 'start');
    try { await api('POST', `/containers/${name}/start`); toast(`Container "${name}" started`, 'success'); clearContainerLoading(name); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}
async function stopContainer(name) {
    setContainerLoading(name, 'stop');
    try { await api('POST', `/containers/${name}/stop`); toast(`Container "${name}" stopped`, 'success'); clearContainerLoading(name); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}
async function restartContainer(name) {
    setContainerLoading(name, 'restart');
    try { await api('POST', `/containers/${name}/restart`); toast(`Container "${name}" restarted`, 'success'); clearContainerLoading(name); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}
async function deleteContainer(name) {
    const ok = await confirmAction('Delete Container', `Delete "${name}"? This cannot be undone.`);
    if (!ok) return;
    setContainerLoading(name, 'delete');
    try {
        await api('DELETE', `/containers/${name}`);
        if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; }
        currentContainer = null;
        hideModal('detail-modal');
        toast(`Container "${name}" deleted`, 'success');
        clearContainerLoading(name);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}

let currentContainer = null;
let detailLogTimer = null;

async function showContainerDetail(name) {
    // Clean up previous log timer
    if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; }
    try {
        const [c, logs] = await Promise.all([api('GET', `/containers/${name}`), api('GET', `/containers/${name}/logs`)]);
        currentContainer = c;
        const isBuilding = c.status === 'building';
        const isFailed = c.status === 'failed';
        const isTransient = isBuilding || isFailed || c.status === 'starting' || c.status === 'stopping';

        document.getElementById('detail-name').textContent = c.name;

        const statusClass = isBuilding ? 'status-building' : isFailed ? 'status-failed' : `status-${c.status}`;
        const statusText = isBuilding ? 'Building...' : isFailed ? 'Failed' : c.status === 'starting' ? 'Starting...' : c.status === 'stopping' ? 'Stopping...' : c.status;
        document.getElementById('detail-status').textContent = statusText;
        document.getElementById('detail-status').className = `status-badge ${statusClass}`;

        // Show port warning if present
        const portWarningEl = document.getElementById('detail-port-warning');
        if (portWarningEl) {
            if (c.port_warning) {
                portWarningEl.textContent = c.port_warning;
                portWarningEl.style.display = '';
            } else {
                portWarningEl.style.display = 'none';
            }
        }

        document.getElementById('detail-ip').textContent = c.ip_address || '-';
        document.getElementById('detail-image').textContent = c.template_name || c.image || '-';
        document.getElementById('detail-mode').textContent = c.mode || '-';
        document.getElementById('detail-pid').textContent = c.pid || '-';
        document.getElementById('detail-memory').textContent = c.resources?.memory_limit || '-';
        document.getElementById('detail-cpu').textContent = c.resources?.cpu_limit_percent ? c.resources.cpu_limit_percent + '%' : '-';

        const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
        document.getElementById('detail-log-output').textContent = logText || (isBuilding ? 'Container is being built... Packages are being installed.' : 'No logs available');

        const running = c.status === 'running' || c.status === 'starting';
        const stopped = c.status === 'stopped' || c.status === 'stopping';
        document.getElementById('detail-start').disabled = running || isBuilding || isFailed;
        document.getElementById('detail-stop').disabled = stopped || isBuilding || isFailed;
        document.getElementById('detail-restart').disabled = isTransient;
        document.getElementById('detail-delete').disabled = isBuilding;
        document.getElementById('detail-start').onclick = async () => { await startContainer(name); showContainerDetail(name); };
        document.getElementById('detail-stop').onclick = async () => { await stopContainer(name); showContainerDetail(name); };
        document.getElementById('detail-restart').onclick = async () => { await restartContainer(name); showContainerDetail(name); };
        document.getElementById('detail-delete').onclick = () => deleteContainer(name);
        document.getElementById('detail-autostart').checked = c.autostart || false;
        document.getElementById('detail-mem-limit').value = c.resources?.memory_limit || '256M';
        document.getElementById('detail-cpu-limit').value = c.resources?.cpu_limit_percent || 50;
        document.getElementById('detail-p2p').checked = c.policies?.inter_container_p2p || false;
        document.getElementById('detail-host').checked = c.policies?.allow_host_access || false;
        document.getElementById('detail-internet').checked = c.policies?.allow_internet || false;
        renderPortMappings(c.port_mappings || []);
        document.getElementById('detail-serves-static').checked = c.serves_static || false;
        document.getElementById('detail-static-path').value = c.static_path || '';
        document.getElementById('detail-container-ip').value = c.ip_address || '-';
        document.getElementById('detail-container-subnet').value = (await api('GET', '/config')).network?.subnet || '-';
        const sshHint = document.getElementById('ssh-hint');
        if (c.ssh_port && c.status === 'running') {
            const host = location.hostname || 'localhost';
            document.getElementById('ssh-hint-cmd').textContent = `ssh root@${host} -p ${c.ssh_port}`;
            sshHint.style.display = 'flex';
        } else {
            sshHint.style.display = 'none';
        }

        document.querySelectorAll('.modal-tab').forEach(tab => {
            if (isBuilding || isFailed) {
                tab.style.pointerEvents = 'none';
                tab.style.opacity = '0.4';
                if (tab.dataset.mtab !== 'overview') {
                    tab.classList.remove('active');
                } else {
                    tab.classList.add('active');
                }
            } else {
                tab.style.pointerEvents = '';
                tab.style.opacity = '';
            }
        });
        document.querySelectorAll('.mtab').forEach(mtab => {
            if (isBuilding || isFailed) {
                if (mtab.id !== 'mtab-overview') {
                    mtab.classList.remove('active');
                    mtab.style.display = 'none';
                } else {
                    mtab.classList.add('active');
                    mtab.style.display = '';
                }
            } else {
                mtab.style.display = '';
            }
        });

        if (isBuilding || isFailed) {
            document.getElementById('detail-settings-form')?.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
            document.getElementById('detail-network-form')?.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
        } else {
            document.getElementById('detail-settings-form')?.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
            document.getElementById('detail-network-form')?.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
        }

        showModal('detail-modal');

        if (isBuilding) {
            let pollAttempt = 0;
            const pollBuilding = setInterval(async () => {
                pollAttempt++;
                if (pollAttempt > 60) { clearInterval(pollBuilding); return; }
                try {
                    const updated = await api('GET', `/containers/${name}`);
                    if (updated.status !== 'building' && updated.status !== 'starting') {
                        clearInterval(pollBuilding);
                        loadAll();
                        showContainerDetail(name);
                    }
                } catch (e) { clearInterval(pollBuilding); }
            }, 3000);
        }

        // Poll logs in real-time while modal is open
        const startDetailLogPoll = () => {
            if (detailLogTimer) return;
            detailLogTimer = setInterval(async () => {
                try {
                    if (!document.getElementById('detail-modal') || document.getElementById('detail-modal').classList.contains('hidden')) {
                        clearInterval(detailLogTimer); detailLogTimer = null; return;
                    }
                    const logs = await api('GET', `/containers/${name}/logs`);
                    const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
                    const el = document.getElementById('detail-log-output');
                    if (el) el.textContent = logText || 'No logs available';
                } catch (e) {
                    clearInterval(detailLogTimer); detailLogTimer = null;
                }
            }, 3000);
        };
        startDetailLogPoll();
        const detailModal = document.getElementById('detail-modal');
        if (detailModal) {
            detailModal._logCleanup = () => { if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; } };
        }
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

function renderPortMappings(ports) {
    const list = document.getElementById('port-mappings-list');
    if (!ports.length) { list.innerHTML = ''; return; }
    list.innerHTML = ports.map((p, i) => `
        <div class="port-row">
            <input type="number" placeholder="Host" value="${p.host_port || ''}" data-idx="${i}" data-field="host_port">
            <span style="color:var(--text-muted)">:</span>
            <input type="number" placeholder="Container" value="${p.container_port || ''}" data-idx="${i}" data-field="container_port">
            <select data-idx="${i}" data-field="protocol"><option value="tcp" ${p.protocol==='tcp'?'selected':''}>TCP</option><option value="udp" ${p.protocol==='udp'?'selected':''}>UDP</option></select>
            <button type="button" class="btn btn-ghost btn-sm remove-port" data-idx="${i}"><i class="bi bi-x-lg"></i></button>
        </div>
    `).join('');
    list.querySelectorAll('.remove-port').forEach(btn => {
        btn.onclick = () => { const ports = currentContainer.port_mappings || []; ports.splice(+btn.dataset.idx, 1); renderPortMappings(ports); };
    });
}

document.getElementById('add-port-btn')?.addEventListener('click', () => {
    if (!currentContainer) return;
    if (!currentContainer.port_mappings) currentContainer.port_mappings = [];
    currentContainer.port_mappings.push({ host_port: 0, container_port: 0, protocol: 'tcp' });
    renderPortMappings(currentContainer.port_mappings);
});

document.getElementById('detail-settings-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentContainer) return;
    const name = currentContainer.name;
    const btn = e.target.querySelector('button[type="submit"]');
    const portRows = document.querySelectorAll('.port-row');
    const ports = [];
    portRows.forEach(row => {
        const hp = row.querySelector('[data-field="host_port"]');
        const cp = row.querySelector('[data-field="container_port"]');
        const pr = row.querySelector('[data-field="protocol"]');
        if (hp && cp && (hp.value || cp.value)) {
            ports.push({ host_port: parseInt(hp.value)||0, container_port: parseInt(cp.value)||0, protocol: pr.value });
        }
    });
    await btnLoading(btn, async () => {
        try {
            const updateData = {
                autostart: document.getElementById('detail-autostart').checked,
                resources: { memory_limit: document.getElementById('detail-mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('detail-cpu-limit').value) },
                policies: { inter_container_p2p: document.getElementById('detail-p2p').checked, allow_host_access: document.getElementById('detail-host').checked, allow_internet: document.getElementById('detail-internet').checked },
                port_mappings: ports
            };
            const newPass = document.getElementById('detail-root-password').value;
            if (newPass && newPass.length >= 4) updateData.root_password = newPass;
            await api('POST', `/containers/${name}/update`, updateData);
            toast(`Settings saved for "${name}"`, 'success');
            showContainerDetail(name);
        } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });
});

document.getElementById('detail-network-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentContainer) return;
    const name = currentContainer.name;
    try {
        await api('POST', `/containers/${name}/update`, {
            serves_static: document.getElementById('detail-serves-static').checked,
            static_path: document.getElementById('detail-static-path').value || ''
        });
        toast(`Network settings saved for "${name}"`, 'success');
        showContainerDetail(name);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.querySelectorAll('.modal-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        tab.closest('.modal-content').querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
        tab.closest('.modal-content').querySelectorAll('.mtab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`mtab-${tab.dataset.mtab}`).classList.add('active');
        if (tab.dataset.mtab === 'terminal' && currentContainer) initContainerTerminal();
        if (tab.dataset.mtab === 'files' && currentContainer) showFileExplorer(currentContainer.name);
    });
});

let termHistory = [];
let termHistIdx = -1;
let xtermTerminal = null;
let xtermWs = null;

function initContainerTerminal() {
    const el = document.getElementById('container-terminal');
    if (!el) return;
    if (!currentContainer || currentContainer.status !== 'running') {
        el.innerHTML = '<div style="color:#f85149;padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> Container not running</div>';
        return;
    }

    // Cleanup old
    if (xtermTerminal) { try { xtermTerminal.dispose(); } catch(e){} xtermTerminal = null; }
    if (xtermWs) { try { xtermWs.close(); } catch(e){} xtermWs = null; }
    el.innerHTML = '';

    try {
        xtermTerminal = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
            theme: {
                background: '#0a0d12',
                foreground: '#d3d9e3',
                cursor: '#58a6ff',
                cursorAccent: '#0a0d12',
                selectionBackground: '#264f78',
                black: '#0d1117',
                red: '#f85171',
                green: '#3fb950',
                yellow: '#d29922',
                blue: '#58a6ff',
                magenta: '#bc8cff',
                cyan: '#39c5cf',
                white: '#d3d9e3',
                brightBlack: '#6e7681',
                brightRed: '#ff7b72',
                brightGreen: '#56d364',
                brightYellow: '#e3b341',
                brightBlue: '#79c0ff',
                brightMagenta: '#d2a8ff',
                brightCyan: '#56d4dd',
                brightWhite: '#f0f6fc'
            },
            allowProposedApi: true,
            scrollback: 5000
        });
        xtermTerminal.open(el);

        // Fit addon not available, manually size
        const resizeTerminal = () => {
            const rect = el.getBoundingClientRect();
            const cols = Math.floor(rect.width / 8.4);
            const rows = Math.floor(rect.height / 18);
            if (cols > 0 && rows > 0) {
                xtermTerminal.resize(cols, rows);
                if (xtermWs && xtermWs.readyState === WebSocket.OPEN) {
                    xtermWs.send(JSON.stringify({ type: 'resize', cols: cols, rows: rows }));
                }
            }
        };

        xtermTerminal.writeln('\x1b[1;36m  ANK Terminal\x1b[0m');
        xtermTerminal.writeln('\x1b[90m  Connecting to container: ' + currentContainer.name + '...\x1b[0m\r\n');
        xtermTerminal.focus();

        // Open WebSocket
        const wsUrl = wsProtocol + '//' + location.host + '/ws/terminal/' + currentContainer.name + '?cols=' + (xtermTerminal.cols || 80) + '&rows=' + (xtermTerminal.rows || 24) + '&token=' + encodeURIComponent(ankToken);
        xtermWs = new WebSocket(wsUrl);
        xtermWs.onopen = () => {
            resizeTerminal();
            xtermTerminal.focus();
        };
        xtermWs.onmessage = (ev) => {
            xtermTerminal.write(ev.data);
        };
        xtermWs.onclose = () => {
            xtermTerminal.writeln('\r\n\x1b[31m[Connection closed]\x1b[0m');
        };
        xtermWs.onerror = () => {
            xtermTerminal.writeln('\r\n\x1b[31m[Connection error]\x1b[0m');
        };

        // Send keystrokes to WebSocket
        xtermTerminal.onData((data) => {
            if (xtermWs && xtermWs.readyState === WebSocket.OPEN) {
                xtermWs.send(JSON.stringify({ type: 'input', data: data }));
            }
        });

        // Handle resize
        window.addEventListener('resize', resizeTerminal);
        setTimeout(resizeTerminal, 100);

    } catch (e) {
        el.innerHTML = '<div style="color:#f85149;padding:20px">xterm.js failed to load. Check internet connection.</div>';
    }
}

function closeContainerTerminal() {
    if (xtermWs) { try { xtermWs.close(); } catch(e){} xtermWs = null; }
    if (xtermTerminal) { try { xtermTerminal.dispose(); } catch(e){} xtermTerminal = null; }
}

document.getElementById('create-btn').addEventListener('click', () => showModal('create-modal'));
document.getElementById('create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const origHTML = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Creating...';
    const name = document.getElementById('container-name').value;
    const imageVal = document.getElementById('container-image').value;
    if (imageVal.startsWith('template:')) {
        const templateId = imageVal.replace('template:', '');
        const rootPass = document.getElementById('container-root-password').value || 'admin123';
        try {
            toast(`Deploying template "${templateId}" as "${name}"...`, 'info');
            await api('POST', '/images/deploy', { template: templateId, name, root_password: rootPass });
            hideModal('create-modal');
            document.getElementById('create-form').reset();
            toast(`Template deployed as "${name}"`, 'success');
            loadAll();
        } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
        submitBtn.disabled = false;
        submitBtn.innerHTML = origHTML;
        return;
    }
    const data = {
        name,
        image: imageVal,
        root_password: document.getElementById('container-root-password').value,
        autostart: document.getElementById('container-autostart').checked,
        policies: {
            inter_container_p2p: document.getElementById('policy-p2p').checked,
            allow_host_access: document.getElementById('policy-host').checked,
            allow_internet: document.getElementById('policy-internet').checked
        },
        resources: { memory_limit: document.getElementById('mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('cpu-limit').value) }
    };
    const sshPortVal = document.getElementById('container-ssh-port').value;
    if (sshPortVal) data.ssh_port = parseInt(sshPortVal);
    try {
        await api('POST', '/containers', data);
        hideModal('create-modal');
        document.getElementById('create-form').reset();
        toast(`Container "${data.name}" created`, 'success');
        loadAll();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    submitBtn.disabled = false;
    submitBtn.innerHTML = origHTML;
});

document.getElementById('pull-btn').addEventListener('click', async () => {
    const version = await inputModal('Pull Image', 'Alpine version to download:', '3.20');
    if (!version) return;
    await btnLoading(document.getElementById('pull-btn'), async () => {
        try {
            toast(`Pulling alpine-${version}...`, 'info');
            await api('POST', '/images/pull', { version });
            toast(`Image alpine-${version} downloaded`, 'success');
            loadAll();
        } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });
});

async function loadTemplates() {
    try {
        const templates = await api('GET', '/images/templates');
        renderTemplates(templates);
    } catch (e) { console.error('Templates load failed:', e); }
}

function renderTemplates(templates) {
    const grid = document.getElementById('templates-grid');
    if (!grid) return;
    grid.innerHTML = templates.map(t => `
        <div class="template-card" onclick="deployTemplate('${t.id}', '${esc(t.name)}', ${t.base_ready})" style="border-left: 3px solid ${t.color}">
            <div class="template-icon" style="color:${t.color}"><i class="bi ${t.icon}"></i></div>
            <div class="template-name">${esc(t.name)}</div>
            <div class="template-desc">${esc(t.description)}</div>
            <span class="template-badge ${t.base_ready ? 'ready' : 'pending'}">${t.base_ready ? 'Ready' : 'Pull base first'}</span>
        </div>
    `).join('');
}

async function deployTemplate(id, name, baseReady) {
    if (!baseReady) { toast('Download the Alpine base image first (Pull Alpine)', 'warning'); return; }
    const result = await customModal('Deploy ' + name, [
        { id: 'tpl-name', label: 'Container name:', type: 'text', value: name.toLowerCase().replace(/\s+/g, '-') },
        { id: 'tpl-pass', label: 'Root password:', type: 'password', value: 'admin123' }
    ]);
    if (!result) return;
    const containerName = result['tpl-name'];
    const rootPass = result['tpl-pass'];
    if (!containerName) { toast('Container name required', 'warning'); return; }
    if (!rootPass || rootPass.length < 4) { toast('Password must be at least 4 characters', 'warning'); return; }
    try {
        toast(`Deploying ${name} as "${containerName}"...`, 'info');
        await api('POST', '/images/deploy', { template: id, name: containerName, root_password: rootPass });
        toast(`${name} deployed as "${containerName}"`, 'success');
        loadAll();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

let uploadContainer = null;
function showUploadModal(containerName) {
    uploadContainer = containerName;
    document.getElementById('upload-container-name').textContent = containerName;
    document.getElementById('upload-file-input').value = '';
    document.getElementById('upload-result').textContent = '';
    showModal('upload-modal');
}

async function uploadFiles(files) {
    if (!uploadContainer || !files.length) return;
    const result = document.getElementById('upload-result');
    result.textContent = 'Uploading...';
    const formData = new FormData();
    for (const f of files) formData.append('file', f);
    try {
        const headers = { 'X-ANK-Client': 'ank-panel' };
        if (ankToken) headers['Authorization'] = 'Bearer ' + ankToken;
        const res = await fetch(`/api/containers/${uploadContainer}/upload`, { method: 'PUT', headers, body: formData });
        const data = await res.json();
        if (res.ok) { result.textContent = `Uploaded ${data.files?.length || 0} file(s)`; toast(`Files uploaded to "${uploadContainer}"`, 'success'); } else { result.textContent = data.error || 'Upload failed'; }
    } catch (e) { result.textContent = e.message; }
}

document.getElementById('upload-file-input')?.addEventListener('change', (e) => { uploadFiles(e.target.files); });
const uploadArea = document.getElementById('upload-drop-area');
if (uploadArea) {
    uploadArea.addEventListener('dragover', (e) => { e.preventDefault(); uploadArea.classList.add('dragover'); });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
    uploadArea.addEventListener('drop', (e) => { e.preventDefault(); uploadArea.classList.remove('dragover'); uploadFiles(e.dataTransfer.files); });
    uploadArea.addEventListener('click', () => document.getElementById('upload-file-input')?.click());
}

async function loadNetworks() {
    try {
        const [networks, netInfo] = await Promise.all([api('GET', '/networks'), api('GET', '/networks/info')]);
        renderNetworks(networks, netInfo);
    } catch (e) { toast(`Failed to load networks: ${e.message}`, 'error'); }
}

function renderNetworks(networks, info) {
    const container = document.getElementById('networks-list');
    if (!networks || networks.length === 0) {
        container.innerHTML = `<div class="empty-state"><i class="bi bi-hdd-network"></i><p>No networks configured</p></div>`;
        return;
    }
    container.innerHTML = networks.map(net => `
        <div class="network-card">
            <div class="net-header">
                <h3><i class="bi bi-hdd-network"></i> ${net.name}</h3>
                <span class="status-badge status-running">${net.mode}</span>
            </div>
            <div class="network-details">
                <div class="net-detail"><span class="label">Subnet</span><span class="value">${net.subnet}</span></div>
                <div class="net-detail"><span class="label">Gateway</span><span class="value">${net.gateway}</span></div>
                <div class="net-detail"><span class="label">NAT</span><span class="value">${net.nat ? 'Enabled' : 'Disabled'}</span></div>
                <div class="net-detail"><span class="label">WAN Interface</span><span class="value">${info.wan_interface || '-'}</span></div>
                <div class="net-detail"><span class="label">IP Forward</span><span class="value">${info.ip_forward === '1' ? 'Enabled' : 'Disabled'}</span></div>
                <div class="net-detail"><span class="label">Containers</span><span class="value">${net.containers?.length || 0}</span></div>
            </div>
            ${net.containers && net.containers.length > 0 ? `
                <div class="net-containers">
                    <h4>Connected Containers</h4>
                    ${net.containers.map(c => `
                        <div class="net-container-item">
                            <span><i class="bi bi-box-seam" style="color:var(--accent)"></i> ${c.name}</span>
                            <span>${c.ip}</span>
                            <span class="status-badge status-${c.status}">${c.status}</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `).join('');
}

document.getElementById('network-config-btn').addEventListener('click', async () => {
    try {
        const info = await api('GET', '/networks/info');
        document.getElementById('net-bridge').value = info.bridge || 'ank0';
        document.getElementById('net-subnet').value = (info.subnet || '').replace('/24', '');
        document.getElementById('net-gateway').value = info.gateway || '';
        document.getElementById('net-nat').checked = info.nat_enabled !== false;
        showModal('network-modal');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('network-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const subnet = document.getElementById('net-subnet').value.trim();
    const gateway = document.getElementById('net-gateway').value.trim();
    const bridge = document.getElementById('net-bridge').value.trim();
    const nat = document.getElementById('net-nat').checked;
    if (!subnet.match(/^\d+\.\d+\.\d+\.0$/)) { toast('Subnet must be a /24 network ending in .0', 'error'); return; }
    try {
        await api('POST', '/networks', { subnet, gateway, bridge, nat });
        hideModal('network-modal');
        toast(`Network ${subnet}/24 configured`, 'success');
        loadAll();
        loadNetworks();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        await api('POST', '/auth/password', {
            current_password: document.getElementById('current-password').value,
            username: document.getElementById('new-username').value || undefined,
            new_password: document.getElementById('new-password').value || undefined
        });
        toast('Credentials updated', 'success');
        document.getElementById('password-form').reset();
        const newPass = document.getElementById('new-password').value;
        const newUser = document.getElementById('new-username').value;
        if (newPass) {
            // Re-login with new credentials to get fresh token
            const user = newUser || document.getElementById('username-input').value;
            const loginRes = await fetch(`${API}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
                body: JSON.stringify({ username: user, password: newPass })
            });
            const loginData = await loginRes.json();
            if (loginData.token) {
                ankToken = loginData.token;
                localStorage.setItem('ank_token', ankToken);
            }
        }
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

let refreshSeconds = parseInt(localStorage.getItem('ank_refresh') || '15');
let refreshTimer = null;
let _infoCounter = 0;

function startRefreshTimer() {
    if (refreshTimer) clearInterval(refreshTimer);
    if (refreshSeconds <= 0) return;
    refreshTimer = setInterval(async () => {
        if (!isLoggedIn || document.getElementById('app-screen').classList.contains('hidden')) return;
        if (document.hidden) return;
        try {
            const status = await api('GET', '/status');
            document.getElementById('stat-running').textContent = status.containers_running;
            document.getElementById('stat-stopped').textContent = status.containers_stopped || 0;
            document.getElementById('stat-total').textContent = status.containers_total;
            document.getElementById('stat-uptime').textContent = fmtUptime(status.uptime || 0);
            _infoCounter++;
            if (_infoCounter >= 4) {
                _infoCounter = 0;
                const info = await api('GET', '/system/info');
                document.getElementById('stat-cpu').textContent = (info.cpu_usage != null ? info.cpu_usage + '%' : '-');
                document.getElementById('stat-cpu-cores').textContent = (info.cpu_cores || 0) > 0 ? info.cpu_cores + ' cores - ' : '';
                const memT = info.memory?.total_kb || 0;
                const memA = info.memory?.available_kb || 0;
                if (memT > 0 && memA > 0) {
                    const used = memT - memA;
                    document.getElementById('info-memory').textContent = `${fmtBytes(used * 1024)} used / ${fmtBytes(memT * 1024)} total (${Math.round(used/memT*100)}%)`;
                }
            }
        } catch (e) { }
    }, refreshSeconds * 1000);
}

document.getElementById('panel-settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const bind = document.getElementById('setting-bind').value;
    const refresh = document.getElementById('setting-refresh').value;
    const autostart = document.getElementById('setting-autostart').checked;
    try {
        await api('POST', '/config', { bind_address: bind, refresh_interval: parseInt(refresh), autostart_on_boot: autostart });
        refreshSeconds = parseInt(refresh);
        localStorage.setItem('ank_refresh', refresh);
        startRefreshTimer();
        toast('Panel settings saved', 'success');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('restart-device-btn')?.addEventListener('click', async () => {
    const ok = await confirmAction('Restart Device', 'This will reboot the Android device. Keep USB connected. Continue?');
    if (!ok) return;
    try {
        toast('Rebooting device...', 'warning');
        await api('POST', '/system/restart-device');
        document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#e2e8f0;font-family:sans-serif;text-align:center"><div><h1 style="font-size:32px;margin-bottom:16px">Device Rebooting...</h1><p style="color:#94a3b8">The device is restarting. Wait for it to come back online.</p></div></div>';
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('restart-server-btn')?.addEventListener('click', async () => {
    const ok = await confirmAction('Restart Server', 'This will stop all containers and restart the ANK server. Continue?');
    if (!ok) return;
    try {
        toast('Restarting server...', 'warning');
        await api('POST', '/system/restart-server');
        document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#e2e8f0;font-family:sans-serif;text-align:center"><div><h1 style="font-size:32px;margin-bottom:16px">Server Restarting...</h1><p style="color:#94a3b8">The ANK server is restarting. This page will reload shortly.</p></div></div>';
        setTimeout(() => location.reload(), 5000);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('uninstall-btn')?.addEventListener('click', async () => {
    const ok = await confirmAction('Uninstall ANK', 'This will PERMANENTLY delete ALL containers, images, configs, and the ANK directory. This cannot be undone. Continue?');
    if (!ok) return;
    const ok2 = await confirmAction('Final Warning', 'Are you absolutely sure? All data will be lost.');
    if (!ok2) return;
    try {
        toast('Uninstalling ANK... Server will shut down.', 'warning');
        await api('POST', '/system/uninstall');
        setTimeout(() => {
            document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0f172a;color:#e2e8f0;font-family:sans-serif;text-align:center"><div><h1 style="font-size:32px;margin-bottom:16px">ANK Uninstalled</h1><p style="color:#94a3b8">All data has been removed. You can close this tab.</p></div></div>';
        }, 2000);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

async function loadSettings() {
    try {
        const cfg = await api('GET', '/config');
        document.getElementById('setting-bind').value = cfg.bind_address || '0.0.0.0';
        document.getElementById('setting-refresh').value = cfg.refresh_interval != null ? cfg.refresh_interval : 10;
        refreshSeconds = parseInt(cfg.refresh_interval != null ? cfg.refresh_interval : localStorage.getItem('ank_refresh') || '10');
        localStorage.setItem('ank_refresh', refreshSeconds);
        const autostartEl = document.getElementById('setting-autostart');
        if (autostartEl) autostartEl.checked = cfg.autostart_on_boot !== false;
    } catch (e) { }
    try {
        const info = await api('GET', '/system/info');
        document.getElementById('info-rootfs').textContent = info.rootfs_size || '-';
        document.getElementById('info-containers-size').textContent = info.containers_size || '-';
        document.getElementById('info-total-size').textContent = info.total_size || '-';
        document.getElementById('info-device-free').textContent = info.device_free || '-';
    } catch (e) { }
}

document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => {
        const modal = btn.closest('.modal');
        if (modal && modal.id === 'detail-modal') {
            closeContainerTerminal();
            if (modal._logCleanup) modal._logCleanup();
        }
        modal.classList.add('hidden');
    });
});
document.querySelectorAll('.modal-overlay').forEach(ov => {
    ov.addEventListener('click', () => {
        const modal = ov.closest('.modal');
        if (modal && modal.id === 'detail-modal') {
            closeContainerTerminal();
            if (modal._logCleanup) modal._logCleanup();
        }
        modal.classList.add('hidden');
    });
});

if (isLoggedIn) { showScreen('app-screen'); detectWsProtocol().then(() => { loadAll(); loadSettings(); startRefreshTimer(); }); }
else { showScreen('login-screen'); }

let logsPaused = false;
let logsOffset = 0;
const LOG_POLL_MS = 3000;

async function loadLogs(append) {
    try {
        const filter = document.getElementById('log-filter')?.value || 'all';
        const params = new URLSearchParams({ filter });
        if (append && logsOffset > 0) params.set('offset', logsOffset);
        const data = await api('GET', `/logs?${params}`);
        const viewer = document.getElementById('log-viewer');
        if (!data.lines || data.lines.length === 0) {
            if (!append) viewer.innerHTML = '<div class="log-empty"><i class="bi bi-terminal"></i><p>No logs available</p></div>';
            return;
        }
        if (append) {
            const wasAtBottom = viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 30;
            const frag = document.createDocumentFragment();
            data.lines.forEach(line => { const div = document.createElement('div'); div.className = 'log-entry'; div.innerHTML = colorizeLog(line); frag.appendChild(div); });
            viewer.appendChild(frag);
            if (wasAtBottom) viewer.scrollTop = viewer.scrollHeight;
        } else {
            viewer.innerHTML = data.lines.map(line => { const div = document.createElement('div'); div.className = 'log-entry'; div.innerHTML = colorizeLog(line); return div.outerHTML; }).join('');
            viewer.scrollTop = viewer.scrollHeight;
        }
        logsOffset = data.new_offset || logsOffset + data.lines.length;
    } catch (e) { console.error('Logs load failed:', e); }
}

function colorizeLog(line) {
    return esc(line)
        .replace(/\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\b/g, '<span class="log-time">$1</span>')
        .replace(/\bINFO\b/g, '<span class="log-level-info">INFO</span>')
        .replace(/\bWARN(ING)?\b/g, '<span class="log-level-warn">WARN</span>')
        .replace(/\bERROR\b/g, '<span class="log-level-error">ERROR</span>')
        .replace(/\bDEBUG\b/g, '<span class="log-level-info">DEBUG</span>');
}

let logsTimer = null;
function startLogsPoll() { if (logsTimer) return; logsTimer = setInterval(() => { if (!logsPaused) loadLogs(true); }, LOG_POLL_MS); }
function stopLogsPoll() { if (logsTimer) { clearInterval(logsTimer); logsTimer = null; } }

document.getElementById('logs-pause-btn')?.addEventListener('click', () => {
    logsPaused = !logsPaused;
    const btn = document.getElementById('logs-pause-btn');
    const viewer = document.getElementById('log-viewer');
    if (logsPaused) { btn.innerHTML = '<i class="bi bi-play-fill"></i> Resume'; viewer?.classList.add('log-paused'); } else { btn.innerHTML = '<i class="bi bi-pause-fill"></i> Pause'; viewer?.classList.remove('log-paused'); loadLogs(true); }
});

document.getElementById('logs-clear-btn')?.addEventListener('click', () => {
    document.getElementById('log-viewer').innerHTML = '<div class="log-empty"><i class="bi bi-terminal"></i><p>Logs cleared</p></div>';
    logsOffset = 0;
});

document.getElementById('logs-refresh-btn')?.addEventListener('click', () => { logsOffset = 0; loadLogs(false); });
document.getElementById('log-filter')?.addEventListener('change', () => { logsOffset = 0; loadLogs(false); });

let fileContainerName = '';
let fileCurrentPath = '/';

function getFileIcon(item) {
    if (item.type === 'directory') return '<i class="bi bi-folder-fill file-icon-dir"></i>';
    const ext = item.name.split('.').pop().toLowerCase();
    if (['jpg','jpeg','png','gif','svg','webp','ico'].includes(ext)) return '<i class="bi bi-file-earmark-image file-icon-img"></i>';
    if (['html','css','js','py','sh','php','json','xml','yml','yaml','conf','cfg','ini','md','txt','log','csv'].includes(ext)) return '<i class="bi bi-file-earmark-code file-icon-code"></i>';
    if (['zip','tar','gz','bz2','xz','7z','rar'].includes(ext)) return '<i class="bi bi-file-earmark-zip file-icon-archive"></i>';
    return '<i class="bi bi-file-earmark file-icon-file"></i>';
}

function formatSize(bytes) {
    if (!bytes || bytes === 0) return '-';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}

function renderBreadcrumbs() {
    const el = document.getElementById('file-breadcrumbs');
    const parts = fileCurrentPath.split('/').filter(Boolean);
    let html = '<span class="breadcrumb-item" data-path="/">/</span>';
    let accumulated = '';
    parts.forEach((part, i) => {
        accumulated += '/' + part;
        const p = accumulated;
        html += '<span class="breadcrumb-sep">/</span>';
        html += '<span class="breadcrumb-item" data-path="' + esc(p) + '">' + esc(part) + '</span>';
    });
    el.innerHTML = html;
    el.querySelectorAll('.breadcrumb-item').forEach(item => {
        item.addEventListener('click', () => { fileCurrentPath = item.dataset.path; loadFiles(); });
    });
}

async function loadFiles() {
    if (!fileContainerName) return;
    renderBreadcrumbs();
    const listEl = document.getElementById('file-list');
    listEl.innerHTML = '<div class="file-empty"><i class="bi bi-hourglass-split"></i> Loading...</div>';
    try {
        const data = await api('GET', `/containers/${fileContainerName}/files?path=${encodeURIComponent(fileCurrentPath)}`);
        if (!data.items || data.items.length === 0) { listEl.innerHTML = '<div class="file-empty"><i class="bi bi-folder"></i> Empty directory</div>'; return; }
        let html = '<div class="file-row file-header"><div class="file-name">Name</div><div class="file-size">Size</div><div class="file-date">Modified</div></div>';
        const dirs = data.items.filter(i => i.type === 'directory');
        const files = data.items.filter(i => i.type === 'file');
        [...dirs, ...files].forEach(item => {
            const onclick = item.type === 'directory' ? "fileNavigate('" + esc(item.path) + "')" : "openFile('" + esc(item.path) + "')";
            const dlBtn = item.type === 'file' ? '<button class="btn btn-xs btn-ghost" onclick="event.stopPropagation();downloadFile(\'' + esc(item.path) + '\')" title="Download"><i class="bi bi-download"></i></button>' : '';
            const actionsHtml = '<div class="file-actions-row">' + dlBtn +
                '<button class="btn btn-xs btn-ghost" onclick="event.stopPropagation();renameFilePrompt(\'' + esc(item.path) + '\')" title="Rename"><i class="bi bi-pencil"></i></button>' +
                '<button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteFilePrompt(\'' + esc(item.path) + '\')" title="Delete"><i class="bi bi-trash3"></i></button></div>';
            html += '<div class="file-row" onclick="' + onclick + '">' + getFileIcon(item) +
                '<div class="file-name">' + esc(item.name) + '</div>' +
                '<div class="file-size">' + formatSize(item.size) + '</div>' +
                '<div class="file-date">' + formatDate(item.modified) + '</div>' +
                actionsHtml + '</div>';
        });
        listEl.innerHTML = html;
    } catch (e) { listEl.innerHTML = '<div class="file-empty"><i class="bi bi-exclamation-triangle"></i> ' + esc(e.message || 'Failed to load files') + '</div>'; }
}

function fileNavigate(path) { fileCurrentPath = path; loadFiles(); }

async function openFile(path) {
    if (!fileContainerName) return;
    try {
        const data = await api('GET', `/containers/${fileContainerName}/files/content?path=${encodeURIComponent(path)}`);
        document.getElementById('file-list').parentElement.classList.add('hidden');
        document.getElementById('file-editor').classList.remove('hidden');
        document.getElementById('file-editor-name').textContent = path;
        document.getElementById('file-editor-content').value = data.content || '';
        document.getElementById('file-editor-content').dataset.path = path;
        document.getElementById('file-editor-content').dataset.binary = data.binary ? '1' : '0';
    } catch (e) { toast(e.message || 'Failed to open file', 'error'); }
}

function closeEditor() {
    document.getElementById('file-editor').classList.add('hidden');
    document.getElementById('file-list').parentElement.classList.remove('hidden');
}

async function saveFile() {
    const ta = document.getElementById('file-editor-content');
    const path = ta.dataset.path;
    if (ta.dataset.binary === '1') { toast('Cannot edit binary files', 'warning'); return; }
    try { await api('POST', `/containers/${fileContainerName}/files/write`, { path: path, content: ta.value }); toast('File saved', 'success'); } catch (e) { toast(e.message || 'Failed to save', 'error'); }
}

async function deleteFilePrompt(path) {
    const confirmed = await confirmAction('Delete File', 'Delete ' + path + '?');
    if (!confirmed) return;
    try { await api('DELETE', `/containers/${fileContainerName}/files?path=${encodeURIComponent(path)}`); toast('Deleted', 'success'); loadFiles(); } catch (e) { toast(e.message || 'Failed to delete', 'error'); }
}

async function renameFilePrompt(oldPath) {
    const name = oldPath.split('/').pop();
    const newName = await inputModal('Rename', 'Rename to:', name);
    if (!newName || newName === name) return;
    const dir = oldPath.substring(0, oldPath.lastIndexOf('/')) || '/';
    const newPath = dir + '/' + newName;
    try { await api('POST', `/containers/${fileContainerName}/files/rename`, { old_path: oldPath, new_path: newPath }); toast('Renamed', 'success'); loadFiles(); } catch (e) { toast(e.message || 'Failed to rename', 'error'); }
}

async function downloadFile(path) {
    if (!fileContainerName) return;
    const a = document.createElement('a');
    a.href = API + `/containers/${fileContainerName}/files/download?path=${encodeURIComponent(path)}`;
    a.target = '_blank';
    a.download = path.split('/').pop();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function createNewFile() {
    const name = await inputModal('New File', 'New file name:');
    if (!name) return;
    const path = fileCurrentPath === '/' ? '/' + name : fileCurrentPath + '/' + name;
    api('POST', `/containers/${fileContainerName}/files/write`, { path: path, content: '' }).then(() => { toast('File created', 'success'); loadFiles(); }).catch(e => toast(e.message || 'Failed', 'error'));
}

async function createNewDir() {
    const name = await inputModal('New Folder', 'New folder name:');
    if (!name) return;
    const path = fileCurrentPath === '/' ? '/' + name : fileCurrentPath + '/' + name;
    api('POST', `/containers/${fileContainerName}/files/mkdir`, { path: path }).then(() => { toast('Folder created', 'success'); loadFiles(); }).catch(e => toast(e.message || 'Failed', 'error'));
}

async function uploadToContainer(files) {
    if (!fileContainerName || !files.length) return;
    const token = localStorage.getItem('ank_token') || '';
    for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        try {
            const res = await fetch(API + `/containers/${fileContainerName}/upload`, { method: 'PUT', headers: { 'Authorization': 'Bearer ' + token, 'X-ANK-Client': 'ank-panel' }, body: form });
            if (!res.ok) throw new Error('Upload failed');
        } catch (e) { toast('Upload failed: ' + file.name, 'error'); }
    }
    toast('Upload complete', 'success');
    loadFiles();
}

function showFileExplorer(name) { fileContainerName = name; fileCurrentPath = '/'; closeEditor(); loadFiles(); }

document.getElementById('file-btn-refresh')?.addEventListener('click', loadFiles);
document.getElementById('file-btn-new')?.addEventListener('click', createNewFile);
document.getElementById('file-btn-mkdir')?.addEventListener('click', createNewDir);
document.getElementById('file-btn-save')?.addEventListener('click', saveFile);
document.getElementById('file-btn-close-editor')?.addEventListener('click', closeEditor);
document.getElementById('file-btn-upload')?.addEventListener('click', () => document.getElementById('file-upload-input')?.click());
document.getElementById('file-upload-input')?.addEventListener('change', (e) => { uploadToContainer(e.target.files); e.target.value = ''; });

const ANKFILE_EXAMPLE = `# ANK Example: Cloudreve (personal cloud storage)
FROM alpine-3.20
PASSWD ank123
RUN apk add --allow-untrusted curl tar sqlite
RUN mkdir -p /data/cloudreve
RUN curl -L https://github.com/cloudreve/cloudreve/releases/download/4.18.0/cloudreve_4.18.0_linux_armv7.tar.gz | tar xz -C /usr/local/bin
EXPOSE 5212
WORKDIR /usr/local/bin
CMD cloudreve --base-dir /data/cloudreve -l :5212`;

document.getElementById('ankfile-build-btn')?.addEventListener('click', async () => {
    const content = document.getElementById('ankfile-content')?.value?.trim();
    const name = document.getElementById('ankfile-name')?.value?.trim() || 'ank-build';
    if (!content) { toast('Ankfile is empty', 'error'); return; }
    if (!content.includes('FROM')) { toast('Ankfile must have a FROM instruction', 'error'); return; }
    try { toast(`Building from Ankfile as "${name}"...`, 'info'); await api('POST', '/images/ankfile', { content, name }); toast(`Ankfile built as "${name}"`, 'success'); loadAll(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('ankfile-example-btn')?.addEventListener('click', () => {
    document.getElementById('ankfile-content').value = ANKFILE_EXAMPLE;
    document.getElementById('ankfile-name').value = 'cloudreve';
    toast('Example Ankfile loaded', 'info');
});

/* ============================================================
   Theme (dark/light)
   ============================================================ */

function getTheme() { return localStorage.getItem('ank_theme') || (document.documentElement.getAttribute('data-theme') || 'dark'); }
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('ank_theme', theme);
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute('content', theme === 'light' ? '#f4f5f8' : '#0b0d13');
}
function toggleTheme() { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); }

['login', 'mobile', 'desktop'].forEach(ctx => {
    document.getElementById(`theme-toggle-${ctx}`)?.addEventListener('click', toggleTheme);
});