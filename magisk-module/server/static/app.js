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

function toast(msg, type = 'info', duration = 4000) {
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    const icons = { success: 'bi-check-circle-fill', error: 'bi-exclamation-circle-fill', info: 'bi-info-circle-fill', warning: 'bi-exclamation-triangle-fill' };
    el.className = `toast toast-${type}`;
    el.style.display = 'flex';
    el.style.alignItems = 'center';
    el.innerHTML = `<i class="bi ${icons[type] || icons.info}"></i> <span>${msg}</span>`;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(100%)'; setTimeout(() => el.remove(), 300); }, duration);
    return el;
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
            let el;
            if (f.type === 'select') {
                el = document.createElement('select');
                el.innerHTML = f.options;
            } else {
                el = document.createElement('input');
                el.type = f.type || 'text';
                el.value = f.value || '';
                el.placeholder = f.label;
            }
            el.id = f.id;
            el.style.cssText = 'width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);margin-bottom:8px;font-size:14px;';
            el.className = 'custom-modal-field';
            container.appendChild(el);
            return el;
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

function showApkFailureModal(containerName, failure) {
    const pkgs = Array.isArray(failure.packages) ? failure.packages.join(' ') : (failure.packages || '');
    const sshPort = failure.ssh_port || 22;
    const overlay = document.createElement('div');
    overlay.id = 'apk-failure-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
        <div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:12px;width:90%;max-width:520px;padding:24px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
                <i class="bi bi-exclamation-triangle" style="font-size:24px;color:var(--warning,#f59e0b);"></i>
                <h3 style="margin:0;font-size:16px;">Package Install Failed</h3>
            </div>
            <p style="margin:0 0 12px;font-size:13px;color:var(--text-secondary);">
                Failed to install packages after 2 attempts in container <strong>${containerName}</strong>:
            </p>
            <div style="background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:16px;">
                <code style="font-size:12px;color:var(--warning);">${pkgs}</code>
            </div>
            <p style="margin:0 0 8px;font-size:13px;color:var(--text-secondary);">
                You can install manually via SSH:
            </p>
            <div style="display:flex;align-items:center;gap:8px;background:var(--bg-tertiary);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:16px;">
                <code id="apk-failure-ssh" style="font-size:12px;flex:1;user-select:all;">ssh root@${window.location.hostname} -p ${sshPort}</code>
                <button class="btn btn-xs btn-ghost" onclick="navigator.clipboard.writeText(document.getElementById('apk-failure-ssh').textContent);toast('Copied!','success')"><i class="bi bi-clipboard"></i></button>
            </div>
            <p style="margin:0 0 16px;font-size:12px;color:var(--text-muted);">
                Then run: <code>apk add --allow-untrusted ${pkgs}</code>
            </p>
            <div style="display:flex;gap:8px;justify-content:flex-end;">
                <button class="btn btn-danger btn-sm" id="apk-fail-cancel"><i class="bi bi-trash3"></i> Cancel & Remove</button>
                <button class="btn btn-primary btn-sm" id="apk-fail-continue"><i class="bi bi-check-lg"></i> Continue Build</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    document.getElementById('apk-fail-continue').addEventListener('click', () => {
        overlay.remove();
        toast(`Container "${containerName}" deployed without packages. Install via SSH.`, 'warning');
        loadAll();
    });
    document.getElementById('apk-fail-cancel').addEventListener('click', async () => {
        overlay.remove();
        try {
            await api('DELETE', `/containers/${containerName}`);
            toast(`Container "${containerName}" deleted`, 'success');
            loadAll();
        } catch (e) { toast(`Failed to delete: ${e.message}`, 'error'); }
    });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
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
        if (item.dataset.tab === 'stacks') loadStacks();
        if (item.dataset.tab === 'backups') loadBackups();
        if (item.dataset.tab === 'nodes') { loadNodes(); loadPairingRequests(); }
        if (item.dataset.tab === 'logs') { logsOffset = 0; loadLogs(false); startLogsPoll(); }
        if (item.dataset.tab === 'shell') initCoreTerminal(document.getElementById('shell-node-selector')?.value || 'local');
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
        renderContainers(containers, 'local');
        renderImages(images, 'local');
        populateImageSelect(images);
        renderDashboardContainers(containers);
        renderDashboardNodes();
        loadTemplates();
        loadStacks();
        loadBackups();
        loadNodes();
        loadPairingRequests();
        if (selectedNode !== 'local') {
            loadContainers();
            loadImages();
        }
    } catch (e) { console.error('Load failed:', e); }
}

function renderContainers(containers, nodeId) {
    const list = document.getElementById('containers-list');
    const isAll = nodeId === 'all';
    const isRemoteFixed = nodeId && nodeId !== 'local' && nodeId !== 'all';
    if (!containers || containers.length === 0) {
        const msg = isAll ? 'No containers found on any node.' : isRemoteFixed ? 'No containers on this remote node.' : 'No containers yet. Click "New Container".';
        list.innerHTML = `<div class="empty-state"><i class="bi bi-box-seam"></i><p>${msg}</p></div>`;
        return;
    }
    list.innerHTML = containers.map(c => {
        const name = c.name || '';
        const itemNode = c.node || (isRemoteFixed ? nodeId : 'local');
        const isRemote = itemNode !== 'local';
        const isBuilding = c.status === 'building';
        const isFailed = c.status === 'failed';
        const statusClass = isBuilding ? 'status-building' : isFailed ? 'status-failed' : `status-${c.status}`;
        const statusText = isBuilding ? 'Building...' : isFailed ? 'Failed' : c.status === 'starting' ? 'Starting...' : c.status === 'stopping' ? 'Stopping...' : c.status;
        const disabled = isBuilding || isFailed || c.status === 'starting' || c.status === 'stopping';
        const isRunning = c.status === 'running' || c.status === 'starting';
        const startAction = isRemote ? `remoteContainerAction('${itemNode}','${esc(name)}','start')` : `startContainer('${esc(name)}')`;
        const stopAction = isRemote ? `remoteContainerAction('${itemNode}','${esc(name)}','stop')` : `stopContainer('${esc(name)}')`;
        const restartAction = isRemote ? `remoteContainerAction('${itemNode}','${esc(name)}','restart')` : `restartContainer('${esc(name)}')`;
        const deleteAction = isRemote ? `remoteDeleteContainer('${itemNode}','${esc(name)}')` : `deleteContainer('${esc(name)}')`;
        const clickAction = isRemote ? `onclick="event.stopPropagation(); showRemoteContainerDetail('${itemNode}','${esc(name)}')"` : `onclick="event.stopPropagation(); showContainerDetail('${esc(name)}')"`;
        const nodeLabel = c.node_alias || (itemNode === 'local' ? 'local' : itemNode.slice(0, 8));
        const nodeTag = `<span class="status-badge" style="font-size:10px;background:${isRemote ? 'var(--accent)' : 'var(--text-muted)'};color:#fff;margin-left:6px">${esc(nodeLabel)}</span>`;
        return `
        <div class="container-card ${isBuilding ? 'building' : ''}" data-name="${esc(name)}" data-node="${itemNode}" style="${isBuilding ? 'opacity:0.7' : ''}">
            <div class="container-info" ${clickAction} style="cursor:pointer">
                <span class="container-name"><i class="bi bi-box-seam" style="margin-right:6px;color:var(--accent)"></i>${esc(name)}${nodeTag}</span>
                <div class="container-meta">
                    <span><i class="bi bi-image"></i> ${esc(c.template_name || c.image || '-')}</span>
                    <span><i class="bi bi-globe2"></i> ${c.ip_address || 'N/A'}</span>
                    ${c.stats && c.stats.memory_bytes ? `<span><i class="bi bi-memory"></i> ${fmtBytes(c.stats.memory_bytes)}</span>` : ''}
                </div>
            </div>
            <div class="container-actions">
                <span class="status-badge ${statusClass}">${isBuilding ? '<i class="bi bi-arrow-repeat spin"></i> ' : ''}${statusText}</span>
                ${c.status === 'running' || c.status === 'starting'
                    ? `<button class="btn btn-warning btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); ${stopAction}"><i class="bi bi-stop-fill"></i></button>`
                    : `<button class="btn btn-success btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); ${startAction}"><i class="bi bi-play-fill"></i></button>`
                }
                <button class="btn btn-primary btn-sm" ${disabled ? 'disabled' : ''} onclick="event.stopPropagation(); ${restartAction}"><i class="bi bi-arrow-repeat"></i></button>
                <button class="btn btn-danger btn-sm" ${(isRunning || isBuilding) ? 'disabled' : ''} onclick="event.stopPropagation(); ${deleteAction}"><i class="bi bi-trash3"></i></button>
            </div>
        </div>`;
    }).join('');
    list.querySelectorAll('.container-card[data-node="local"]').forEach(card => {
        card.addEventListener('click', () => showContainerDetail(card.dataset.name));
    });
}

function renderImages(images, nodeId) {
    const el = document.getElementById('images-list');
    if (!images || images.length === 0) {
        el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-stack"></i><p>No images available</p></div>';
        return;
    }
    el.innerHTML = images.map(img => {
        const itemNode = img.node || nodeId || 'local';
        const isRemote = itemNode !== 'local';
        const nodeLabel = img.node_alias || (itemNode === 'local' ? 'local' : itemNode.slice(0, 8));
        const nodeTag = (nodeId === 'all') ? `<span class="status-badge" style="font-size:10px;background:${isRemote ? 'var(--accent)' : 'var(--text-muted)'};color:#fff;margin-left:6px">${esc(nodeLabel)}</span>` : '';
        return `
        <div class="image-card">
            <div class="image-icon"><i class="bi bi-hdd-stack"></i></div>
            <div class="image-info">
                <span class="image-name">${esc(img.name)}${nodeTag}</span>
                <span class="image-size">${img.size_human || fmtBytes(img.size || 0)}</span>
            </div>
        </div>`;
    }).join('');
}

function renderLocalImagesForTransfer(images) {
    const el = document.getElementById('local-images-list');
    if (!el) return;
    if (!images || images.length === 0) {
        el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-stack"></i><p>No local images to transfer</p></div>';
        return;
    }
    el.innerHTML = images.map(img => `
        <div class="image-card">
            <div class="image-icon"><i class="bi bi-hdd-stack"></i></div>
            <div class="image-info">
                <span class="image-name">${esc(img.name)}</span>
                <span class="image-size">${img.size_human || fmtBytes(img.size || 0)}</span>
            </div>
            <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); transferImage('${selectedNode}','${esc(img.name)}')" title="Transfer to remote"><i class="bi bi-arrow-right"></i> Send</button>
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
            <option value="template:apache">Apache Static (Web server :9090)</option>
            <option value="template:php">PHP 8.2 (Alpine + PHP :8000)</option>
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

async function renderDashboardNodes() {
    const section = document.getElementById('dash-nodes-section');
    const grid = document.getElementById('dash-nodes-grid');
    const clusterSection = document.getElementById('dash-cluster-section');
    const nodesNavItem = document.querySelector('.nav-item[data-tab="nodes"]');
    try {
        const dashboard = await api('GET', '/system/dashboard');
        const isManager = dashboard.is_manager;
        const nodes = dashboard.nodes || [];
        const cluster = dashboard.cluster;

        // Show/hide Nodes nav tab (manager only)
        if (nodesNavItem) nodesNavItem.style.display = isManager ? '' : 'none';

        // Show/hide nodes section (manager only)
        if (section) section.style.display = (isManager && nodes.length) ? 'block' : 'none';

        // Show/hide cluster section + populate
        if (clusterSection) {
            if (isManager && cluster) {
                clusterSection.style.display = 'block';
                const el = (id) => document.getElementById(id);
                const cores = cluster.cpu_cores || 0;
                const avgCpu = cluster.cpu_percent || 0;
                el('cluster-cpu').textContent = `${avgCpu}%`;
                el('cluster-cpu-label').textContent = `${cores} cores — avg usage`;
                const ramUsed = cluster.ram_used_gb || 0;
                const ramTotal = cluster.ram_total_gb || 0;
                const ramPct = cluster.ram_percent || 0;
                if (ramTotal > 0) {
                    el('cluster-memory').textContent = `${ramUsed.toFixed(1)} / ${ramTotal.toFixed(1)} GB`;
                    el('cluster-memory-label').textContent = `${ramPct.toFixed(0)}% avg usage`;
                } else {
                    el('cluster-memory').textContent = '-';
                    el('cluster-memory-label').textContent = 'Memory';
                }
                const diskUsed = cluster.disk_used_gb || 0;
                const diskTotal = cluster.disk_total_gb || 0;
                const diskPct = cluster.disk_percent || 0;
                if (diskTotal > 0) {
                    el('cluster-disk').textContent = `${diskUsed.toFixed(1)} / ${diskTotal.toFixed(1)} GB`;
                    el('cluster-disk-label').textContent = `${diskPct.toFixed(0)}% avg usage`;
                } else {
                    el('cluster-disk').textContent = '-';
                    el('cluster-disk-label').textContent = 'Disk';
                }
                el('cluster-containers').textContent = `${cluster.containers_running || 0}/${cluster.containers_total || 0}`;
            } else {
                clusterSection.style.display = 'none';
            }
        }

        if (!grid || !nodes.length) return;
        grid.innerHTML = nodes.map(n => {
            const statusColor = n.status === 'online' ? 'var(--success)' : n.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
            const statusLabel = n.status === 'online' ? 'Online' : n.status === 'pending' ? 'Pending' : 'Offline';
            const isOnline = n.status === 'online';
            const cpu = isOnline ? `${Math.round(n.cpu_percent || 0)}%` : '-';
            const mem = isOnline ? `${(n.mem_used_gb || 0).toFixed(1)}/${(n.mem_total_gb || 0).toFixed(1)} GB` : '-';
            const disk = isOnline ? `${Math.round(n.disk_used_gb || 0)}/${Math.round(n.disk_total_gb || 0)} GB` : '-';
            const containers = isOnline ? `${n.containers_running || 0}/${n.containers || 0}` : '-';
            return `<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:10px;padding:12px;cursor:pointer" onclick="document.querySelector('.nav-item[data-tab=\\'nodes\\']')?.click()">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                    <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span>
                    <strong style="color:var(--text-primary);font-size:13px">${esc(n.alias || n.ip || n.id)}</strong>
                    <span style="color:var(--text-muted);font-size:11px">${statusLabel}</span>
                </div>
                <div style="color:var(--text-muted);font-size:11px">CPU ${cpu} &middot; RAM ${mem} &middot; Disk ${disk}</div>
                <div style="color:var(--text-muted);font-size:11px">Containers ${containers} &middot; Stacks ${isOnline ? (n.stacks_count || 0) : '-'}</div>
            </div>`;
        }).join('');
    } catch (e) {
        if (section) section.style.display = 'none';
        if (clusterSection) clusterSection.style.display = 'none';
        if (nodesNavItem) nodesNavItem.style.display = 'none';
    }
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

function initCoreTerminal(nodeId) {
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
        coreTerminal.writeln(`\x1b[1;36m  ANK Core Shell${nodeId && nodeId !== 'local' ? ' — ' + nodeId : ''}\x1b[0m`);
        coreTerminal.writeln('\x1b[90m  Connecting...\x1b[0m\r\n');
        coreTerminal.focus();
        _connectCoreWs(el, nodeId);
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

async function _connectCoreWs(el, nodeId) {
    await detectWsProtocol();
    const isRemote = nodeId && nodeId !== 'local';
    const basePath = isRemote ? `/ws/node-shell/${encodeURIComponent(nodeId)}` : '/ws/shell';
    const url = wsProtocol + '//' + location.host + basePath + '?cols=' + (coreTerminal ? coreTerminal.cols : 80) + '&rows=' + (coreTerminal ? coreTerminal.rows : 24) + '&token=' + encodeURIComponent(ankToken);
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
    if (attempt > 30) {
        loadContainers();
        return;
    }
    try {
        const c = await api('GET', `/containers/${name}`);
        if (c.status === 'building' || c.status === 'starting' || c.status === 'stopping') {
            updateContainerBadge(name, c.status);
            setTimeout(() => pollContainerStatus(name, attempt + 1), 2000);
        } else {
            if (c.package_failure) {
                showApkFailureModal(name, c.package_failure);
            }
            updateContainerBadge(name, c.status);
            updateDetailButtons(name, c.status);
            loadContainers();
            const detailModal = document.getElementById('detail-modal');
            if (detailModal && detailModal.style.display !== 'none' && document.getElementById('detail-name')?.textContent === name) {
                showContainerDetail(name);
            }
        }
    } catch (e) { loadContainers(); }
}

function updateContainerBadge(name, status) {
    const card = document.querySelector(`.container-card[data-name="${name}"]`);
    if (!card) return;
    const badge = card.querySelector('.status-badge');
    if (!badge) return;
    const isBuilding = status === 'building';
    const isFailed = status === 'failed';
    const statusClass = isBuilding ? 'status-building' : isFailed ? 'status-failed' : `status-${status}`;
    const statusText = isBuilding ? 'Building...' : isFailed ? 'Failed' : status === 'starting' ? 'Starting...' : status === 'stopping' ? 'Stopping...' : status;
    badge.className = `status-badge ${statusClass}`;
    badge.innerHTML = `${isBuilding ? '<i class="bi bi-arrow-repeat spin"></i> ' : ''}${statusText}`;
    const isRunning = status === 'running' || status === 'starting';
    card.querySelectorAll('.container-actions button').forEach(btn => {
        if (btn.classList.contains('btn-danger')) {
            btn.disabled = isRunning || isBuilding;
        } else if (btn.classList.contains('btn-warning')) {
            btn.disabled = !isRunning;
        } else if (btn.classList.contains('btn-success')) {
            btn.disabled = isRunning || isBuilding;
        }
    });
}

function updateDetailButtons(name, status) {
    if (!currentContainer || currentContainer.name !== name) return;
    const isRunning = status === 'running' || status === 'starting';
    const isBuilding = status === 'building';
    const isFailed = status === 'failed';
    const stopped = status === 'stopped' || status === 'stopping';
    const isTransient = isBuilding || isFailed || status === 'starting' || status === 'stopping';
    document.getElementById('detail-start').disabled = isRunning || isBuilding || isFailed;
    document.getElementById('detail-stop').disabled = stopped || isBuilding || isFailed;
    document.getElementById('detail-restart').disabled = isTransient;
    document.getElementById('detail-delete').disabled = isRunning || isBuilding;
}

async function startContainer(name) {
    setContainerLoading(name, 'start');
    try { await api('POST', `/containers/${name}/start`); toast(`Starting "${name}"...`, 'info'); pollContainerStatus(name, 0); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}
async function stopContainer(name) {
    setContainerLoading(name, 'stop');
    try { await api('POST', `/containers/${name}/stop`); toast(`Stopping "${name}"...`, 'info'); pollContainerStatus(name, 0); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
}
async function restartContainer(name) {
    setContainerLoading(name, 'restart');
    try { await api('POST', `/containers/${name}/restart`); toast(`Restarting "${name}"...`, 'info'); pollContainerStatus(name, 0); } catch (e) { toast(`Failed: ${e.message}`, 'error'); clearContainerLoading(name); }
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
        document.getElementById('detail-delete').disabled = running || isBuilding;
        document.getElementById('detail-start').onclick = () => startContainer(name);
        document.getElementById('detail-stop').onclick = () => stopContainer(name);
        document.getElementById('detail-restart').onclick = () => restartContainer(name);
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
        document.getElementById('detail-s6').checked = c.s6 || false;
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
    if (!ports.length) { list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No port configured</div>'; return; }
    list.innerHTML = ports.map((p, i) => `
        <div class="port-row">
            <div style="flex:1"><label style="font-size:11px;color:var(--text-muted);margin-bottom:2px;display:block">Port</label><input type="number" placeholder="8080" value="${p.host_port || ''}" data-idx="${i}" data-field="host_port"></div>
            <button type="button" class="btn btn-ghost btn-sm remove-port" data-idx="${i}" style="align-self:flex-end;margin-bottom:6px"><i class="bi bi-x-lg"></i></button>
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
        if (hp && hp.value) {
            const port = parseInt(hp.value) || 0;
            ports.push({ host_port: port, container_port: port, protocol: 'tcp' });
        }
    });
    await btnLoading(btn, async () => {
        try {
            const updateData = {
                autostart: document.getElementById('detail-autostart').checked,
                resources: { memory_limit: document.getElementById('detail-mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('detail-cpu-limit').value) },
                serves_static: document.getElementById('detail-serves-static').checked,
                static_path: document.getElementById('detail-static-path').value || '',
                s6: document.getElementById('detail-s6').checked
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
    const rows = document.querySelectorAll('#port-mappings-list .port-row');
    const ports = [];
    rows.forEach(row => {
        const hp = row.querySelector('[data-field="host_port"]');
        const pr = row.querySelector('[data-field="protocol"]');
        if (hp && hp.value) {
            const port = parseInt(hp.value) || 0;
            ports.push({ host_port: port, container_port: port, protocol: pr ? pr.value : 'tcp' });
        }
    });
    try {
        await api('POST', `/containers/${name}/update`, {
            port_mappings: ports,
            policies: { inter_container_p2p: document.getElementById('detail-p2p').checked, allow_host_access: document.getElementById('detail-host').checked, allow_internet: document.getElementById('detail-internet').checked }
        });
        toast(`Network settings saved for "${name}"`, 'success');
        if (ports.length > 0 && currentContainer.status === 'running') {
            const toastEl = toast(`Port changed. Restart container to apply.`, 'warning', 8000);
            const restartBtn = document.createElement('button');
            restartBtn.className = 'btn btn-xs btn-warning';
            restartBtn.style.cssText = 'margin-left:8px;font-size:11px;';
            restartBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Restart Now';
            restartBtn.onclick = async () => {
                restartBtn.disabled = true;
                restartBtn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Restarting...';
                try { await restartContainer(name); } catch (e) {}
            };
            if (toastEl) toastEl.appendChild(restartBtn);
        }
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
        if (tab.dataset.mtab === 'files' && currentContainer) { fileContainerName = currentContainer.name; showFileExplorer(currentContainer.name); }
        if (tab.dataset.mtab === 'taskmanager' && currentContainer) loadTaskManager();
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

document.getElementById('create-btn').addEventListener('click', () => {
    const targetSel = document.getElementById('container-target-node');
    if (targetSel) targetSel.value = (selectedNode && selectedNode !== 'all') ? selectedNode : 'local';
    showModal('create-modal');
});
document.getElementById('create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const origHTML = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Creating...';
    const name = document.getElementById('container-name').value;
    const imageVal = document.getElementById('container-image').value;
    const nodeId = document.getElementById('container-target-node')?.value || 'local';
    const isRemote = nodeId !== 'local';
    if (imageVal.startsWith('template:')) {
        const templateId = imageVal.replace('template:', '');
        const rootPass = document.getElementById('container-root-password').value || 'ank123';
        try {
            if (isRemote) {
                toast(`Deploying template "${templateId}" as "${name}" on remote...`, 'info');
                await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name, image: templateId, root_password: rootPass });
            } else {
                toast(`Deploying template "${templateId}" as "${name}"...`, 'info');
                await api('POST', '/images/deploy', { template: templateId, name, root_password: rootPass });
                loadContainers();
                pollContainerStatus(name, 0);
            }
            hideModal('create-modal');
            document.getElementById('create-form').reset();
            toast(`Template deployed as "${name}"`, 'success');
            loadContainers();
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
        if (isRemote) {
            await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, data);
        } else {
            await api('POST', '/containers', data);
        }
        hideModal('create-modal');
        document.getElementById('create-form').reset();
        toast(`Container "${data.name}" ${isRemote ? 'creation sent to remote' : 'created'}`, 'success');
        loadContainers();
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
    let defaultPass = 'ank123';
    try {
        const cfg = await api('GET', '/config');
        if (cfg && cfg.default_container_password) defaultPass = cfg.default_container_password;
    } catch(e) {}
    const fields = [
        { id: 'tpl-name', label: 'Container name:', type: 'text', value: name.toLowerCase().replace(/\s+/g, '-') },
        { id: 'tpl-pass', label: 'Root password:', type: 'password', value: defaultPass }
    ];
    let onlineNodes = [];
    try {
        const d = await api('GET', '/system/dashboard');
        onlineNodes = (d.nodes || []).filter(n => n.status === 'online');
    } catch(e) {}
    if (onlineNodes.length > 0) {
        let opts = '<option value="local">Local</option>';
        onlineNodes.forEach(n => { opts += `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`; });
        fields.push({ id: 'tpl-target-node', label: 'Target node:', type: 'select', options: opts });
    }
    const result = await customModal('Deploy ' + name, fields);
    if (!result) return;
    const containerName = result['tpl-name'];
    const rootPass = result['tpl-pass'];
    const nodeId = result['tpl-target-node'] || 'local';
    if (!containerName) { toast('Container name required', 'warning'); return; }
    if (!rootPass || rootPass.length < 4) { toast('Password must be at least 4 characters', 'warning'); return; }
    try {
        if (nodeId !== 'local') {
            toast(`Deploying ${name} as "${containerName}" on remote...`, 'info');
            await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name: containerName, image: id, root_password: rootPass });
            toast(`Container "${containerName}" creation sent to remote node`, 'success');
            setTimeout(() => loadContainers(), 2000);
        } else {
            toast(`Deploying ${name} as "${containerName}"...`, 'info');
            await api('POST', '/images/deploy', { template: id, name: containerName, root_password: rootPass });
            pollContainerStatus(containerName, 0);
            loadAll();
        }
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
            if (selectedNode !== 'local') {
                loadContainers();
                loadImages();
            } else {
                loadContainers();
            }
        } catch (e) { }
    }, refreshSeconds * 1000);
}

document.getElementById('panel-settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const bind = document.getElementById('setting-bind').value;
    const refresh = document.getElementById('setting-refresh').value;
    const autostart = document.getElementById('setting-autostart').checked;
    const nodeName = document.getElementById('setting-node-name')?.value?.trim() || '';
    const defaultPass = document.getElementById('setting-default-pass')?.value?.trim() || '';
    try {
        await api('POST', '/config', { bind_address: bind, refresh_interval: parseInt(refresh), autostart_on_boot: autostart, node_name: nodeName, default_container_password: defaultPass });
        refreshSeconds = parseInt(refresh);
        localStorage.setItem('ank_refresh', refresh);
        startRefreshTimer();
        toast('Server settings saved', 'success');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

async function saveRemoteSSHSettings() {
    const enableRemote = document.getElementById('setting-remote-mgmt')?.checked ?? false;
    const managerIp = document.getElementById('setting-manager-ip')?.value?.trim() || '';
    const sshEnabled = document.getElementById('setting-ssh-enabled')?.checked ?? true;
    const sshPort = document.getElementById('setting-ssh-port')?.value || '2200';
    try {
        await api('POST', '/config', { enable_remote_management: enableRemote, manager_ip: managerIp, ssh_enabled: sshEnabled, ssh_port: parseInt(sshPort) });
        toast('Settings saved', 'success');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function saveSSHSettings() { return saveRemoteSSHSettings(); }
async function saveRemoteSettings() { return saveRemoteSSHSettings(); }

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
        await api('POST', '/system/restart-server');
    } catch (e) { /* server dies before responding, that's expected */ }

    // Show progress overlay
    const overlay = document.createElement('div');
    overlay.id = 'restart-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif';
    const steps = [
        'Stopping running containers...',
        'Restarting ANK server...',
        'Waiting for server to come back...',
        'Done! Redirecting to login...'
    ];
    let currentStep = 0;
    overlay.innerHTML = `<div style="max-width:420px;width:90%;text-align:center">
        <h2 style="font-size:24px;margin:0 0 24px">Restarting Server</h2>
        <div id="restart-steps" style="text-align:left"></div>
        <div style="margin-top:24px;height:4px;background:#1e293b;border-radius:2px;overflow:hidden">
            <div id="restart-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#009639,#22c55e);transition:width 0.5s ease"></div>
        </div>
    </div>`;
    document.body.appendChild(overlay);

    const stepsEl = overlay.querySelector('#restart-steps');
    const bar = overlay.querySelector('#restart-bar');

    function showStep(i) {
        if (i >= steps.length) return;
        currentStep = i;
        stepsEl.innerHTML = steps.map((s, idx) => {
            const color = idx < i ? '#22c55e' : idx === i ? '#fbbf24' : '#475569';
            const icon = idx < i ? '&#10003;' : idx === i ? '<span class="restart-spin">&#8987;</span>' : '&#9675;';
            return `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;color:${color};font-size:14px"><span style="width:20px;text-align:center">${icon}</span>${s}</div>`;
        }).join('');
        bar.style.width = `${((i + 1) / steps.length) * 100}%`;
    }
    showStep(0);

    // Step 1: Wait a bit for containers to stop
    await new Promise(r => setTimeout(r, 3000));
    showStep(1);

    // Step 2: Wait for server to die then come back
    await new Promise(r => setTimeout(r, 2000));
    showStep(2);

    // Step 3: Poll until server responds
    let tries = 0;
    const maxTries = 60;
    while (tries < maxTries) {
        await new Promise(r => setTimeout(r, 2000));
        tries++;
        try {
            const resp = await fetch('/api/health', { method: 'GET', signal: AbortSignal.timeout(3000) });
            if (resp.ok) break;
        } catch (_) {}
    }
    showStep(3);
    await new Promise(r => setTimeout(r, 1000));
    window.location.href = '/login';
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
        const nodeNameEl = document.getElementById('setting-node-name');
        if (nodeNameEl) nodeNameEl.value = cfg.node_name || '';
        const remoteMgmtEl = document.getElementById('setting-remote-mgmt');
        if (remoteMgmtEl) remoteMgmtEl.checked = cfg.enable_remote_management === true;
        const managerIpEl = document.getElementById('setting-manager-ip');
        if (managerIpEl) managerIpEl.value = cfg.manager_ip || '';
        const defaultPassEl = document.getElementById('setting-default-pass');
        if (defaultPassEl) defaultPassEl.value = cfg.default_container_password || '';
        const sshEnabledEl = document.getElementById('setting-ssh-enabled');
        if (sshEnabledEl) sshEnabledEl.checked = cfg.ssh_enabled !== false;
        const sshPortEl = document.getElementById('setting-ssh-port');
        if (sshPortEl) sshPortEl.value = cfg.ssh_port || 2200;
        const sshPortDisplay = document.getElementById('setting-ssh-port-display');
        if (sshPortDisplay) sshPortDisplay.textContent = cfg.ssh_port || 2200;
        const mipGroup = document.getElementById('manager-ip-group');
        if (mipGroup) mipGroup.style.display = remoteMgmtEl?.checked ? 'block' : 'none';
        if (remoteMgmtEl) remoteMgmtEl.addEventListener('change', () => {
            document.getElementById('manager-ip-group').style.display = remoteMgmtEl.checked ? 'block' : 'none';
        });
        const nodeName = cfg.node_name || '';
        document.getElementById('sidebar-title').textContent = nodeName ? `ANK - ${nodeName}` : 'ANK';
        document.getElementById('mt-sidebar-title').textContent = nodeName ? `ANK - ${nodeName}` : 'ANK';
    } catch (e) { }
    try {
        const info = await api('GET', '/system/info');
        document.getElementById('info-rootfs').textContent = info.rootfs_size || '-';
        document.getElementById('info-containers-size').textContent = info.containers_size || '-';
        document.getElementById('info-total-size').textContent = info.total_size || '-';
        document.getElementById('info-device-free').textContent = info.device_free || '-';
        const nodeName = info.node_name || '';
        document.getElementById('sidebar-title').textContent = nodeName ? `ANK - ${nodeName}` : 'ANK';
        document.getElementById('mt-sidebar-title').textContent = nodeName ? `ANK - ${nodeName}` : 'ANK';
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
RUN mkdir -p /opt/cloudreve
RUN curl -L https://github.com/cloudreve/cloudreve/releases/download/4.18.0/cloudreve_4.18.0_linux_armv7.tar.gz | tar xz -C /opt/cloudreve
EXPOSE 5212
WORKDIR /opt/cloudreve
CMD /opt/cloudreve/cloudreve`;

document.getElementById('ankfile-build-btn')?.addEventListener('click', async () => {
    const content = document.getElementById('ankfile-content')?.value?.trim();
    const name = document.getElementById('ankfile-name')?.value?.trim() || 'ank-build';
    if (!content) { toast('Ankfile is empty', 'error'); return; }
    if (!content.includes('FROM')) { toast('Ankfile must have a FROM instruction', 'error'); return; }
    try {
        toast(`Building from Ankfile as "${name}"...`, 'info');
        await api('POST', '/images/ankfile', { content, name });
        loadContainers();
        pollContainerStatus(name, 0);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('ankfile-example-btn')?.addEventListener('click', () => {
    document.getElementById('ankfile-content').value = ANKFILE_EXAMPLE;
    document.getElementById('ankfile-name').value = 'cloudreve';
    toast('Example Ankfile loaded', 'info');
});

/* ============================================================
   Stacks
   ============================================================ */

async function loadStacks() {
    const node = selectedStackNode || 'local';
    try {
        let stacks;
        if (node === 'local') {
            const data = await api('GET', '/stacks');
            stacks = (data.stacks || []).map(s => ({ ...s, node: 'local', node_alias: 'Local' }));
        } else if (node === 'all') {
            const data = await api('GET', '/stacks/all');
            stacks = data.stacks || [];
        } else {
            const remote = await api('GET', `/nodes/${encodeURIComponent(node)}/stacks`);
            stacks = (Array.isArray(remote) ? remote : []).map(s => ({ ...s, node, node_alias: node }));
        }
        const el = document.getElementById('stacks-list');
        if (!el) return;
        if (!stacks.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-stack"></i><p>No stacks yet</p></div>'; return; }
        el.innerHTML = stacks.map(s => {
            const running = (s.containers || []).filter(c => c.status === 'running').length;
            const total = (s.containers || []).length;
            const statusColor = running === total && total > 0 ? 'var(--success)' : running > 0 ? 'var(--warning)' : 'var(--danger)';
            const tpl = s.template === 'ankfile' ? '<i class="bi bi-filetype-json"></i> Ankfile' : esc(s.template || s.image || '');
            const lbPort = s.port || s.lb_port || '-';
            const itemNode = s.node || (node === 'all' ? 'local' : node);
            const isRemote = itemNode !== 'local';
            const nodeLabel = s.node_alias || (itemNode === 'local' ? 'local' : itemNode);
            const nodeTag = (node === 'all') ? `<span class="status-badge" style="font-size:10px;background:${isRemote ? 'var(--accent)' : 'var(--text-muted)'};color:#fff;margin-left:6px">${esc(nodeLabel)}</span>` : '';
            const actions = isRemote
                ? `<span style="color:var(--text-muted);font-size:11px">View only</span>`
                : `<div style="display:flex;gap:6px">
                        <button class="btn btn-sm btn-ghost" onclick="scaleStackUp('${esc(s.name)}')" title="Scale Up"><i class="bi bi-plus-lg"></i></button>
                        <button class="btn btn-sm btn-ghost" onclick="scaleStackDown('${esc(s.name)}')" title="Scale Down"><i class="bi bi-dash-lg"></i></button>
                        <button class="btn btn-sm btn-danger" onclick="deleteStack('${esc(s.name)}')" title="Delete"><i class="bi bi-trash"></i></button>
                    </div>`;
            return `<div class="card-hover" style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                            <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span>
                            <strong style="color:var(--text-primary)">${esc(s.name)}</strong>
                            <span style="color:var(--text-muted);font-size:12px">${tpl}</span>
                            ${nodeTag}
                        </div>
                        <div style="color:var(--text-muted);font-size:12px">${running}/${total} running &middot; LB port ${lbPort}</div>
                    </div>
                    ${actions}
                </div>
            </div>`;
        }).join('');
    } catch (e) { console.error('loadStacks', e); }
}

function showCreateStackModal() { showModal('create-stack-modal'); }

function toggleStackAnkfile() {
    const sel = document.getElementById('stack-image')?.value;
    const sec = document.getElementById('stack-ankfile-section');
    if (sec) sec.style.display = sel === 'ankfile' ? 'block' : 'none';
}

async function createStack() {
    const name = document.getElementById('stack-name')?.value?.trim();
    const image = document.getElementById('stack-image')?.value;
    const instances = parseInt(document.getElementById('stack-instances')?.value || '1');
    const lbPort = parseInt(document.getElementById('stack-lb-port')?.value || '30000');
    const volume = document.getElementById('stack-volume')?.checked;
    const trigger = document.getElementById('stack-trigger')?.value;
    const ankfile = image === 'ankfile' ? (document.getElementById('stack-ankfile')?.value?.trim() || '') : '';
    if (!name) { toast('Stack name required', 'error'); return; }
    if (image === 'ankfile' && !ankfile) { toast('Ankfile content required', 'error'); return; }
    if (ankfile && !ankfile.includes('FROM')) { toast('Ankfile must have a FROM instruction', 'error'); return; }
    try {
        toast(`Creating stack "${name}"...`, 'info');
        await api('POST', '/stacks', { name, template: image, instances, lb_port: lbPort, shared_volume: volume, trigger: trigger === 'none' ? null : trigger, ankfile });
        hideModal('create-stack-modal');
        toast(`Stack "${name}" created`, 'success');
        loadStacks();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function scaleStackUp(name) {
    try { await api('POST', `/stacks/${encodeURIComponent(name)}/scale`, { count: 1 }); toast(`Scaled up "${name}"`, 'success'); loadStacks(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function scaleStackDown(name) {
    try { await api('POST', `/stacks/${encodeURIComponent(name)}/scale-down`, { count: 1 }); toast(`Scaled down "${name}"`, 'success'); loadStacks(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteStack(name) {
    const ok = await confirm(`Delete stack "${name}"? This will stop and remove all containers.`, 'Delete Stack');
    if (!ok) return;
    try { await api('POST', `/stacks/${encodeURIComponent(name)}/delete`); toast(`Stack "${name}" deleted`, 'success'); loadStacks(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ============================================================
   Backups
   ============================================================ */

async function loadBackups() {
    try {
        const data = await api('GET', '/backups');
        const routines = data.routines || [];
        const el = document.getElementById('backups-list');
        if (!el) return;
        if (!routines.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-cloud-arrow-up"></i><p>No backup routines yet</p></div>'; return; }
        el.innerHTML = routines.map(r => {
            const lastRun = r.last_run ? new Date(r.last_run).toLocaleString() : 'Never';
            const statusColor = r.last_status === 'success' ? 'var(--success)' : r.last_status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
            return `<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                            <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span>
                            <strong style="color:var(--text-primary)">${esc(r.name)}</strong>
                        </div>
                        <div style="color:var(--text-muted);font-size:12px">${esc(r.source || '')} &rarr; ${esc(r.remote_host || '')}:${esc(r.remote_path || '')} &middot; Last: ${lastRun}</div>
                        <div style="color:var(--text-muted);font-size:12px;margin-top:4px">Schedule: ${esc(r.schedule || '-')} &middot; Retention: ${r.retention || 30}d</div>
                    </div>
                    <div style="display:flex;gap:6px">
                        <button class="btn btn-sm btn-primary" onclick="executeBackup('${esc(r.id || r.name)}')" title="Run Now"><i class="bi bi-play-fill"></i></button>
                        <button class="btn btn-sm btn-danger" onclick="deleteBackup('${esc(r.id || r.name)}')" title="Delete"><i class="bi bi-trash"></i></button>
                    </div>
                </div>
            </div>`;
        }).join('');
    } catch (e) { console.error('loadBackups', e); }
}

function showCreateBackupModal() { showModal('create-backup-modal'); }

async function createBackup() {
    const name = document.getElementById('backup-name')?.value?.trim();
    if (!name) { toast('Routine name required', 'error'); return; }
    try {
        toast(`Creating routine "${name}"...`, 'info');
        await api('POST', '/backups', {
            name,
            source: document.getElementById('backup-source')?.value || '',
            remote_host: document.getElementById('backup-remote-host')?.value || '',
            remote_path: document.getElementById('backup-remote-path')?.value || '/backups/ank',
            ssh_user: document.getElementById('backup-ssh-user')?.value || 'root',
            ssh_pass: document.getElementById('backup-ssh-pass')?.value || '',
            schedule: document.getElementById('backup-schedule')?.value || '',
            retention: parseInt(document.getElementById('backup-retention')?.value || '30')
        });
        hideModal('create-backup-modal');
        toast(`Routine "${name}" created`, 'success');
        loadBackups();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function executeBackup(id) {
    try { toast('Running backup...', 'info'); const r = await api('POST', `/backups/${encodeURIComponent(id)}/execute`); toast(r.message || 'Backup complete', 'success'); loadBackups(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteBackup(id) {
    const ok = await confirm(`Delete backup routine "${id}"?`, 'Delete Routine');
    if (!ok) return;
    try { await api('POST', `/backups/${encodeURIComponent(id)}/delete`); toast('Routine deleted', 'success'); loadBackups(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function createBackupFromDetail() {
    const containerName = document.getElementById('detail-name')?.textContent || '';
    const source = document.getElementById('detail-backup-source')?.value || '';
    const remoteHost = document.getElementById('detail-backup-host')?.value || '';
    const remotePath = document.getElementById('detail-backup-rpath')?.value || '/backups';
    const pass = document.getElementById('detail-backup-pass')?.value || '';
    const cron = document.getElementById('detail-backup-cron')?.value || '0 2 * * *';
    const retention = parseInt(document.getElementById('detail-backup-retention')?.value || '30');
    if (!source || !remoteHost) { toast('Source and remote host required', 'error'); return; }
    try {
        toast('Creating backup routine...', 'info');
        await api('POST', '/backups', { name: `container-${containerName}`, source, remote_host: remoteHost, remote_path: remotePath, ssh_user: 'root', ssh_pass: pass, schedule: cron, retention });
        toast('Backup routine created', 'success');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ============================================================
   Nodes
   ============================================================ */

async function loadNodes() {
    try {
        const data = await api('GET', '/nodes');
        const nodes = data.nodes || [];
        const el = document.getElementById('nodes-list');
        if (!el) return;

        let managerHtml = '';
        try {
            const mgr = await api('GET', '/nodes/manager');
            if (mgr.manager) {
                const m = mgr.manager;
                const mStatus = m.status === 'online' ? 'Online' : m.status === 'pending' ? 'Pending' : 'Offline';
                const mColor = m.status === 'online' ? 'var(--success)' : m.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
                managerHtml = `<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <div>
                            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                                <span style="width:8px;height:8px;border-radius:50%;background:${mColor};flex-shrink:0"></span>
                                <strong style="color:var(--text-primary)">Managed by: ${esc(m.alias || m.ip)}</strong>
                                <span style="color:var(--text-muted);font-size:12px">${mStatus}</span>
                                <span style="background:var(--accent);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px">MANAGER</span>
                            </div>
                            <div style="color:var(--text-muted);font-size:12px">IP: ${esc(m.ip)}</div>
                        </div>
                        <button class="btn btn-sm btn-danger" onclick="revokeManager()" title="Revoke access"><i class="bi bi-x-circle"></i> Revoke</button>
                    </div>
                </div>`;
            }
        } catch (e) { }

        if (!nodes.length && !managerHtml) { el.innerHTML = '<div class="empty-state"><i class="bi bi-pc-display-horizontal"></i><p>No remote nodes configured</p><p style="color:var(--text-muted);font-size:12px;margin-top:4px">Add a remote ANK device to manage it from here</p></div>'; return; }
        if (!nodes.length && managerHtml) { el.innerHTML = managerHtml; return; }
        el.innerHTML = managerHtml + nodes.map(n => {
            const statusColor = n.status === 'online' ? 'var(--success)' : n.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
            const statusLabel = n.status === 'online' ? 'Online' : n.status === 'pending' ? 'Pending' : 'Offline';
            const roleTag = n.role === 'manager' ? '<span style="background:var(--accent);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px">MANAGER</span>' : '<span style="background:var(--text-muted);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px">MANAGED</span>';
            const managedBy = n.managed_by ? `<div style="color:var(--text-muted);font-size:11px;margin-top:2px">Managed by: ${esc(n.managed_by)}</div>` : '';
            const isOnline = n.status === 'online';
            const cpu = isOnline ? `${Math.round(n.cpu_percent || 0)}%` : '-';
            const ram = isOnline ? `${n.mem_used_gb || 0}/${n.mem_total_gb || 0} GB` : '-';
            const disk = isOnline ? `${Math.round(n.disk_used_gb || 0)}/${Math.round(n.disk_total_gb || 0)} GB` : '-';
            const uptime = isOnline ? fmtUptime(n.uptime_seconds || 0) : '-';
            return `<div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:12px;cursor:pointer" onclick="openNodeDetail('${esc(n.id)}','${esc(n.alias || n.ip)}','${esc(n.status)}')">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                            <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span>
                            <strong style="color:var(--text-primary)">${esc(n.alias || n.ip)}</strong>
                            <span style="color:var(--text-muted);font-size:12px">${statusLabel}</span>
                            ${roleTag}
                        </div>
                        <div style="color:var(--text-muted);font-size:12px">CPU: ${cpu} &middot; RAM: ${ram} &middot; Disk: ${disk} &middot; Uptime: ${uptime}</div>
                        <div style="color:var(--text-muted);font-size:12px;margin-top:2px">Containers: ${isOnline ? (n.containers_total || 0) : 0} &middot; Stacks: ${isOnline ? (n.stacks_count || 0) : 0}</div>
                        ${managedBy}
                    </div>
                    <div style="display:flex;gap:6px" onclick="event.stopPropagation()">
                        <button class="btn btn-sm btn-ghost" onclick="refreshNode('${esc(n.id)}')" title="Refresh"><i class="bi bi-arrow-clockwise"></i></button>
                        <button class="btn btn-sm btn-danger" onclick="deleteNode('${esc(n.id)}')" title="Remove"><i class="bi bi-trash"></i></button>
                    </div>
                </div>
            </div>`;
        }).join('');
        updateNodeSelectors(nodes);
    } catch (e) { console.error('loadNodes', e); }
}

function showAddNodeModal() { showModal('add-node-modal'); }

async function sendPairingRequest() {
    const ip = document.getElementById('node-hostname')?.value?.trim();
    if (!ip) { toast('Panel IP required', 'error'); return; }
    try {
        toast(`Sending pairing request to "${ip}"...`, 'info');
        await api('POST', '/nodes/pairing/send', {
            ip,
            port: parseInt(document.getElementById('node-panel-port')?.value || '8001'),
            user: document.getElementById('node-user')?.value?.trim() || 'admin',
            password: document.getElementById('node-pass')?.value || '',
            alias: document.getElementById('node-alias')?.value?.trim() || ''
        });
        hideModal('add-node-modal');
        toast(`Pairing request sent to "${ip}"`, 'success');
        loadNodes();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function refreshNode(id) {
    try { toast('Refreshing node...', 'info'); await api('POST', `/nodes/${encodeURIComponent(id)}/refresh`); toast('Node refreshed', 'success'); loadNodes(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteNode(id) {
    const ok = await confirm(`Remove this node?`, 'Remove Node');
    if (!ok) return;
    try { await api('POST', `/nodes/${encodeURIComponent(id)}/delete`); toast('Node removed', 'success'); loadNodes(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function revokeManager() {
    const ok = await confirm('Revoke manager access? This node will no longer be managed.', 'Revoke Manager');
    if (!ok) return;
    try { await api('DELETE', '/nodes/manager'); toast('Manager access revoked', 'success'); loadNodes(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* Pairing requests (remote side) */
async function loadPairingRequests() {
    try {
        const data = await api('GET', '/nodes/pairing');
        const requests = data.requests || [];
        const section = document.getElementById('pairing-requests');
        const list = document.getElementById('pairing-list');
        if (!section || !list) return;
        if (!requests.length) { section.style.display = 'none'; return; }
        section.style.display = 'block';
        list.innerHTML = requests.map(r => {
            return `<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border)">
                <div>
                    <div style="display:flex;align-items:center;gap:8px">
                        <i class="bi bi-pc-display-horizontal" style="color:var(--accent);font-size:18px"></i>
                        <strong style="color:var(--text-primary)">${esc(r.manager_name)}</strong>
                        <span style="color:var(--text-muted);font-size:12px">${esc(r.manager_ip || 'unknown IP')}</span>
                    </div>
                    <div style="color:var(--text-muted);font-size:12px;margin-top:2px">${esc(r.device_model || 'Unknown device')}</div>
                </div>
                <div style="display:flex;gap:6px">
                    <button class="btn btn-sm btn-success" onclick="approvePairing('${esc(r.id)}')"><i class="bi bi-check-lg"></i> Approve</button>
                    <button class="btn btn-sm btn-danger" onclick="rejectPairing('${esc(r.id)}')"><i class="bi bi-x-lg"></i> Reject</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) { console.error('loadPairingRequests', e); }
}

async function approvePairing(reqId) {
    try {
        toast('Approving...', 'info');
        await api('POST', `/nodes/pairing/${encodeURIComponent(reqId)}/approve`);
        toast('Pairing approved', 'success');
        loadPairingRequests();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function rejectPairing(reqId) {
    try {
        toast('Rejecting...', 'info');
        await api('POST', `/nodes/pairing/${encodeURIComponent(reqId)}/reject`);
        toast('Pairing rejected', 'success');
        loadPairingRequests();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* Node detail modal (proxy to remote panel) */
function openNodeDetail(nodeId, name, status) {
    document.getElementById('node-detail-name').textContent = name;
    document.getElementById('node-detail-status').textContent = status;
    document.getElementById('node-detail-status').style.color = status === 'online' ? 'var(--success)' : 'var(--danger)';
    document.getElementById('node-detail-loading').style.display = 'block';
    document.getElementById('node-detail-content').style.display = 'none';
    showModal('node-detail-modal');
    loadNodeDetail(nodeId);
}

async function loadNodeDetail(nodeId) {
    const el = document.getElementById('node-detail-content');
    const loading = document.getElementById('node-detail-loading');
    try {
        const [info, containers, images] = await Promise.all([
            api('GET', `/nodes/${encodeURIComponent(nodeId)}/status`).catch(() => ({})),
            api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers`).catch(() => []),
            api('GET', `/nodes/${encodeURIComponent(nodeId)}/images`).catch(() => [])
        ]);
        const dev = info.device_model || info.device || info.hostname || '-';
        const kernel = info.kernel || info.kernel_version || '-';
        const cpu = info.cpu_usage != null ? info.cpu_usage + '%' : (info.cpu || '-');
        const memTotal = info.memory?.total_kb || 0;
        const memAvail = info.memory?.available_kb || 0;
        const memText = memTotal > 0 ? `${fmtBytes((memTotal - memAvail) * 1024)} / ${fmtBytes(memTotal * 1024)}` : '-';
        const disk = info.disk || {};
        const diskText = disk.total ? `${disk.used || '-'} / ${disk.total} GB` : (info.device_free || '-');
        const battery = info.battery;
        const batteryText = (battery != null && battery >= 0) ? battery + '%' : '-';
        const uptime = info.uptime ? fmtUptime(info.uptime) : '-';
        const contArr = Array.isArray(containers) ? containers : [];
        const imgArr = Array.isArray(images) ? images : [];
        const running = contArr.filter(c => c.status === 'running').length;
        const stopped = contArr.filter(c => c.status !== 'running').length;
        el.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-pc"></i> Device</div>
                    <div style="font-weight:600">${esc(dev)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-cpu"></i> CPU</div>
                    <div style="font-weight:600">${esc(cpu)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-memory"></i> Memory</div>
                    <div style="font-weight:600">${esc(memText)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-device-hdd"></i> Disk</div>
                    <div style="font-weight:600">${esc(diskText)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-battery-half"></i> Battery</div>
                    <div style="font-weight:600">${esc(batteryText)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-clock-history"></i> Uptime</div>
                    <div style="font-weight:600">${esc(uptime)}</div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-box-seam"></i> Containers</div>
                    <div style="font-weight:600"><span style="color:var(--success)">${running} running</span> / <span style="color:var(--text-muted)">${stopped} stopped</span></div>
                </div>
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px">
                    <div style="color:var(--text-muted);font-size:11px;margin-bottom:4px"><i class="bi bi-hdd-stack"></i> Images</div>
                    <div style="font-weight:600">${imgArr.length}</div>
                </div>
            </div>
            <div style="margin-bottom:12px">
                <h4 style="margin-bottom:8px;font-size:13px;color:var(--text-muted)"><i class="bi bi-terminal"></i> Kernel</h4>
                <code style="font-size:12px;background:var(--bg-primary);padding:6px 10px;border-radius:6px;display:block">${esc(kernel)}</code>
            </div>
            ${contArr.length > 0 ? `
            <div>
                <h4 style="margin-bottom:8px;font-size:13px;color:var(--text-muted)"><i class="bi bi-box-seam"></i> Containers</h4>
                <div style="display:flex;flex-direction:column;gap:6px">
                    ${contArr.map(c => {
                        const sc = c.status === 'running' ? 'var(--success)' : c.status === 'building' ? 'var(--warning)' : 'var(--text-muted)';
                        return `<div style="display:flex;align-items:center;justify-content:space-between;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
                            <div>
                                <span style="font-weight:600">${esc(c.name || '')}</span>
                                <span style="color:var(--text-muted);font-size:12px;margin-left:8px">${esc(c.image || c.template_name || '')}</span>
                            </div>
                            <div style="display:flex;gap:6px;align-items:center">
                                <span style="color:${sc};font-size:12px;font-weight:600">${esc(c.status || '')}</span>
                                ${c.status === 'running' ? `<button class="btn btn-warning btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','stop')"><i class="bi bi-stop-fill"></i></button>` : `<button class="btn btn-success btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','start')"><i class="bi bi-play-fill"></i></button>`}
                                <button class="btn btn-danger btn-sm" onclick="remoteDeleteContainer('${nodeId}','${esc(c.name)}')"><i class="bi bi-trash3"></i></button>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>` : '<p style="color:var(--text-muted);text-align:center;padding:20px">No containers</p>'}
        `;
        loading.style.display = 'none';
        el.style.display = 'block';
    } catch (e) {
        loading.innerHTML = `<p style="color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> Failed to load node data: ${esc(e.message)}</p>`;
    }
}

/* Node selectors for containers, images, shell */
let selectedNode = 'local';

function updateNodeSelectors(nodes) {
    const onlineNodes = (nodes || []).filter(n => n.status === 'online');
    const hasNodes = onlineNodes.length > 0;
    const unifiedSelectors = ['container-node-selector', 'image-node-selector', 'stack-node-selector'];
    unifiedSelectors.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="all">All Nodes</option><option value="local">Local</option>';
        onlineNodes.forEach(n => {
            const opt = document.createElement('option');
            opt.value = n.id;
            opt.textContent = n.alias || n.ip;
            sel.appendChild(opt);
        });
        // Always default to 'all'
        sel.value = val || 'all';
    });
    if (hasNodes && selectedNode === 'local') {
        selectedNode = 'all';
        loadContainers();
        loadImages();
    }
    const shellSel = document.getElementById('shell-node-selector');
    if (shellSel) {
        const val = shellSel.value;
        shellSel.innerHTML = '<option value="local">Local</option>';
        (nodes || []).filter(n => n.status === 'online').forEach(n => {
            const opt = document.createElement('option');
            opt.value = n.id;
            opt.textContent = n.alias || n.ip;
            shellSel.appendChild(opt);
        });
        shellSel.value = val || 'local';
    }
    const createModalSel = document.getElementById('container-target-node');
    if (createModalSel) {
        const val = createModalSel.value;
        createModalSel.innerHTML = '<option value="local">Local</option>';
        (nodes || []).filter(n => n.status === 'online').forEach(n => {
            const opt = document.createElement('option');
            opt.value = n.id;
            opt.textContent = n.alias || n.ip;
            createModalSel.appendChild(opt);
        });
        createModalSel.value = val || 'local';
    }
}

function onContainerNodeChange() {
    selectedNode = document.getElementById('container-node-selector')?.value || 'local';
    loadContainers();
}

function onImageNodeChange() {
    selectedNode = document.getElementById('image-node-selector')?.value || 'local';
    loadImages();
}

let selectedStackNode = 'local';
function onStackNodeChange() {
    selectedStackNode = document.getElementById('stack-node-selector')?.value || 'local';
    loadStacks();
}

async function loadContainers() {
    if (selectedNode === 'local') {
        try {
            const containers = await api('GET', '/containers');
            renderContainers(containers, 'local');
            renderDashboardContainers(containers);
            populateImageSelect(await api('GET', '/images'));
        } catch (e) {}
        return;
    }
    if (selectedNode === 'all') {
        try {
            const containers = await api('GET', '/containers/all');
            renderContainers(Array.isArray(containers) ? containers : [], 'all');
        } catch (e) {
            renderContainers([], 'all');
        }
        return;
    }
    try {
        const containers = await api('GET', `/nodes/${encodeURIComponent(selectedNode)}/containers`);
        renderContainers(Array.isArray(containers) ? containers : [], selectedNode);
    } catch (e) {
        renderContainers([], selectedNode);
    }
}

async function loadImages() {
    const localCard = document.getElementById('local-images-transfer-card');
    const sectionTitle = document.getElementById('images-section-title');
    if (selectedNode === 'local') {
        if (localCard) localCard.style.display = 'none';
        if (sectionTitle) sectionTitle.textContent = 'Downloaded Images';
        try {
            const images = await api('GET', '/images');
            renderImages(images, 'local');
            populateImageSelect(images);
        } catch (e) {}
        return;
    }
    if (selectedNode === 'all') {
        if (localCard) localCard.style.display = 'none';
        if (sectionTitle) sectionTitle.textContent = 'Images (All Nodes)';
        try {
            const images = await api('GET', '/images/all');
            renderImages(Array.isArray(images) ? images : [], 'all');
        } catch (e) {
            renderImages([], 'all');
        }
        return;
    }
    if (sectionTitle) sectionTitle.textContent = 'Remote Images';
    if (localCard) localCard.style.display = 'block';
    try {
        const remoteImages = await api('GET', `/nodes/${encodeURIComponent(selectedNode)}/images`);
        renderImages(Array.isArray(remoteImages) ? remoteImages : [], selectedNode);
    } catch (e) {
        renderImages([], selectedNode);
    }
    try {
        const localImages = await api('GET', '/images');
        renderLocalImagesForTransfer(localImages);
    } catch (e) {}
}

function onShellNodeChange() {
    const val = document.getElementById('shell-node-selector')?.value || 'local';
    initCoreTerminal(val);
}

/* Node container actions (remote) */
async function remoteContainerAction(nodeId, containerName, action) {
    try {
        await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(containerName)}/${action}`);
        toast(`Container ${action} sent`, 'success');
        setTimeout(() => loadContainers(), 1000);
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function showRemoteContainerDetail(nodeId, name) {
    try {
        const c = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`);
        if (!c) { toast('Container not found', 'warning'); return; }
        const isRunning = c.status === 'running';
        const detail = document.getElementById('detail-panel');
        document.getElementById('detail-title').textContent = c.name || name;
        document.getElementById('detail-status').textContent = c.status || '-';
        document.getElementById('detail-status').className = `status-badge status-${c.status}`;
        document.getElementById('detail-ip').textContent = c.ip_address || '-';
        document.getElementById('detail-image').textContent = c.template_name || c.image || '-';
        document.getElementById('detail-node').textContent = c.node_alias || nodeId.slice(0,8);
        document.getElementById('detail-created').textContent = c.created || '-';
        document.getElementById('detail-ssh-port').textContent = c.ssh_port || '-';
        const actionsEl = document.getElementById('detail-actions');
        actionsEl.innerHTML = `
            ${isRunning
                ? `<button class="btn btn-warning" onclick="remoteContainerAction('${nodeId}','${esc(name)}','stop')"><i class="bi bi-stop-fill"></i> Stop</button>`
                : `<button class="btn btn-success" onclick="remoteContainerAction('${nodeId}','${esc(name)}','start')"><i class="bi bi-play-fill"></i> Start</button>`}
            <button class="btn btn-primary" onclick="remoteContainerAction('${nodeId}','${esc(name)}','restart')"><i class="bi bi-arrow-repeat"></i> Restart</button>
            <button class="btn btn-danger" onclick="remoteDeleteContainer('${nodeId}','${esc(name)}')"><i class="bi bi-trash"></i> Delete</button>
        `;
        document.getElementById('detail-logs').textContent = c.log || '(logs unavailable for remote containers)';
        showPanel('detail');
    } catch (e) { toast(`Failed to load remote container: ${e.message}`, 'error'); }
}

async function remoteDeleteContainer(nodeId, containerName) {
    const ok = await confirmAction('Delete Container', `Delete "${containerName}" on remote node?`);
    if (!ok) return;
    try {
        await api('DELETE', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(containerName)}`);
        toast(`Container delete sent`, 'success');
        loadContainers();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* Node image transfer */
async function transferImage(nodeId, imageName) {
    try {
        toast(`Transferring "${imageName}"...`, 'info');
        await api('POST', `/nodes/${encodeURIComponent(nodeId)}/images/transfer`, { image: imageName });
        toast('Image transferred', 'success');
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

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

/* ============================================================
   Task Manager — Service management for ankd
   ============================================================ */

async function loadTaskManager() {
    if (!currentContainer) return;
    const el = document.getElementById('taskmanager-services');
    el.innerHTML = '<div class="empty-state">Loading...</div>';
    try {
        const data = await api('GET', `/containers/${currentContainer.name}/services`);
        const services = data.services || [];
        if (services.length === 0) {
            el.innerHTML = '<div class="empty-state"><i class="bi bi-inbox" style="font-size:24px; opacity:0.3;"></i><br>No services configured</div>';
            return;
        }
        let html = '';
        for (const svc of services) {
            const isRunning = svc.status === 'running';
            const statusColor = isRunning ? 'var(--success)' : 'var(--text-muted)';
            const statusBg = isRunning ? 'rgba(34,197,94,0.1)' : 'rgba(255,255,255,0.03)';
            const enabledBadge = svc.enabled
                ? '<span style="color:var(--success);font-size:11px;">ON</span>'
                : '<span style="color:var(--text-muted);font-size:11px;">OFF</span>';

            html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;background:${statusBg};">`;
            // Left: name + status
            html += `<div style="display:flex;align-items:center;gap:10px;">`;
            html += `<div style="width:8px;height:8px;border-radius:50%;background:${statusColor};${isRunning ? 'box-shadow:0 0 6px ' + statusColor : ''}"></div>`;
            html += `<div>`;
            html += `<div style="font-weight:600;font-size:13px;">${svc.name} ${enabledBadge}</div>`;
            html += `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${svc.cmd || 'no command'}</div>`;
            html += `</div></div>`;
            // Right: actions
            html += `<div style="display:flex;gap:4px;align-items:center;">`;
            html += `<button class="btn btn-xs btn-ghost" onclick="taskManagerViewLog('${svc.name}')" title="View Log"><i class="bi bi-journal-text"></i></button>`;
            if (isRunning) {
                html += `<button class="btn btn-xs btn-warning" onclick="taskManagerServiceAction('${svc.name}','stop')" title="Stop"><i class="bi bi-stop-fill"></i></button>`;
                html += `<button class="btn btn-xs btn-ghost" onclick="taskManagerServiceAction('${svc.name}','restart')" title="Restart"><i class="bi bi-arrow-clockwise"></i></button>`;
            } else {
                html += `<button class="btn btn-xs btn-success" onclick="taskManagerServiceAction('${svc.name}','start')" title="Start"><i class="bi bi-play-fill"></i></button>`;
            }
            if (svc.enabled) {
                html += `<button class="btn btn-xs btn-ghost" onclick="taskManagerServiceAction('${svc.name}','disable')" title="Disable"><i class="bi bi-pause-circle"></i></button>`;
            } else {
                html += `<button class="btn btn-xs btn-ghost" onclick="taskManagerServiceAction('${svc.name}','enable')" title="Enable"><i class="bi bi-play-circle"></i></button>`;
            }
            html += `<button class="btn btn-xs btn-ghost" onclick="taskManagerServiceAction('${svc.name}','delete')" title="Delete" style="color:var(--danger);"><i class="bi bi-trash3"></i></button>`;
            html += `</div></div>`;
        }
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = `<div class="empty-state">Failed to load services: ${e.message}</div>`;
    }
}

async function taskManagerServiceAction(service, action) {
    if (!currentContainer) return;
    if (action === 'delete' && !confirm(`Delete service "${service}"?`)) return;
    try {
        if (action === 'delete') {
            await api('DELETE', `/containers/${currentContainer.name}/services/${service}`);
            toast(`Service "${service}" deleted`, 'success');
        } else {
            await api('POST', `/containers/${currentContainer.name}/services/${service}/${action}`);
            toast(`Service "${service}" ${action}ed`, 'success');
        }
        setTimeout(loadTaskManager, 500);
    } catch (e) {
        toast(`Failed: ${e.message}`, 'error');
    }
}

async function taskManagerViewLog(service) {
    if (!currentContainer) return;
    try {
        const data = await api('GET', `/containers/${currentContainer.name}/services/${service}/logs?lines=50`);
        const logs = data.logs || 'No logs for this service';
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = `
            <div style="background:var(--bg-primary);border:1px solid var(--border);border-radius:12px;width:90%;max-width:700px;max-height:80vh;display:flex;flex-direction:column;">
                <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);">
                    <h4 style="margin:0;font-size:14px;"><i class="bi bi-journal-text"></i> ${service} — Logs</h4>
                    <button class="btn btn-xs btn-ghost" onclick="this.closest('div[style*=fixed]').remove()"><i class="bi bi-x-lg"></i></button>
                </div>
                <pre style="margin:0;padding:16px;overflow:auto;flex:1;font-size:12px;line-height:1.5;color:var(--text-primary);background:transparent;">${logs.replace(/</g, '&lt;')}</pre>
            </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    } catch (e) {
        toast(`Failed to load log: ${e.message}`, 'error');
    }
}

function taskManagerAddService() {
    document.getElementById('taskmanager-add-form').style.display = 'block';
    document.getElementById('tm-svc-name').value = '';
    document.getElementById('tm-svc-cmd').value = '';
    document.getElementById('tm-svc-name').focus();
}

async function taskManagerSaveService() {
    if (!currentContainer) return;
    const name = document.getElementById('tm-svc-name').value.trim();
    const cmd = document.getElementById('tm-svc-cmd').value.trim();
    const policy = document.getElementById('tm-svc-policy').value;
    const enabled = document.getElementById('tm-svc-enabled').checked;
    if (!name || !cmd) { toast('Name and command required', 'error'); return; }
    try {
        await api('POST', `/containers/${currentContainer.name}/services`, { name, cmd, restart_policy: policy, enabled });
        toast(`Service "${name}" created`, 'success');
        document.getElementById('taskmanager-add-form').style.display = 'none';
        loadTaskManager();
    } catch (e) {
        toast(`Failed: ${e.message}`, 'error');
    }
}