const API = '/api';
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

async function btnLoading(btn, fn) {
  if (!btn) return fn();
  const orig = btn.innerHTML;
  const origDisabled = btn.disabled;
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> ' + orig.replace(/<[^>]+>/g, '').trim();
  try { return await fn(); } finally { btn.disabled = origDisabled; btn.innerHTML = orig; }
}

function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : ''; }
function fmtBytes(b) { if (!b || b === 0) return '0 B'; const k = 1024, s = ['B','KB','MB','GB']; const i = Math.floor(Math.log(b)/Math.log(k)); return (b/Math.pow(k,i)).toFixed(1)+' '+s[i]; }
function fmtUptime(sec) { const d = Math.floor(sec/86400), h = Math.floor((sec%86400)/3600), m = Math.floor((sec%3600)/60); if (d>0) return `${d}d ${h}h`; if (h>0) return `${h}h ${m}m`; return `${m}m`; }
function copyText(text) { if (navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(text); else { const ta=document.createElement('textarea'); ta.value=text; ta.style.cssText='position:fixed;opacity:0'; document.body.appendChild(ta); ta.select(); try{document.execCommand('copy')}catch(e){} document.body.removeChild(ta); } }

function toast(msg, type = 'info', duration = 4000) {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  const icons = { success: 'bi-check-circle-fill', error: 'bi-exclamation-circle-fill', info: 'bi-info-circle-fill', warning: 'bi-exclamation-triangle-fill' };
  el.className = `toast ${type}`;
  el.innerHTML = `<i class="bi ${icons[type]||icons.info}"></i><span>${msg}</span><div class="toast-bar"></div>`;
  c.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; el.style.transform='translateX(100%)'; setTimeout(()=>el.remove(),300); }, duration);
  return el;
}

async function confirmAction(title, message) {
  return new Promise(resolve => {
    openModal(title, `
      <p style="margin-bottom:20px;color:var(--text-secondary)">${esc(message)}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" id="_confirm-cancel">Cancel</button>
        <button class="btn btn-danger" id="_confirm-ok">Confirm</button>
      </div>
    `);
    document.getElementById('_confirm-ok').onclick = () => { closeModal(); resolve(true); };
    document.getElementById('_confirm-cancel').onclick = () => { closeModal(); resolve(false); };
  });
}

async function inputModal(title, message, defaultValue = '') {
  return new Promise(resolve => {
    openModal(title, `
      <p style="margin-bottom:12px;color:var(--text-secondary)">${esc(message)}</p>
      <input class="form-input" id="_input-field" value="${esc(defaultValue)}" autofocus>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
        <button class="btn btn-secondary" id="_input-cancel">Cancel</button>
        <button class="btn btn-primary" id="_input-ok">OK</button>
      </div>
    `);
    const field = document.getElementById('_input-field');
    setTimeout(() => field.focus(), 50);
    const submit = () => { const v = field.value.trim(); closeModal(); resolve(v || null); };
    document.getElementById('_input-ok').onclick = submit;
    document.getElementById('_input-cancel').onclick = () => { closeModal(); resolve(null); };
    field.onkeydown = e => { if (e.key === 'Enter') submit(); };
  });
}

async function customModal(title, fields) {
  return new Promise(resolve => {
    let html = fields.map(f => {
      if (f.type === 'select') return `<div class="form-group"><label class="form-label">${esc(f.label)}</label><select class="form-select" id="_cm-${f.id}">${f.options}</select></div>`;
      if (f.type === 'textarea') return `<div class="form-group"><label class="form-label">${esc(f.label)}</label><textarea class="form-input" id="_cm-${f.id}" rows="6" placeholder="${esc(f.placeholder||f.label)}">${esc(f.value||'')}</textarea></div>`;
      return `<div class="form-group"><label class="form-label">${esc(f.label)}</label><input class="form-input" id="_cm-${f.id}" type="${f.type||'text'}" value="${esc(f.value||'')}" placeholder="${esc(f.label)}"></div>`;
    }).join('');
    html += `<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn btn-secondary" id="_cm-cancel">Cancel</button><button class="btn btn-primary" id="_cm-ok">OK</button></div>`;
    openModal(title, html);
    const first = document.querySelector('[id^="_cm-"]');
    if (first) setTimeout(() => first.focus(), 50);
    document.getElementById('_cm-ok').onclick = () => {
      const result = {};
      let allFilled = true;
      fields.forEach(f => { result[f.id] = document.getElementById(`_cm-${f.id}`).value.trim(); if (!result[f.id]) allFilled = false; });
      closeModal();
      resolve(allFilled ? result : null);
    };
    document.getElementById('_cm-cancel').onclick = () => { closeModal(); resolve(null); };
  });
}

/* ═══════ MODAL ═══════ */
function openModal(title, bodyHtml) {
  const overlay = document.getElementById('modal-overlay');
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-footer').innerHTML = '';
  overlay.classList.add('active');
}
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('active');
}
function closeModalById(id) {
  document.getElementById(id).classList.remove('active');
}
document.getElementById('modal-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });
document.getElementById('create-modal-overlay')?.addEventListener('click', e => { if (e.target === e.currentTarget) closeCreateModal(); });
document.getElementById('network-modal-overlay')?.addEventListener('click', e => { if (e.target === e.currentTarget) closeModalById('network-modal-overlay'); });
document.getElementById('stack-modal-overlay')?.addEventListener('click', e => { if (e.target === e.currentTarget) closeModalById('stack-modal-overlay'); });
document.getElementById('backup-modal-overlay')?.addEventListener('click', e => { if (e.target === e.currentTarget) closeModalById('backup-modal-overlay'); });
document.getElementById('upload-modal-overlay')?.addEventListener('click', e => { if (e.target === e.currentTarget) closeModalById('upload-modal-overlay'); });
function closeCreateModal() { closeModalById('create-modal-overlay'); const f = document.getElementById('create-form'); if (f) f.reset(); }

/* ═══════ NAVIGATION ═══════ */
function navigateTo(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.notch-item, .mobile-bar-item').forEach(i => i.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');
  document.querySelectorAll(`[data-page="${page}"]`).forEach(i => i.classList.add('active'));
  document.getElementById('mobile-expanded')?.classList.remove('active');
  if (page === 'dashboard') loadDashboard();
  if (page === 'containers') loadContainers();
  if (page === 'images') loadImages();
  if (page === 'nodes') { loadNodes(); loadPairingRequests(); }
  if (page === 'stacks') loadStacks();
  if (page === 'backups') loadBackups();
  if (page === 'networks') loadNetworks();
  if (page === 'logs') { logsOffset = 0; loadLogs(false); startLogsPoll(); }
  if (page === 'settings') loadSettings();
  if (page === 'shell') initCoreTerminal();
  if (page !== 'logs') stopLogsPoll();
}

document.querySelectorAll('.notch-item, .mobile-bar-item').forEach(item => {
  item.addEventListener('click', e => { e.preventDefault(); navigateTo(item.dataset.page); });
});
document.getElementById('mobile-more-btn')?.addEventListener('click', () => {
  document.getElementById('mobile-expanded')?.classList.toggle('active');
});

/* ═══════ LOGIN ═══════ */
const loginUsername = document.getElementById('login-username');
const loginPassGroup = document.getElementById('login-pass-group');
const loginPassword = document.getElementById('login-password');

loginUsername.addEventListener('input', () => {
  if (loginUsername.value.length > 0 && !loginPassGroup.classList.contains('hidden')) return;
  if (loginUsername.value.length > 0) loginPassGroup.classList.remove('hidden');
});
loginUsername.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (loginUsername.value.length > 0) {
      if (loginPassGroup.classList.contains('hidden')) loginPassGroup.classList.remove('hidden');
      else loginPassword.focus();
    }
  }
});

document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  if (loginPassGroup.classList.contains('hidden')) return;
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
      body: JSON.stringify({ username: loginUsername.value, password: loginPassword.value })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Login failed');
    ankToken = data.token;
    localStorage.setItem('ank_token', ankToken);
    isLoggedIn = true;
    showApp();
  } catch (e) { toast(e.message || 'Invalid credentials', 'error'); }
});

function logout() {
  ankToken = '';
  localStorage.removeItem('ank_token');
  isLoggedIn = false;
  document.getElementById('login-screen').style.display = '';
  document.getElementById('app').classList.add('hidden');
}

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app').classList.remove('hidden');
  loadDashboard();
}

/* ═══════ DASHBOARD ═══════ */
async function loadDashboard() {
  try {
    const [status, info] = await Promise.all([api('GET', '/status'), api('GET', '/system/info')]);
    animateCounter('stat-running', status.containers_running || 0);
    animateCounter('stat-stopped', status.containers_stopped || 0);
    animateCounter('stat-total', status.containers_total || 0);
    document.getElementById('dash-device-name').textContent = info.device || 'ANK Device';
    document.getElementById('dash-uptime').textContent = 'Uptime: ' + fmtUptime(status.uptime || 0);
    document.getElementById('info-device').textContent = info.device || '-';
    document.getElementById('info-kernel').textContent = info.kernel || '-';
    const bat = info.battery;
    document.getElementById('info-battery').textContent = (bat != null && bat >= 0) ? bat + '%' : '-';
    document.getElementById('info-subnet').textContent = (info.network?.subnet || '-') + '/24';
    const cpuPct = info.cpu_usage != null ? Math.round(info.cpu_usage) : 0;
    document.getElementById('cpu-cores').textContent = (info.cpu_cores || 0) > 0 ? info.cpu_cores + ' cores' : '';
    const memT = info.memory?.total_kb || 0;
    const memA = info.memory?.available_kb || 0;
    const memUsed = memT - memA;
    const memPct = memT > 0 ? Math.round(memUsed / memT * 100) : 0;
    document.getElementById('ram-detail').textContent = memT > 0 ? `${fmtBytes(memUsed * 1024)} / ${fmtBytes(memT * 1024)}` : '';
    const disk = status.disk || {};
    const diskTotal = disk.total || 0;
    const diskUsedNum = disk.used_num || 0;
    const diskPct = diskTotal > 0 ? Math.round(diskUsedNum / diskTotal * 100) : 0;
    document.getElementById('disk-detail').textContent = diskTotal > 0 ? `${disk.used || '-'} / ${diskTotal} GB` : '';
    setGaugeDash('gauge-cpu', cpuPct, 'gauge-cpu-text', 175.9);
    setGaugeDash('gauge-ram', memPct, 'gauge-ram-text', 175.9);
    setGaugeDash('gauge-disk', diskPct, 'gauge-disk-text', 175.9);
    renderDashboardContainers();
    renderDashboardNodes();
  } catch (e) { console.error('Dashboard load failed:', e); }
}

function setGaugeDash(id, pct, textId, circ) {
  const circle = document.getElementById(id);
  const text = document.getElementById(textId);
  if (!circle || !text) return;
  circle.style.strokeDashoffset = circ - (circ * pct / 100);
  text.textContent = pct + '%';
}

function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = parseInt(el.textContent) || 0;
  if (start === target) { el.textContent = target; return; }
  const duration = 600, startTime = performance.now();
  function tick(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    el.textContent = Math.round(start + (target - start) * (1 - Math.pow(1 - progress, 3)));
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

async function renderDashboardContainers() {
  const el = document.getElementById('dashboard-containers');
  if (!el) return;
  try {
    const containers = await api('GET', '/containers/all');
    if (!containers || !containers.length) { el.innerHTML = '<div class="empty-state" style="padding:30px"><p>No containers yet</p></div>'; return; }
    el.innerHTML = containers.slice(0, 8).map(c => {
      const s = c.status;
      const color = s === 'running' ? 'var(--success)' : s === 'building' ? 'var(--warning)' : 'var(--text-muted)';
      return `<div class="dash-container-row" onclick="navigateTo('containers');setTimeout(()=>showContainerDetail('${esc(c.name)}','${c.node||'local'}'),100)">
        <span class="dcr-dot" style="background:${color}"></span>
        <span class="dcr-name">${esc(c.name)}</span>
        <span class="badge badge-neutral" style="font-size:9px">${s}</span>
      </div>`;
    }).join('');
    if (containers.length > 8) el.innerHTML += `<div style="text-align:center;padding:8px;font-size:11px;color:var(--text-muted)">+${containers.length-8} more</div>`;
  } catch (e) { el.innerHTML = '<div class="empty-state" style="padding:20px"><p>Failed to load</p></div>'; }
}

async function renderDashboardNodes() {
  const card = document.getElementById('cluster-card');
  const info = document.getElementById('cluster-info');
  if (!card || !info) return;
  try {
    const dashboard = await api('GET', '/system/dashboard');
    if (!dashboard.is_manager || !dashboard.nodes || !dashboard.nodes.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    info.innerHTML = dashboard.nodes.map(n => {
      const color = n.status === 'online' ? 'var(--success)' : 'var(--danger)';
      return `<div class="dash-cluster-row">
        <span class="dcl-dot" style="background:${color}"></span>
        <span class="dcl-name">${esc(n.alias||n.ip)}</span>
        <span class="dcl-stats">CPU ${Math.round(n.cpu_percent||0)}% · RAM ${(n.mem_used_gb||0).toFixed(1)}/${(n.mem_total_gb||0).toFixed(1)}GB</span>
      </div>`;
    }).join('');
  } catch (e) { card.style.display = 'none'; }
}

/* ═══════ CONTAINERS ═══════ */
async function loadContainers() {
  const el = document.getElementById('containers-list');
  if (!el) return;
  el.innerHTML = '<div class="skeleton skeleton-card"></div>';
  try {
    const containers = await api('GET', '/containers/all');
    renderContainers(Array.isArray(containers) ? containers : [], 'all');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function renderContainers(containers, nodeId) {
  const el = document.getElementById('containers-list');
  if (!el) return;
  if (!containers.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-box-seam"></i><h3>No containers</h3><p>Create your first container</p></div>'; return; }
  el.innerHTML = containers.map(c => {
    const name = c.name || '';
    const node = c.node || 'local';
    const s = c.status;
    const bc = s === 'running' ? 'badge-success' : s === 'building' ? 'badge-warning' : s === 'failed' ? 'badge-danger' : 'badge-neutral';
    const nodeTag = node !== 'local' ? `<span class="badge badge-info" style="font-size:9px">${esc(c.node_alias||node.slice(0,6))}</span>` : '';
    const mem = c.stats && c.stats.memory_bytes ? fmtBytes(c.stats.memory_bytes) : '';
    return `<div class="split-list-card" data-name="${esc(name)}" onclick="showContainerDetail('${esc(name)}','${node}')">
      <div class="slc-top"><span class="slc-name"><i class="bi bi-box-seam" style="color:var(--accent)"></i>${esc(name)}${nodeTag}</span><span class="badge ${bc}" style="font-size:10px">${s}</span></div>
      <div class="slc-meta"><span><i class="bi bi-image"></i> ${esc(c.template_name||c.image||'-')}</span><span><i class="bi bi-globe2"></i> ${esc(c.ip_address||'N/A')}</span>${mem?`<span>${mem}</span>`:''}</div>
    </div>`;
  }).join('');
}

let selectedContainerName = null;
let currentContainer = null;
let detailLogTimer = null;

async function showContainerDetail(name, nodeId) {
  if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; }
  selectedContainerName = name;
  document.querySelectorAll('#containers-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.name === name));
  const el = document.getElementById('container-detail');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)"><i class="bi bi-arrow-repeat spin" style="font-size:24px"></i><p style="margin-top:8px">Loading...</p></div>';
  try {
    const isRemote = nodeId && nodeId !== 'local';
    let c, logs;
    if (isRemote) {
      c = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`);
      logs = { logs: c.log || '' };
    } else {
      [c, logs] = await Promise.all([api('GET', `/containers/${name}`), api('GET', `/containers/${name}/logs`).catch(()=>({logs:''}))]);
    }
    currentContainer = c;
    currentContainer._nodeId = nodeId || 'local';
    const s = c.status;
    const bc = s === 'running' ? 'badge-success' : s === 'building' ? 'badge-warning' : s === 'failed' ? 'badge-danger' : 'badge-neutral';
    const isBuilding = s === 'building';
    const isFailed = s === 'failed';
    const isTransient = isBuilding || isFailed || s === 'starting' || s === 'stopping';
    const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
    const host = location.hostname || 'localhost';
    const sshHint = (c.ssh_port && s === 'running') ? `<div class="ssh-hint"><div class="ssh-hint-header"><i class="bi bi-terminal"></i> SSH</div><code class="ssh-hint-cmd">ssh root@${host} -p ${c.ssh_port}</code><button class="btn btn-sm btn-ghost" onclick="copyText(this.previousElementSibling.textContent);toast('Copied!','success')"><i class="bi bi-clipboard"></i></button></div>` : '';

    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-box-seam" style="color:var(--accent)"></i>${esc(c.name)} <span class="badge ${bc}" style="font-size:11px">${s}</span></h2>
        <div class="sr-actions">
          ${isRemote ? `
            ${s==='running'||s==='starting'?`<button class="btn btn-secondary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','stop')"><i class="bi bi-stop-fill"></i> Stop</button>`:`<button class="btn btn-success btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','start')"><i class="bi bi-play-fill"></i> Start</button>`}
            <button class="btn btn-primary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','restart')"><i class="bi bi-arrow-repeat"></i></button>
            <button class="btn btn-danger btn-sm" onclick="remoteDeleteContainer('${nodeId}','${esc(name)}')"><i class="bi bi-trash3"></i></button>
          ` : `
            ${s==='running'||s==='starting'?`<button class="btn btn-secondary btn-sm" id="detail-stop" onclick="stopContainer('${esc(name)}')"><i class="bi bi-stop-fill"></i> Stop</button>`:`<button class="btn btn-success btn-sm" id="detail-start" onclick="startContainer('${esc(name)}')"><i class="bi bi-play-fill"></i> Start</button>`}
            <button class="btn btn-primary btn-sm" id="detail-restart" onclick="restartContainer('${esc(name)}')"><i class="bi bi-arrow-repeat"></i></button>
            <button class="btn btn-danger btn-sm" id="detail-delete" onclick="deleteContainer('${esc(name)}')"><i class="bi bi-trash3"></i></button>
          `}
        </div>
      </div>

      <div class="detail-tabs">
        <div class="detail-tab active" data-dtab="overview"><i class="bi bi-info-circle"></i> Overview</div>
        <div class="detail-tab" data-dtab="terminal"><i class="bi bi-terminal"></i> Terminal</div>
        <div class="detail-tab" data-dtab="files"><i class="bi bi-folder2-open"></i> Files</div>
        <div class="detail-tab" data-dtab="network"><i class="bi bi-hdd-network"></i> Networks</div>
        <div class="detail-tab" data-dtab="settings"><i class="bi bi-gear"></i> Settings</div>
        <div class="detail-tab" data-dtab="services"><i class="bi bi-cpu"></i> Services</div>
      </div>

      <div class="detail-tab-content active" id="dtab-overview">
        ${sshHint}
        <div class="detail-stats">
          <div class="detail-stat"><span class="detail-stat-label">IP Address</span><span class="detail-stat-value">${esc(c.ip_address||'-')}</span></div>
          <div class="detail-stat"><span class="detail-stat-label">Image</span><span class="detail-stat-value">${esc(c.template_name||c.image||'-')}</span></div>
          ${isRemote?`<div class="detail-stat"><span class="detail-stat-label">Node</span><span class="detail-stat-value">${esc(c.node_alias||nodeId.slice(0,8))}</span></div>`:''}
          <div class="detail-stat"><span class="detail-stat-label">Mode</span><span class="detail-stat-value">${esc(c.mode||'-')}</span></div>
          <div class="detail-stat"><span class="detail-stat-label">PID</span><span class="detail-stat-value">${c.pid||'-'}</span></div>
          <div class="detail-stat"><span class="detail-stat-label">Memory</span><span class="detail-stat-value">${esc(c.resources?.memory_limit||'-')}</span></div>
          <div class="detail-stat"><span class="detail-stat-label">CPU</span><span class="detail-stat-value">${c.resources?.cpu_limit_percent?c.resources.cpu_limit_percent+'%':'-'}</span></div>
          <div class="detail-stat"><span class="detail-stat-label">Ports</span><span class="detail-stat-value">${esc((c.port_mappings||[]).map(p=>p.host_port).join(', ')||'-')}</span></div>
        </div>
        <div class="detail-logs">
          <div class="card-header"><h4><i class="bi bi-journal-text"></i> Logs</h4></div>
          <pre class="log-output" id="detail-log-output">${esc(logText||'No logs')}</pre>
        </div>
      </div>

      <div class="detail-tab-content" id="dtab-terminal">
        <div id="container-terminal" style="width:100%;min-height:400px"></div>
      </div>

      <div class="detail-tab-content" id="dtab-files">
        <div class="file-explorer">
          <div class="file-toolbar">
            <div id="file-breadcrumbs" class="file-breadcrumbs"><span class="breadcrumb-item" data-path="/">/</span></div>
            <div class="file-actions">
              <button id="file-btn-new" class="btn btn-sm btn-ghost" title="New File"><i class="bi bi-file-earmark-plus"></i></button>
              <button id="file-btn-mkdir" class="btn btn-sm btn-ghost" title="New Folder"><i class="bi bi-folder-plus"></i></button>
              <button id="file-btn-upload" class="btn btn-sm btn-ghost" title="Upload"><i class="bi bi-upload"></i></button>
              <button id="file-btn-refresh" class="btn btn-sm btn-ghost" title="Refresh"><i class="bi bi-arrow-clockwise"></i></button>
            </div>
          </div>
          <div id="file-list" class="file-list"><div class="file-empty">Loading...</div></div>
          <input type="file" id="file-upload-input" class="hidden" multiple>
        </div>
        <div id="file-editor" class="file-editor hidden">
          <div class="file-editor-header">
            <span id="file-editor-name" class="file-editor-name">-</span>
            <div class="file-editor-actions">
              <button id="file-btn-save" class="btn btn-sm btn-success"><i class="bi bi-check-lg"></i> Save</button>
              <button id="file-btn-close-editor" class="btn btn-sm btn-ghost"><i class="bi bi-x-lg"></i> Close</button>
            </div>
          </div>
          <textarea id="file-editor-content" class="file-editor-content" spellcheck="false"></textarea>
        </div>
      </div>

      <div class="detail-tab-content" id="dtab-network">
        <form id="detail-network-form">
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-info-circle"></i> Info</div>
            <div class="form-group"><label class="form-label">Container IP</label><input type="text" class="form-input" id="detail-container-ip" readonly></div>
            <div class="form-group"><label class="form-label">Subnet</label><input type="text" class="form-input" id="detail-container-subnet" readonly><small class="form-hint">Read-only — configured in global network settings</small></div>
          </div>
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-plug"></i> Port Mappings</div>
            <div id="port-mappings-list"></div>
            <button type="button" id="add-port-btn" class="btn btn-ghost btn-sm"><i class="bi bi-plus-lg"></i> Add Port</button>
          </div>
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-shield-lock"></i> Policies</div>
            <div class="checkbox-group">
              <label class="checkbox-label"><input type="checkbox" id="detail-p2p" style="accent-color:var(--accent)"><i class="bi bi-diagram-3"></i> Inter-container P2P</label>
              <label class="checkbox-label"><input type="checkbox" id="detail-host" style="accent-color:var(--accent)"><i class="bi bi-phone"></i> Host Access</label>
              <label class="checkbox-label"><input type="checkbox" id="detail-internet" style="accent-color:var(--accent)"><i class="bi bi-globe"></i> Internet Access</label>
            </div>
          </div>
          <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Save Network</button>
        </form>
      </div>

      <div class="detail-tab-content" id="dtab-settings">
        <form id="detail-settings-form">
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-gear"></i> General</div>
            <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="detail-autostart" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-power" style="color:var(--accent)"></i> Autostart on boot</label></div>
            <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="detail-s6" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-box-seam" style="color:var(--accent)"></i> Enable s6 supervisor</label><small class="form-hint">Start s6-overlay for additional custom services</small></div>
          </div>
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-key"></i> Access</div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">Root Password</label><input type="password" class="form-input" id="detail-root-password" placeholder="min 4 chars" minlength="4"></div>
              <div class="form-group"><label class="form-label">SSH Port</label><input type="number" class="form-input" id="detail-ssh-port" placeholder="auto" min="1024" max="65535" readonly></div>
            </div>
          </div>
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-cpu"></i> Resources</div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">Memory Limit</label><select class="form-select" id="detail-mem-limit"><option value="128M">128 MB</option><option value="256M">256 MB</option><option value="512M">512 MB</option><option value="1G">1 GB</option></select></div>
              <div class="form-group"><label class="form-label">CPU %</label><input type="number" class="form-input" id="detail-cpu-limit" value="50" min="1" max="100"></div>
            </div>
          </div>
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-folder2"></i> Services</div>
            <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="detail-serves-static" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-globe2" style="color:var(--accent)"></i> Serves Static Files</label></div>
            <div class="form-group"><label class="form-label">Static Files Path</label><input type="text" class="form-input" id="detail-static-path" placeholder="/var/www/html"><small class="form-hint">Path inside container where static files are served</small></div>
          </div>
          <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Save</button>
        </form>
      </div>

      <div class="detail-tab-content" id="dtab-services">
        <div id="taskmanager-services"><div class="empty-state">Loading services...</div></div>
        <div style="margin-top:12px"><button class="btn btn-sm btn-primary" id="tm-add-btn"><i class="bi bi-plus"></i> Add Service</button></div>
        <div id="taskmanager-add-form" class="settings-section" style="display:none;margin-top:12px">
          <div class="settings-section-title"><i class="bi bi-plus-circle"></i> New Service</div>
          <div class="form-row">
            <div class="form-group"><label class="form-label">Name</label><input type="text" class="form-input" id="tm-svc-name" placeholder="nginx, myapp..."></div>
            <div class="form-group"><label class="form-label">Command</label><input type="text" class="form-input" id="tm-svc-cmd" placeholder="nginx, python3 app.py..."></div>
          </div>
          <div class="form-row">
            <div class="form-group"><label class="form-label">Restart Policy</label><select class="form-select" id="tm-svc-policy"><option value="on-failure">On Failure</option><option value="always">Always</option><option value="never">Never</option></select></div>
            <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="tm-svc-enabled" checked style="width:18px;height:18px;accent-color:var(--accent)"> Enabled</label></div>
          </div>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-sm btn-primary" id="tm-save-btn"><i class="bi bi-check"></i> Save</button>
            <button class="btn btn-sm btn-secondary" id="tm-cancel-btn"><i class="bi bi-x"></i> Cancel</button>
          </div>
        </div>
      </div>`;

    // Bind detail tabs
    el.querySelectorAll('.detail-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        el.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
        el.querySelectorAll('.detail-tab-content').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`dtab-${tab.dataset.dtab}`).classList.add('active');
        if (tab.dataset.dtab === 'terminal' && currentContainer) initContainerTerminal();
        if (tab.dataset.dtab === 'files' && currentContainer) { fileContainerName = currentContainer.name; fileCurrentPath = '/'; closeEditor(); loadFiles(); }
        if (tab.dataset.dtab === 'services' && currentContainer) loadTaskManager();
      });
    });

    // Populate settings form
    document.getElementById('detail-autostart').checked = c.autostart || false;
    document.getElementById('detail-s6').checked = c.s6 || false;
    document.getElementById('detail-mem-limit').value = c.resources?.memory_limit || '256M';
    document.getElementById('detail-cpu-limit').value = c.resources?.cpu_limit_percent || 50;
    document.getElementById('detail-ssh-port').value = c.ssh_port || '';
    document.getElementById('detail-serves-static').checked = c.serves_static || false;
    document.getElementById('detail-static-path').value = c.static_path || '';
    document.getElementById('detail-container-ip').value = c.ip_address || '-';
    try { const cfg = await api('GET', '/config'); document.getElementById('detail-container-subnet').value = cfg.network?.subnet || '-'; } catch(e) {}
    document.getElementById('detail-p2p').checked = c.policies?.inter_container_p2p || false;
    document.getElementById('detail-host').checked = c.policies?.allow_host_access || false;
    document.getElementById('detail-internet').checked = c.policies?.allow_internet || false;
    renderPortMappings(c.port_mappings || []);

    // Disable tabs if building/failed
    if (isBuilding || isFailed) {
      el.querySelectorAll('.detail-tab').forEach(tab => {
        if (tab.dataset.dtab !== 'overview') { tab.style.pointerEvents = 'none'; tab.style.opacity = '0.4'; }
      });
    }

    // Detail forms
    document.getElementById('detail-settings-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentContainer) return;
      try {
        const updateData = {
          autostart: document.getElementById('detail-autostart').checked,
          s6: document.getElementById('detail-s6').checked,
          resources: { memory_limit: document.getElementById('detail-mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('detail-cpu-limit').value) },
          serves_static: document.getElementById('detail-serves-static').checked,
          static_path: document.getElementById('detail-static-path').value || ''
        };
        const newPass = document.getElementById('detail-root-password').value;
        if (newPass && newPass.length >= 4) updateData.root_password = newPass;
        await api('POST', `/containers/${name}/update`, updateData);
        toast(`Settings saved for "${name}"`, 'success');
        showContainerDetail(name, nodeId);
      } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });

    document.getElementById('detail-network-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentContainer) return;
      const rows = document.querySelectorAll('#port-mappings-list .port-row');
      const ports = [];
      rows.forEach(row => {
        const hp = row.querySelector('[data-field="host_port"]');
        if (hp && hp.value) {
          const port = parseInt(hp.value) || 0;
          ports.push({ host_port: port, container_port: port, protocol: 'tcp' });
        }
      });
      try {
        await api('POST', `/containers/${name}/update`, {
          port_mappings: ports,
          policies: { inter_container_p2p: document.getElementById('detail-p2p').checked, allow_host_access: document.getElementById('detail-host').checked, allow_internet: document.getElementById('detail-internet').checked }
        });
        toast(`Network settings saved for "${name}"`, 'success');
        showContainerDetail(name, nodeId);
      } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });

    document.getElementById('add-port-btn')?.addEventListener('click', () => {
      if (!currentContainer) return;
      if (!currentContainer.port_mappings) currentContainer.port_mappings = [];
      currentContainer.port_mappings.push({ host_port: 0, container_port: 0, protocol: 'tcp' });
      renderPortMappings(currentContainer.port_mappings);
    });

    // Service manager buttons
    document.getElementById('tm-add-btn')?.addEventListener('click', () => { document.getElementById('taskmanager-add-form').style.display = 'block'; document.getElementById('tm-svc-name').value = ''; document.getElementById('tm-svc-cmd').value = ''; document.getElementById('tm-svc-name').focus(); });
    document.getElementById('tm-save-btn')?.addEventListener('click', taskManagerSaveService);
    document.getElementById('tm-cancel-btn')?.addEventListener('click', () => { document.getElementById('taskmanager-add-form').style.display = 'none'; });

    // File explorer buttons
    document.getElementById('file-btn-refresh')?.addEventListener('click', loadFiles);
    document.getElementById('file-btn-new')?.addEventListener('click', createNewFile);
    document.getElementById('file-btn-mkdir')?.addEventListener('click', createNewDir);
    document.getElementById('file-btn-save')?.addEventListener('click', saveFile);
    document.getElementById('file-btn-close-editor')?.addEventListener('click', closeEditor);
    document.getElementById('file-btn-upload')?.addEventListener('click', () => document.getElementById('file-upload-input')?.click());
    document.getElementById('file-upload-input')?.addEventListener('change', (e) => { uploadToContainer(e.target.files); e.target.value = ''; });

    // Start log polling for running containers
    if (!isRemote && s === 'running') {
      detailLogTimer = setInterval(async () => {
        try {
          if (!currentContainer || currentContainer.name !== name) { clearInterval(detailLogTimer); detailLogTimer = null; return; }
          const logs = await api('GET', `/containers/${name}/logs`);
          const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
          const el = document.getElementById('detail-log-output');
          if (el) el.textContent = logText || 'No logs available';
        } catch (e) { clearInterval(detailLogTimer); detailLogTimer = null; }
      }, 3000);
    }
  } catch (e) { el.innerHTML = `<div style="color:var(--danger);padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message)}</div>`; }
}

function renderPortMappings(ports) {
  const list = document.getElementById('port-mappings-list');
  if (!list) return;
  if (!ports.length) { list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No port configured</div>'; return; }
  list.innerHTML = ports.map((p, i) => `
    <div class="port-row">
      <div><label style="font-size:11px;color:var(--text-muted);margin-bottom:2px;display:block">Port</label><input type="number" class="form-input" placeholder="8080" value="${p.host_port || ''}" data-idx="${i}" data-field="host_port"></div>
      <button type="button" class="btn btn-ghost btn-sm" data-idx="${i}" style="align-self:flex-end;margin-bottom:6px" onclick="removePort(${i})"><i class="bi bi-x-lg"></i></button>
    </div>
  `).join('');
}

function removePort(idx) {
  if (!currentContainer || !currentContainer.port_mappings) return;
  currentContainer.port_mappings.splice(idx, 1);
  renderPortMappings(currentContainer.port_mappings);
}

async function startContainer(name) { setContainerLoading(name,'start'); try { await api('POST',`/containers/${name}/start`); toast(`Starting "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function stopContainer(name) { setContainerLoading(name,'stop'); try { await api('POST',`/containers/${name}/stop`); toast(`Stopping "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function restartContainer(name) { setContainerLoading(name,'restart'); try { await api('POST',`/containers/${name}/restart`); toast(`Restarting "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function deleteContainer(name) { const ok = await confirmAction('Delete Container',`Delete "${name}"? This cannot be undone.`); if (!ok) return; try { await api('DELETE',`/containers/${name}`); if(detailLogTimer){clearInterval(detailLogTimer);detailLogTimer=null;} currentContainer=null; toast(`Deleted "${name}"`,'success'); loadContainers(); document.getElementById('container-detail').innerHTML='<div class="split-right-empty"><div><i class="bi bi-box-seam"></i><p>Select a container to manage</p></div></div>'; } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

let containerBusy = {};
function setContainerLoading(name, action) { containerBusy[name] = action; }
function clearContainerLoading(name) { delete containerBusy[name]; pollContainerStatus(name, 0); }

async function pollContainerStatus(name, attempt) {
  if (attempt > 30) { loadContainers(); return; }
  try {
    const c = await api('GET', `/containers/${name}`);
    if (c.status === 'building' || c.status === 'starting' || c.status === 'stopping') {
      setTimeout(() => pollContainerStatus(name, attempt + 1), 2000);
    } else { loadContainers(); }
  } catch (e) { loadContainers(); }
}

async function pollRemoteContainerStatus(nodeId, name, attempt) {
  if (attempt > 60) { loadContainers(); return; }
  try {
    const c = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`);
    if (c.status === 'building' || c.status === 'starting' || c.status === 'stopping') {
      setTimeout(() => pollRemoteContainerStatus(nodeId, name, attempt + 1), 3000);
    } else { loadContainers(); }
  } catch (e) { setTimeout(() => pollRemoteContainerStatus(nodeId, name, attempt + 1), 3000); }
}

/* ═══════ IMAGES ═══════ */
async function loadImages() {
  const el = document.getElementById('images-list');
  if (!el) return;
  el.innerHTML = '<div class="skeleton skeleton-card"></div>';
  try {
    const [images, tplData] = await Promise.all([
      api('GET', '/images/all').catch(() => []),
      api('GET', '/images/templates').catch(() => null)
    ]);
    const templates = tplData?.templates || [];
    const imgArr = Array.isArray(images) ? images : [];
    let html = '';

    // Quick Deploy section
    html += `<div class="img-section"><div class="img-section-header" onclick="this.parentElement.classList.toggle('collapsed')"><i class="bi bi-lightning-charge" style="color:var(--accent)"></i> Quick Deploy <i class="bi bi-chevron-down img-chevron"></i></div><div class="img-section-body">`;
    if (templates.length) {
      html += `<div class="templates-grid">${templates.map(t => `<div class="template-card" style="border-left:3px solid ${t.color||'var(--primary)'}" onclick="deployTemplate('${esc(t.id)}','${esc(t.name)}',${t.base_ready})"><div class="template-icon" style="color:${t.color||'var(--primary)'}"><i class="bi ${t.icon||'bi-box-seam'}"></i></div><div class="template-name">${esc(t.name)}</div><div class="template-desc">${esc(t.description||'')}</div><span class="template-badge ${t.base_ready?'ready':'pending'}">${t.base_ready?'Ready':'Pull base first'}</span></div>`).join('')}</div>`;
    } else {
      html += `<div class="empty-state" style="padding:16px"><i class="bi bi-cloud-download" style="font-size:24px;color:var(--text-muted)"></i><p style="margin-top:8px;color:var(--text-muted)">No templates available. Pull an Alpine image first.</p></div>`;
    }
    html += '</div></div>';

    // Ankfile Build section
    html += `<div class="img-section"><div class="img-section-header" onclick="this.parentElement.classList.toggle('collapsed')"><i class="bi bi-file-earmark-code" style="color:var(--accent)"></i> Ankfile Build <i class="bi bi-chevron-down img-chevron"></i></div><div class="img-section-body"><div class="card" style="border:1px solid var(--accent)"><div class="card-body"><div class="form-group"><label class="form-label">Container Name</label><input type="text" class="form-input" id="ankfile-name" placeholder="my-app" value="ank-build"></div><div class="form-group"><label class="form-label">Ankfile</label><textarea class="ankfile-editor" id="ankfile-content" rows="8" placeholder="# Example Ankfile&#10;FROM alpine-3.20&#10;PASSWD ank123&#10;RUN apk add --allow-untrusted nginx&#10;EXPOSE 8080">FROM alpine-3.20
PASSWD ank123
RUN apk add --allow-untrusted nginx
RUN mkdir -p /var/www/html
RUN echo "&lt;h1&gt;Custom ANK Image&lt;/h1&gt;" > /var/www/html/index.html
EXPOSE 8080</textarea></div><div style="display:flex;gap:8px"><button type="button" class="btn btn-primary" id="ankfile-build-btn"><i class="bi bi-hammer"></i> Build</button><button type="button" class="btn btn-ghost" id="ankfile-example-btn"><i class="bi bi-filetype-json"></i> Load Example</button></div></div></div></div></div>`;

    // Images section
    html += `<div class="img-section"><div class="img-section-header" onclick="this.parentElement.classList.toggle('collapsed')"><i class="bi bi-hdd-stack" style="color:var(--accent)"></i> Ank Images (${imgArr.length}) <i class="bi bi-chevron-down img-chevron"></i></div><div class="img-section-body">`;
    if (imgArr.length) {
      html += imgArr.map(img => `<div class="split-list-card" data-id="${esc(img.name)}" onclick="showImageDetail('${esc(img.name)}')"><div class="slc-top"><span class="slc-name"><i class="bi bi-hdd-stack" style="color:var(--accent)"></i>${esc(img.name)}</span><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteImage('${esc(img.name)}')" title="Delete"><i class="bi bi-trash3"></i></button></div><div class="slc-meta"><span>${img.size_human || fmtBytes(img.size||0)}</span><span>${esc(img.version||'')}</span></div></div>`).join('');
    } else {
      html += '<div class="empty-state" style="padding:16px"><i class="bi bi-hdd-stack" style="font-size:24px;color:var(--text-muted)"></i><p style="margin-top:8px;color:var(--text-muted)">No images downloaded yet</p></div>';
    }
    html += '</div></div>';

    el.innerHTML = html;

    // Bind ankfile buttons
    document.getElementById('ankfile-build-btn')?.addEventListener('click', async () => {
      const content = document.getElementById('ankfile-content')?.value?.trim();
      const name = document.getElementById('ankfile-name')?.value?.trim() || 'ank-build';
      if (!content) { toast('Ankfile is empty', 'error'); return; }
      if (!content.includes('FROM')) { toast('Ankfile must have a FROM instruction', 'error'); return; }
      try { toast(`Building from Ankfile as "${name}"...`, 'info'); await api('POST', '/images/ankfile', { content, name }); loadContainers(); pollContainerStatus(name, 0); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });
    document.getElementById('ankfile-example-btn')?.addEventListener('click', () => {
      document.getElementById('ankfile-content').value = 'FROM alpine-3.20\nPASSWD ank123\nRUN apk add --allow-untrusted curl tar sqlite\nRUN mkdir -p /opt/cloudreve\nRUN curl -L https://github.com/cloudreve/cloudreve/releases/download/4.18.0/cloudreve_4.18.0_linux_armv7.tar.gz | tar xz -C /opt/cloudreve\nEXPOSE 5212\nWORKDIR /opt/cloudreve\nCMD /opt/cloudreve/cloudreve';
      document.getElementById('ankfile-name').value = 'cloudreve';
      toast('Example Ankfile loaded', 'info');
    });
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function showImageDetail(name) {
  document.querySelectorAll('#images-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.id === name));
  const el = document.getElementById('image-detail');
  if (!el) return;
  el.innerHTML = `
    <div class="sr-header">
      <h2><i class="bi bi-hdd-stack" style="color:var(--accent)"></i>${esc(name)}</h2>
      <div class="sr-actions">
        <button class="btn btn-primary btn-sm" onclick="deployTemplate('${esc(name)}','${esc(name)}',true)"><i class="bi bi-rocket-takeoff"></i> Deploy</button>
        <button class="btn btn-danger btn-sm" onclick="deleteImage('${esc(name)}')"><i class="bi bi-trash3"></i></button>
      </div>
    </div>
    <div class="sr-info-grid">
      <div class="sr-info-item"><div class="sr-label">Name</div><div class="sr-value">${esc(name)}</div></div>
    </div>`;
}

function showTemplateDetail(id, name, color, icon, desc, baseReady) {
  document.querySelectorAll('#images-list .template-card').forEach(c => c.classList.toggle('selected', c.dataset.id === id));
  const el = document.getElementById('image-detail');
  if (!el) return;
  el.innerHTML = `
    <div class="sr-header">
      <h2><i class="bi ${icon||'bi-box-seam'}" style="color:${color||'var(--primary)'}"></i>${esc(name)}</h2>
      <div class="sr-actions">
        <button class="btn btn-primary btn-sm" onclick="deployTemplate('${esc(id)}','${esc(name)}',${baseReady})"><i class="bi bi-rocket-takeoff"></i> Deploy</button>
      </div>
    </div>
    <div class="sr-info-grid">
      <div class="sr-info-item"><div class="sr-label">Template</div><div class="sr-value">${esc(name)}</div></div>
      <div class="sr-info-item"><div class="sr-label">Status</div><div class="sr-value"><span class="template-badge ${baseReady?'ready':'pending'}">${baseReady?'Ready':'Pull base first'}</span></div></div>
    </div>
    <div style="margin-top:12px;color:var(--text-secondary);font-size:13px">${esc(desc||'No description')}</div>`;
}

async function pullImage() {
  const result = await customModal('Pull Image', [
    { id: 'version', label: 'Alpine Version', type: 'select', options: '<option value="3.20">Alpine 3.20</option><option value="3.19">Alpine 3.19</option><option value="3.18">Alpine 3.18</option>' }
  ]);
  if (!result) return;
  try { toast('Pulling image...', 'info'); await api('POST', '/images/pull', { version: result.version }); toast('Image pulled', 'success'); loadImages(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deployTemplate(id, name, baseReady) {
  if (baseReady === false) { toast('Download the Alpine base image first (Pull Alpine)', 'warning'); return; }
  let defaultPass = 'ank123';
  try { const cfg = await api('GET', '/config'); if (cfg?.default_container_password) defaultPass = cfg.default_container_password; } catch(e) {}
  const fields = [
    { id: 'tpl-name', label: 'Container name:', type: 'text', value: (name||id).toLowerCase().replace(/[^a-z0-9-]/g,'-') },
    { id: 'tpl-pass', label: 'Root password:', type: 'password', value: defaultPass }
  ];
  let onlineNodes = [];
  try { const d = await api('GET', '/system/dashboard'); onlineNodes = (d.nodes || []).filter(n => n.status === 'online'); } catch(e) {}
  if (onlineNodes.length > 0) {
    let opts = '<option value="local">Local</option>';
    onlineNodes.forEach(n => { opts += `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`; });
    fields.push({ id: 'tpl-target-node', label: 'Target node:', type: 'select', options: opts });
  }
  const result = await customModal('Deploy ' + (name||id), fields);
  if (!result) return;
  const containerName = result['tpl-name'];
  const rootPass = result['tpl-pass'];
  const nodeId = result['tpl-target-node'] || 'local';
  if (!containerName) { toast('Container name required', 'warning'); return; }
  if (!rootPass || rootPass.length < 4) { toast('Password must be at least 4 characters', 'warning'); return; }
  try {
    if (nodeId !== 'local') {
      toast(`Deploying on remote...`, 'info');
      await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name: containerName, image: id, root_password: rootPass });
      toast(`Creation sent to remote node`, 'success');
      setTimeout(() => { loadContainers(); pollRemoteContainerStatus(nodeId, containerName, 0); }, 1000);
    } else {
      toast(`Deploying as "${containerName}"...`, 'info');
      await api('POST', '/images/deploy', { template: id, name: containerName, root_password: rootPass });
      pollContainerStatus(containerName, 0);
      loadContainers();
    }
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-pull-image')?.addEventListener('click', pullImage);

async function deleteImage(id) {
  const ok = await confirmAction('Delete Image', 'Delete this image?');
  if (!ok) return;
  try { await api('DELETE', `/images/${encodeURIComponent(id)}`); toast('Image deleted', 'success'); loadImages(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ═══════ NODES ═══════ */
let currentNodeDetailId = null;

async function loadNodes() {
  const el = document.getElementById('nodes-list');
  if (!el) return;
  el.innerHTML = '<div class="skeleton skeleton-card"></div>';
  try {
    const data = await api('GET', '/nodes');
    const nodes = data.nodes || [];
    // Manager card
    let managerHtml = '';
    try {
      const mgr = await api('GET', '/nodes/manager');
      if (mgr.manager) {
        const m = mgr.manager;
        const mColor = m.status === 'online' ? 'var(--success)' : m.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
        managerHtml = `<div style="background:var(--glass-bg);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="width:8px;height:8px;border-radius:50%;background:${mColor};flex-shrink:0"></span><strong>Managed by: ${esc(m.alias||m.ip)}</strong><span class="badge badge-info" style="font-size:10px">MANAGER</span></div><div style="color:var(--text-muted);font-size:12px">IP: ${esc(m.ip)}</div></div>
            <button class="btn btn-danger btn-sm" onclick="revokeManager()"><i class="bi bi-x-circle"></i> Revoke</button>
          </div></div>`;
      }
    } catch(e) {}
    if (!nodes.length && !managerHtml) { el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-network"></i><h3>No nodes</h3><p>Add a remote ANK device</p></div>'; return; }
    if (!nodes.length && managerHtml) { el.innerHTML = managerHtml; return; }
    el.innerHTML = managerHtml + nodes.map(n => {
      const color = n.status === 'online' ? 'var(--success)' : n.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
      const label = n.status === 'online' ? 'Online' : n.status === 'pending' ? 'Pending' : 'Offline';
      const isOnline = n.status === 'online';
      const roleTag = n.role === 'manager' ? '<span class="badge badge-info" style="font-size:10px">MANAGER</span>' : '';
      return `<div class="split-list-card" data-id="${esc(n.id)}" onclick="showNodeDetail('${esc(n.id)}','${esc(n.alias||n.ip)}','${esc(n.status)}')">
        <div class="slc-top"><span class="slc-name"><i class="bi bi-hdd-network" style="color:var(--primary)"></i>${esc(n.alias||n.ip)}${roleTag}</span><span class="badge ${n.status==='online'?'badge-success':n.status==='pending'?'badge-warning':'badge-danger'}" style="font-size:10px">${label}</span></div>
        <div class="slc-meta"><span>CPU ${isOnline?Math.round(n.cpu_percent||0)+'%':'-'}</span><span>RAM ${isOnline?(n.mem_used_gb||0).toFixed(1)+'GB':'-'}</span><span>${isOnline?(n.containers_total||0):'-'} containers</span></div>
      </div>`;
    }).join('');
    updateNodeSelectors(nodes);
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load nodes</p></div>'; }
}

async function showNodeDetail(nodeId, name, status) {
  currentNodeDetailId = nodeId;
  document.querySelectorAll('#nodes-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.id === nodeId));
  const el = document.getElementById('node-detail');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)"><i class="bi bi-arrow-repeat spin" style="font-size:24px"></i><p style="margin-top:8px">Loading...</p></div>';
  try {
    const [st, sysInfo, containers, images] = await Promise.all([
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/status`).catch(()=>({})),
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/system/info`).catch(()=>({})),
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers`).catch(()=>[]),
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/images`).catch(()=>[])
    ]);
    const info = { ...sysInfo, ...st };
    const dev = info.device_model || info.device || '-';
    const cpu = info.cpu_usage != null ? info.cpu_usage+'%' : '-';
    const memT = info.memory?.total_kb || 0;
    const memA = info.memory?.available_kb || 0;
    const mem = memT > 0 ? `${fmtBytes((memT-memA)*1024)} / ${fmtBytes(memT*1024)}` : '-';
    const battery = info.battery;
    const batteryText = (battery != null && battery >= 0) ? battery+'%' : '-';
    const kernel = info.kernel || '-';
    const uptime = info.uptime ? fmtUptime(info.uptime) : '-';
    const contArr = Array.isArray(containers) ? containers : [];
    const imgArr = Array.isArray(images) ? images : [];
    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-hdd-network" style="color:var(--primary)"></i>${esc(name)} <span class="badge ${status==='online'?'badge-success':'badge-danger'}" style="font-size:11px">${status}</span></h2>
        <div class="sr-actions">
          ${status==='online'?`<button class="btn btn-secondary btn-sm" onclick="restartRemoteNode()"><i class="bi bi-arrow-clockwise"></i> Restart</button>`:''}
          <button class="btn btn-danger btn-sm" onclick="deleteNode('${esc(nodeId)}')"><i class="bi bi-trash3"></i> Remove</button>
        </div>
      </div>
      <div class="detail-stats">
        <div class="detail-stat"><span class="detail-stat-label">Device</span><span class="detail-stat-value">${esc(dev)}</span></div>
        <div class="detail-stat"><span class="detail-stat-label">CPU</span><span class="detail-stat-value">${esc(cpu)}</span></div>
        <div class="detail-stat"><span class="detail-stat-label">Memory</span><span class="detail-stat-value">${esc(mem)}</span></div>
        <div class="detail-stat"><span class="detail-stat-label">Battery</span><span class="detail-stat-value">${esc(batteryText)}</span></div>
        <div class="detail-stat"><span class="detail-stat-label">Uptime</span><span class="detail-stat-value">${esc(uptime)}</span></div>
        <div class="detail-stat"><span class="detail-stat-label">Images</span><span class="detail-stat-value">${imgArr.length}</span></div>
      </div>
      <div style="margin-bottom:12px"><h4 style="margin-bottom:8px;font-size:13px;color:var(--text-muted)"><i class="bi bi-terminal"></i> Kernel</h4><code style="font-size:12px;background:rgba(10,15,30,0.4);padding:6px 10px;border-radius:6px;display:block">${esc(kernel)}</code></div>
      <div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:10px">Containers (${contArr.length})</div>
      ${contArr.length ? contArr.map(c => {
        const sc = c.status==='running'?'badge-success':c.status==='building'?'badge-warning':'badge-neutral';
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
          <span style="font-size:13px">${esc(c.name)} <span class="badge ${sc}" style="font-size:9px">${c.status}</span></span>
          <div style="display:flex;gap:4px">
            ${c.status==='running'?`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','stop')"><i class="bi bi-stop-fill"></i></button>`:`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','start')"><i class="bi bi-play-fill"></i></button>`}
            <button class="btn btn-icon btn-ghost sm" onclick="remoteDeleteContainer('${nodeId}','${esc(c.name)}')"><i class="bi bi-trash3"></i></button>
          </div></div>`;
      }).join('') : '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:12px">No containers</div>'}`;
  } catch (e) { el.innerHTML = `<div style="color:var(--danger);padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message)}</div>`; }
}

async function loadPairingRequests() {
  const el = document.getElementById('nodes-pairing-requests');
  if (!el) return;
  try {
    const data = await api('GET', '/nodes/pairing');
    const requests = data.requests || [];
    if (!requests.length) { el.innerHTML = ''; return; }
    el.innerHTML = requests.map(r => `<div class="card" style="padding:16px;display:flex;align-items:center;justify-content:space-between">
      <div><strong>${esc(r.manager_name)}</strong><span class="text-muted text-sm" style="margin-left:8px">${esc(r.manager_ip||'')}</span></div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-success btn-sm" onclick="approvePairing('${esc(r.id)}')"><i class="bi bi-check-lg"></i> Approve</button>
        <button class="btn btn-danger btn-sm" onclick="rejectPairing('${esc(r.id)}')"><i class="bi bi-x-lg"></i> Reject</button>
      </div></div>`).join('');
  } catch (e) { el.innerHTML = ''; }
}

async function approvePairing(reqId) { try { await api('POST', `/nodes/pairing/${encodeURIComponent(reqId)}/approve`); toast('Approved', 'success'); loadPairingRequests(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); } }
async function rejectPairing(reqId) { try { await api('POST', `/nodes/pairing/${encodeURIComponent(reqId)}/reject`); toast('Rejected', 'success'); loadPairingRequests(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); } }

async function restartRemoteNode() {
  if (!currentNodeDetailId) return;
  const ok = await confirmAction('Restart Device', 'Reboot remote device?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(currentNodeDetailId)}/restart`); toast('Restart sent', 'success'); showNodeDetail(currentNodeDetailId, '', 'online'); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteNode(id) {
  const ok = await confirmAction('Remove Node', 'Remove this node?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(id)}/delete`); toast('Node removed', 'success'); document.getElementById('node-detail').innerHTML = '<div class="split-right-empty"><div><i class="bi bi-hdd-network"></i><p>Select a node</p></div></div>'; loadNodes(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function revokeManager() {
  const ok = await confirmAction('Revoke Manager', 'Revoke manager access? This node will no longer be managed.');
  if (!ok) return;
  try { await api('DELETE', '/nodes/manager'); toast('Manager access revoked', 'success'); loadNodes(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-add-node')?.addEventListener('click', sendPairingRequest);

async function sendPairingRequest() {
  const result = await customModal('Add Node', [
    { id: 'ip', label: 'Panel IP', type: 'text' },
    { id: 'port', label: 'Port', type: 'text', value: '8001' },
    { id: 'password', label: 'Password', type: 'text' },
    { id: 'alias', label: 'Alias', type: 'text' }
  ]);
  if (!result) return;
  try { await api('POST', '/nodes/pairing/send', { ip: result.ip, port: parseInt(result.port), password: result.password, alias: result.alias }); toast('Pairing request sent', 'success'); loadNodes(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function remoteContainerAction(nodeId, name, action) {
  try { await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}/${action}`); toast(`${action} sent`, 'success'); loadContainers(); pollRemoteContainerStatus(nodeId, name, 0); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function remoteDeleteContainer(nodeId, name) {
  const ok = await confirmAction('Delete Container', `Delete "${name}" on remote node?`);
  if (!ok) return;
  try { await api('DELETE', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`); toast('Deleted', 'success'); loadContainers(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

function updateNodeSelectors(nodes) {
  const onlineNodes = (nodes || []).filter(n => n.status === 'online');
  const shellSel = document.getElementById('shell-container-select');
  if (shellSel) {
    const val = shellSel.value;
    shellSel.innerHTML = '<option value="local">Local</option>' + onlineNodes.map(n => `<option value="${esc(n.id)}">${esc(n.alias||n.ip)}</option>`).join('');
    if (val) shellSel.value = val;
  }
  const logSel = document.getElementById('log-node-selector');
  if (logSel) {
    const val = logSel.value;
    logSel.innerHTML = '<option value="local">Local</option>' + onlineNodes.map(n => `<option value="${esc(n.id)}">${esc(n.alias||n.ip)}</option>`).join('');
    if (val) logSel.value = val;
  }
  const createModalSel = document.getElementById('container-target-node');
  if (createModalSel) {
    const val = createModalSel.value;
    createModalSel.innerHTML = '<option value="local">Local</option>' + onlineNodes.map(n => `<option value="${esc(n.id)}">${esc(n.alias||n.ip)}</option>`).join('');
    if (val) createModalSel.value = val;
  }
}

/* ═══════ STACKS ═══════ */
async function loadStacks() {
  const el = document.getElementById('stacks-list');
  if (!el) return;
  try {
    const data = await api('GET', '/stacks/all');
    const stacks = data.stacks || [];
    if (!stacks.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-layers"></i><h3>No stacks</h3><p>Create a stack to get started</p></div>'; return; }
    el.innerHTML = stacks.map(s => {
      const running = (s.containers||[]).filter(c => c.status==='running').length;
      const total = (s.containers||[]).length;
      const bc = running===total&&total>0 ? 'badge-success' : running>0 ? 'badge-warning' : 'badge-danger';
      const tpl = s.template === 'ankfile' ? '<i class="bi bi-filetype-json"></i> Ankfile' : esc(s.template||s.image||'');
      const lbPort = s.port || s.lb_port || '-';
      return `<div class="split-list-card" data-name="${esc(s.name)}" onclick="showStackDetail('${esc(s.name)}')">
        <div class="slc-top"><span class="slc-name"><i class="bi bi-layers" style="color:var(--accent)"></i>${esc(s.name)}</span><span class="badge ${bc}" style="font-size:10px">${running}/${total}</span></div>
        <div class="slc-meta"><span>${tpl}</span><span>LB: ${lbPort}</span></div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function showStackDetail(name) {
  document.querySelectorAll('#stacks-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.name === name));
  const el = document.getElementById('stack-detail');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)"><i class="bi bi-arrow-repeat spin" style="font-size:24px"></i></div>';
  api('GET', '/stacks/all').then(data => {
    const s = (data.stacks||[]).find(x => x.name === name);
    if (!s) { el.innerHTML = '<div style="padding:20px;color:var(--text-muted)">Stack not found</div>'; return; }
    const running = (s.containers||[]).filter(c => c.status==='running').length;
    const total = (s.containers||[]).length;
    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-layers" style="color:var(--accent)"></i>${esc(s.name)}</h2>
        <div class="sr-actions">
          <button class="btn btn-secondary btn-sm" onclick="scaleStackUp('${esc(s.name)}')" title="Scale Up"><i class="bi bi-plus-lg"></i></button>
          <button class="btn btn-secondary btn-sm" onclick="scaleStackDown('${esc(s.name)}')" title="Scale Down"><i class="bi bi-dash-lg"></i></button>
          <button class="btn btn-danger btn-sm" onclick="deleteStack('${esc(s.name)}')"><i class="bi bi-trash3"></i></button>
        </div>
      </div>
      <div class="sr-info-grid">
        <div class="sr-info-item"><div class="sr-label">Template</div><div class="sr-value">${esc(s.template||s.image||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Status</div><div class="sr-value">${running}/${total} running</div></div>
        <div class="sr-info-item"><div class="sr-label">LB Port</div><div class="sr-value">${s.port||s.lb_port||'-'}</div></div>
      </div>
      <div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:10px">Containers</div>
      ${(s.containers||[]).map(c => {
        const sc = c.status==='running'?'badge-success':c.status==='building'?'badge-warning':'badge-neutral';
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
          <span style="font-size:13px">${esc(c.name)} <span class="badge ${sc}" style="font-size:9px">${c.status}</span></span>
        </div>`;
      }).join('') || '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:12px">No containers</div>'}`;
  }).catch(e => { el.innerHTML = `<div style="color:var(--danger);padding:20px">${esc(e.message)}</div>`; });
}

document.getElementById('btn-create-stack')?.addEventListener('click', () => {
  document.getElementById('stack-modal-overlay').classList.add('active');
});
function toggleStackAnkfile() { const sel = document.getElementById('stack-image')?.value; const sec = document.getElementById('stack-ankfile-section'); if (sec) sec.style.display = sel === 'ankfile' ? 'block' : 'none'; }

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
  try {
    toast(`Creating stack "${name}"...`, 'info');
    await api('POST', '/stacks', { name, template: image, instances, lb_port: lbPort, shared_volume: volume, trigger: trigger === 'none' ? null : trigger, ankfile });
    closeModalById('stack-modal-overlay');
    toast(`Stack "${name}" created`, 'success');
    loadStacks();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function scaleStackUp(name) { try { await api('POST', `/stacks/${encodeURIComponent(name)}/scale`, { count: 1 }); toast(`Scaled up "${name}"`, 'success'); loadStacks(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); } }
async function scaleStackDown(name) { try { await api('POST', `/stacks/${encodeURIComponent(name)}/scale-down`, { count: 1 }); toast(`Scaled down "${name}"`, 'success'); loadStacks(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); } }
async function deleteStack(name) {
  const ok = await confirmAction('Delete Stack', `Delete stack "${name}" and all its containers?`);
  if (!ok) return;
  try { await api('DELETE', `/stacks/${encodeURIComponent(name)}`); toast('Stack deleted', 'success'); loadStacks(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ═══════ BACKUPS ═══════ */
async function loadBackups() {
  const el = document.getElementById('backups-list');
  if (!el) return;
  try {
    const data = await api('GET', '/backups');
    const routines = data.routines || [];
    if (!routines.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-cloud-arrow-up"></i><h3>No backups</h3><p>Create a backup routine</p></div>'; return; }
    el.innerHTML = routines.map(r => {
      const lastRun = r.last_run ? new Date(r.last_run).toLocaleString() : 'Never';
      const statusColor = r.last_status === 'success' ? 'var(--success)' : r.last_status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
      return `<div class="split-list-card" data-id="${esc(r.id||r.name)}" onclick="showBackupDetail('${esc(r.id||r.name)}')">
        <div class="slc-top"><span class="slc-name"><i class="bi bi-cloud-arrow-up" style="color:var(--accent)"></i>${esc(r.name)}</span><span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span></div>
        <div class="slc-meta"><span>${esc(r.schedule||'-')}</span><span>Retention: ${r.retention||30}d</span><span>Last: ${lastRun}</span></div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function showBackupDetail(id) {
  document.querySelectorAll('#backups-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.id === id));
  const el = document.getElementById('backup-detail');
  if (!el) return;
  api('GET', '/backups').then(data => {
    const r = (data.routines||[]).find(x => (x.id||x.name) === id);
    const lastRun = r?.last_run ? new Date(r.last_run).toLocaleString() : 'Never';
    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-cloud-arrow-up" style="color:var(--accent)"></i>${esc(id)}</h2>
        <div class="sr-actions">
          <button class="btn btn-success btn-sm" onclick="executeBackup('${esc(id)}')"><i class="bi bi-play-fill"></i> Run</button>
          <button class="btn btn-danger btn-sm" onclick="deleteBackup('${esc(id)}')"><i class="bi bi-trash3"></i></button>
        </div>
      </div>
      <div class="sr-info-grid">
        <div class="sr-info-item"><div class="sr-label">Source</div><div class="sr-value">${esc(r?.source||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Remote Host</div><div class="sr-value">${esc(r?.remote_host||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Schedule</div><div class="sr-value">${esc(r?.schedule||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Retention</div><div class="sr-value">${r?.retention||30}d</div></div>
        <div class="sr-info-item" style="grid-column:span 2"><div class="sr-label">Last Run</div><div class="sr-value">${lastRun}</div></div>
      </div>`;
  }).catch(e => { el.innerHTML = `<div style="color:var(--danger);padding:20px">${esc(e.message)}</div>`; });
}

document.getElementById('btn-create-backup')?.addEventListener('click', () => {
  document.getElementById('backup-modal-overlay').classList.add('active');
});

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
    closeModalById('backup-modal-overlay');
    toast(`Routine "${name}" created`, 'success');
    loadBackups();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function executeBackup(id) { try { toast('Running backup...','info'); await api('POST',`/backups/${encodeURIComponent(id)}/execute`); toast('Backup complete','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }
async function deleteBackup(id) { const ok = await confirmAction('Delete Backup','Delete this routine?'); if(!ok) return; try { await api('POST',`/backups/${encodeURIComponent(id)}/delete`); toast('Deleted','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

/* ═══════ NETWORKS ═══════ */
async function loadNetworks() {
  const el = document.getElementById('networks-list');
  if (!el) return;
  try {
    const [networks, info] = await Promise.all([api('GET', '/networks'), api('GET', '/networks/info')]);
    if (!networks || !networks.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-globe2"></i><h3>No networks</h3></div>'; return; }
    el.innerHTML = networks.map(net => `<div class="split-list-card" data-name="${esc(net.name)}" onclick="showNetworkDetail('${esc(net.name)}')">
      <div class="slc-top"><span class="slc-name"><i class="bi bi-globe2" style="color:var(--accent)"></i>${esc(net.name)}</span><span class="badge badge-success" style="font-size:10px">${net.mode}</span></div>
      <div class="slc-meta"><span>${esc(net.subnet)}</span><span>GW: ${esc(net.gateway)}</span><span>NAT: ${net.nat?'On':'Off'}</span></div>
    </div>`).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function showNetworkDetail(name) {
  document.querySelectorAll('#networks-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.name === name));
  const el = document.getElementById('network-detail');
  if (!el) return;
  api('GET', '/networks').then(networks => {
    const net = networks.find(n => n.name === name);
    if (!net) { el.innerHTML = '<div style="padding:20px;color:var(--text-muted)">Network not found</div>'; return; }
    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-globe2" style="color:var(--accent)"></i>${esc(net.name)}</h2>
      </div>
      <div class="sr-info-grid">
        <div class="sr-info-item"><div class="sr-label">Name</div><div class="sr-value">${esc(net.name)}</div></div>
        <div class="sr-info-item"><div class="sr-label">Mode</div><div class="sr-value">${esc(net.mode)}</div></div>
        <div class="sr-info-item"><div class="sr-label">Subnet</div><div class="sr-value font-mono">${esc(net.subnet)}</div></div>
        <div class="sr-info-item"><div class="sr-label">Gateway</div><div class="sr-value font-mono">${esc(net.gateway)}</div></div>
        <div class="sr-info-item"><div class="sr-label">NAT</div><div class="sr-value">${net.nat?'Enabled':'Disabled'}</div></div>
        <div class="sr-info-item"><div class="sr-label">Containers</div><div class="sr-value">${net.containers?.length||0}</div></div>
      </div>
      ${net.containers && net.containers.length > 0 ? `<div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:10px">Connected Containers</div>${net.containers.map(c => `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px"><span style="font-size:13px">${esc(c.name)}</span><span class="font-mono" style="font-size:12px">${esc(c.ip)}</span></div>`).join('')}` : ''}`;
  }).catch(e => { el.innerHTML = `<div style="color:var(--danger);padding:20px">${esc(e.message)}</div>`; });
}

document.getElementById('network-config-btn')?.addEventListener('click', async () => {
  try {
    const info = await api('GET', '/networks/info');
    document.getElementById('net-bridge').value = info.bridge || 'ank0';
    document.getElementById('net-subnet').value = (info.subnet || '').replace('/24', '');
    document.getElementById('net-gateway').value = info.gateway || '';
    document.getElementById('net-nat').checked = info.nat_enabled !== false;
    document.getElementById('network-modal-overlay').classList.add('active');
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('network-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const subnet = document.getElementById('net-subnet').value.trim();
  const gateway = document.getElementById('net-gateway').value.trim();
  const bridge = document.getElementById('net-bridge').value.trim();
  const nat = document.getElementById('net-nat').checked;
  if (!subnet.match(/^\d+\.\d+\.\d+\.0$/)) { toast('Subnet must be a /24 network ending in .0', 'error'); return; }
  try {
    await api('POST', '/networks', { subnet, gateway, bridge, nat });
    closeModalById('network-modal-overlay');
    toast(`Network ${subnet}/24 configured`, 'success');
    loadNetworks();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

/* ═══════ SETTINGS ═══════ */
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
    if (remoteMgmtEl) remoteMgmtEl.addEventListener('change', () => { document.getElementById('manager-ip-group').style.display = remoteMgmtEl.checked ? 'block' : 'none'; });
  } catch(e) {}
  try {
    const info = await api('GET', '/system/info');
    document.getElementById('info-rootfs').textContent = info.rootfs_size || '-';
    document.getElementById('info-containers-size').textContent = info.containers_size || '-';
    document.getElementById('info-total-size').textContent = info.total_size || '-';
    document.getElementById('info-device-free').textContent = info.device_free || '-';
  } catch(e) {}
}

document.getElementById('password-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('POST', '/auth/password', {
      current_password: document.getElementById('current-password').value,
      username: document.getElementById('new-username').value || undefined,
      new_password: document.getElementById('new-password').value || undefined
    });
    toast('Credentials updated', 'success');
    const newPass = document.getElementById('new-password').value;
    const newUser = document.getElementById('new-username').value;
    if (newPass) {
      const user = newUser || loginUsername.value;
      const loginRes = await fetch(`${API}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
        body: JSON.stringify({ username: user, password: newPass })
      });
      const loginData = await loginRes.json();
      if (loginData.token) { ankToken = loginData.token; localStorage.setItem('ank_token', ankToken); }
    }
    document.getElementById('password-form').reset();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

document.getElementById('panel-settings-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('POST', '/config', {
      bind_address: document.getElementById('setting-bind').value,
      refresh_interval: parseInt(document.getElementById('setting-refresh').value),
      autostart_on_boot: document.getElementById('setting-autostart').checked,
      node_name: document.getElementById('setting-node-name')?.value?.trim() || '',
      default_container_password: document.getElementById('setting-default-pass')?.value?.trim() || ''
    });
    refreshSeconds = parseInt(document.getElementById('setting-refresh').value);
    localStorage.setItem('ank_refresh', refreshSeconds);
    startRefreshTimer();
    toast('Server settings saved', 'success');
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

async function saveRemoteSSHSettings() {
  try {
    await api('POST', '/config', {
      enable_remote_management: document.getElementById('setting-remote-mgmt')?.checked ?? false,
      manager_ip: document.getElementById('setting-manager-ip')?.value?.trim() || '',
      ssh_enabled: document.getElementById('setting-ssh-enabled')?.checked ?? true,
      ssh_port: parseInt(document.getElementById('setting-ssh-port')?.value || '2200')
    });
    toast('Settings saved', 'success');
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('restart-device-btn')?.addEventListener('click', async () => {
  const ok = await confirmAction('Restart Device', 'This will reboot the Android device. Continue?');
  if (!ok) return;
  try { toast('Rebooting device...', 'warning'); await api('POST', '/system/restart-device'); } catch(e) {}
});

document.getElementById('restart-server-btn')?.addEventListener('click', async () => {
  const ok = await confirmAction('Restart Server', 'Restart the ANK server?');
  if (!ok) return;
  try { await api('POST', '/system/restart-server'); } catch(e) {}
  toast('Server restarting...', 'info');
  setTimeout(() => { window.location.reload(); }, 5000);
});

document.getElementById('uninstall-btn')?.addEventListener('click', async () => {
  const ok = await confirmAction('Uninstall ANK', 'This will PERMANENTLY delete ALL containers, images, configs. This cannot be undone.');
  if (!ok) return;
  try { toast('Uninstalling ANK...', 'warning'); await api('POST', '/system/uninstall'); } catch(e) {}
});

/* ═══════ SHELL ═══════ */
let coreTerminal = null;
let coreWs = null;
let wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';

async function detectWsProtocol() {
  try { const res = await fetch(API+'/protocol', { headers: { 'X-ANK-Client': 'ank-panel', 'Authorization': 'Bearer '+ankToken } }); if (res.ok) { const d = await res.json(); wsProtocol = d.protocol==='https'?'wss:':'ws:'; } } catch(e) {}
}

function initCoreTerminal() {
  const el = document.getElementById('terminal');
  if (!el) return;
  if (coreTerminal) { try { coreTerminal.dispose(); } catch(e){} coreTerminal = null; }
  if (coreWs) { try { coreWs.close(); } catch(e){} coreWs = null; }
  el.innerHTML = '';
  try {
    coreTerminal = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: "'Cascadia Code','Fira Code',monospace", theme: { background: '#0a0d12', foreground: '#d3d9e3', cursor: '#58a6ff' }, scrollback: 5000 });
    coreTerminal.open(el);
    coreTerminal.writeln('\x1b[1;36m  ANK Core Shell\x1b[0m');
    coreTerminal.writeln('\x1b[90m  Connecting...\x1b[0m\r\n');
    coreTerminal.focus();
    connectCoreWs();
    const resize = () => { const rect = el.getBoundingClientRect(); const cols = Math.floor(rect.width/8.4); const rows = Math.floor(rect.height/18); if (cols>0&&rows>0) { coreTerminal.resize(cols,rows); if (coreWs&&coreWs.readyState===WebSocket.OPEN) coreWs.send(JSON.stringify({type:'resize',cols,rows})); } };
    window.addEventListener('resize', resize);
    setTimeout(resize, 100);
  } catch(e) { el.innerHTML = '<div style="color:var(--danger);padding:20px">xterm.js failed to load</div>'; }
}

async function connectCoreWs() {
  await detectWsProtocol();
  const nodeId = document.getElementById('shell-container-select')?.value || 'local';
  const isRemote = nodeId && nodeId !== 'local';
  const basePath = isRemote ? `/ws/node-shell/${encodeURIComponent(nodeId)}` : '/ws/shell';
  const url = wsProtocol+'//'+location.host+basePath+'?cols='+(coreTerminal?coreTerminal.cols:80)+'&rows='+(coreTerminal?coreTerminal.rows:24)+'&token='+encodeURIComponent(ankToken);
  coreWs = new WebSocket(url);
  coreWs.onopen = () => { if(coreTerminal) { coreTerminal.writeln('\x1b[90m  Connected.\x1b[0m\r\n'); coreTerminal.focus(); } };
  coreWs.onmessage = ev => { if(coreTerminal) coreTerminal.write(ev.data); };
  coreWs.onclose = () => { if(coreTerminal) coreTerminal.writeln('\r\n\x1b[31m[Connection closed]\x1b[0m'); };
  coreWs.onerror = () => { if(coreTerminal) coreTerminal.writeln('\r\n\x1b[31m[Connection error]\x1b[0m'); };
  if (coreTerminal) coreTerminal.onData(data => { if(coreWs&&coreWs.readyState===WebSocket.OPEN) coreWs.send(JSON.stringify({type:'input',data})); });
}

document.getElementById('btn-shell-connect')?.addEventListener('click', initCoreTerminal);
document.getElementById('btn-shell-disconnect')?.addEventListener('click', () => {
  if (coreWs) { try { coreWs.close(); } catch(e){} coreWs = null; }
  if (coreTerminal) { try { coreTerminal.dispose(); } catch(e){} coreTerminal = null; }
  document.getElementById('terminal').innerHTML = '';
});

/* ═══════ CONTAINER TERMINAL ═══════ */
let xtermTerminal = null;
let xtermWs = null;

function initContainerTerminal() {
  const el = document.getElementById('container-terminal');
  if (!el) return;
  if (!currentContainer || currentContainer.status !== 'running') {
    el.innerHTML = '<div style="color:var(--danger);padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> Container not running</div>';
    return;
  }
  if (xtermTerminal) { try { xtermTerminal.dispose(); } catch(e){} xtermTerminal = null; }
  if (xtermWs) { try { xtermWs.close(); } catch(e){} xtermWs = null; }
  el.innerHTML = '';
  try {
    xtermTerminal = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: "'Cascadia Code','Fira Code',monospace", theme: { background: '#0a0d12', foreground: '#d3d9e3', cursor: '#58a6ff' }, scrollback: 5000 });
    xtermTerminal.open(el);
    xtermTerminal.writeln('\x1b[1;36m  ANK Terminal\x1b[0m');
    xtermTerminal.writeln('\x1b[90m  Connecting to: ' + currentContainer.name + '...\x1b[0m\r\n');
    xtermTerminal.focus();
    const wsUrl = wsProtocol+'//'+location.host+'/ws/terminal/'+currentContainer.name+'?cols='+(xtermTerminal.cols||80)+'&rows='+(xtermTerminal.rows||24)+'&token='+encodeURIComponent(ankToken);
    xtermWs = new WebSocket(wsUrl);
    xtermWs.onopen = () => { xtermTerminal.focus(); };
    xtermWs.onmessage = ev => { xtermTerminal.write(ev.data); };
    xtermWs.onclose = () => { xtermTerminal.writeln('\r\n\x1b[31m[Connection closed]\x1b[0m'); };
    xtermWs.onerror = () => { xtermTerminal.writeln('\r\n\x1b[31m[Connection error]\x1b[0m'); };
    xtermTerminal.onData(data => { if (xtermWs && xtermWs.readyState === WebSocket.OPEN) xtermWs.send(JSON.stringify({ type: 'input', data })); });
    const resize = () => { const rect = el.getBoundingClientRect(); const cols = Math.floor(rect.width/8.4); const rows = Math.floor(rect.height/18); if (cols>0&&rows>0) { xtermTerminal.resize(cols,rows); if (xtermWs&&xtermWs.readyState===WebSocket.OPEN) xtermWs.send(JSON.stringify({type:'resize',cols,rows})); } };
    window.addEventListener('resize', resize);
    setTimeout(resize, 100);
  } catch(e) { el.innerHTML = '<div style="color:var(--danger);padding:20px">xterm.js failed to load</div>'; }
}

/* ═══════ FILE EXPLORER ═══════ */
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
  if (!el) return;
  const parts = fileCurrentPath.split('/').filter(Boolean);
  let html = '<span class="breadcrumb-item" data-path="/">/</span>';
  let accumulated = '';
  parts.forEach(part => {
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
  if (!listEl) return;
  listEl.innerHTML = '<div class="file-empty"><i class="bi bi-hourglass-split"></i> Loading...</div>';
  try {
    const data = await api('GET', `/containers/${fileContainerName}/files?path=${encodeURIComponent(fileCurrentPath)}`);
    if (!data.items || data.items.length === 0) { listEl.innerHTML = '<div class="file-empty"><i class="bi bi-folder"></i> Empty directory</div>'; return; }
    let html = '<div class="file-row file-header"><div class="file-name">Name</div><div class="file-size">Size</div><div class="file-date">Modified</div><div></div></div>';
    const dirs = data.items.filter(i => i.type === 'directory');
    const files = data.items.filter(i => i.type === 'file');
    [...dirs, ...files].forEach(item => {
      const onclick = item.type === 'directory' ? `fileNavigate('${esc(item.path)}')` : `openFile('${esc(item.path)}')`;
      const dlBtn = item.type === 'file' ? `<button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();downloadFile('${esc(item.path)}')" title="Download"><i class="bi bi-download"></i></button>` : '';
      html += `<div class="file-row" onclick="${onclick}">
        ${getFileIcon(item)}
        <div class="file-name">${esc(item.name)}</div>
        <div class="file-size">${formatSize(item.size)}</div>
        <div class="file-date">${formatDate(item.modified)}</div>
        <div class="file-actions-row">
          ${dlBtn}
          <button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();renameFilePrompt('${esc(item.path)}')" title="Rename"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-sm btn-ghost" onclick="event.stopPropagation();deleteFilePrompt('${esc(item.path)}')" title="Delete" style="color:var(--danger)"><i class="bi bi-trash3"></i></button>
        </div>
      </div>`;
    });
    listEl.innerHTML = html;
  } catch (e) { listEl.innerHTML = `<div class="file-empty"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message || 'Failed to load files')}</div>`; }
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
  const editor = document.getElementById('file-editor');
  const list = document.getElementById('file-list');
  if (editor) editor.classList.add('hidden');
  if (list && list.parentElement) list.parentElement.classList.remove('hidden');
}

async function saveFile() {
  const ta = document.getElementById('file-editor-content');
  const path = ta.dataset.path;
  if (ta.dataset.binary === '1') { toast('Cannot edit binary files', 'warning'); return; }
  try { await api('POST', `/containers/${fileContainerName}/files/write`, { path, content: ta.value }); toast('File saved', 'success'); } catch (e) { toast(e.message || 'Failed to save', 'error'); }
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
  try { await api('POST', `/containers/${fileContainerName}/files/rename`, { old_path: oldPath, new_path: dir + '/' + newName }); toast('Renamed', 'success'); loadFiles(); } catch (e) { toast(e.message || 'Failed to rename', 'error'); }
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
  api('POST', `/containers/${fileContainerName}/files/write`, { path, content: '' }).then(() => { toast('File created', 'success'); loadFiles(); }).catch(e => toast(e.message || 'Failed', 'error'));
}

async function createNewDir() {
  const name = await inputModal('New Folder', 'New folder name:');
  if (!name) return;
  const path = fileCurrentPath === '/' ? '/' + name : fileCurrentPath + '/' + name;
  api('POST', `/containers/${fileContainerName}/files/mkdir`, { path }).then(() => { toast('Folder created', 'success'); loadFiles(); }).catch(e => toast(e.message || 'Failed', 'error'));
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

/* ═══════ TASK MANAGER ═══════ */
async function loadTaskManager() {
  if (!currentContainer) return;
  const el = document.getElementById('taskmanager-services');
  if (!el) return;
  el.innerHTML = '<div class="empty-state">Loading services...</div>';
  try {
    const data = await api('GET', `/containers/${currentContainer.name}/services`);
    const services = data.services || [];
    if (services.length === 0) { el.innerHTML = '<div class="empty-state" style="padding:20px"><p style="color:var(--text-muted)">No services configured</p></div>'; return; }
    el.innerHTML = services.map(svc => {
      const isRunning = svc.status === 'running';
      return `<div class="service-item">
        <div class="service-info">
          <div class="service-dot ${isRunning?'running':'stopped'}"></div>
          <div><div class="service-name">${esc(svc.name)} ${svc.enabled?'<span style="color:var(--success);font-size:11px">ON</span>':'<span style="color:var(--text-muted);font-size:11px">OFF</span>'}</div><div class="service-cmd">${esc(svc.cmd||'no command')}</div></div>
        </div>
        <div class="service-actions">
          <button class="btn btn-sm btn-ghost" onclick="taskManagerViewLog('${esc(svc.name)}')" title="View Log"><i class="bi bi-journal-text"></i></button>
          ${isRunning
            ? `<button class="btn btn-sm btn-secondary" onclick="taskManagerServiceAction('${esc(svc.name)}','stop')" title="Stop"><i class="bi bi-stop-fill"></i></button>
               <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','restart')" title="Restart"><i class="bi bi-arrow-clockwise"></i></button>`
            : `<button class="btn btn-sm btn-success" onclick="taskManagerServiceAction('${esc(svc.name)}','start')" title="Start"><i class="bi bi-play-fill"></i></button>`
          }
          <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','${svc.enabled?'disable':'enable'}')" title="${svc.enabled?'Disable':'Enable'}"><i class="bi bi-${svc.enabled?'pause':'play'}-circle"></i></button>
          <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','delete')" title="Delete" style="color:var(--danger)"><i class="bi bi-trash3"></i></button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = `<div class="empty-state">Failed to load services: ${esc(e.message)}</div>`; }
}

async function taskManagerServiceAction(service, action) {
  if (!currentContainer) return;
  if (action === 'delete') { const ok = await confirmAction('Delete Service', `Delete service "${service}"?`); if (!ok) return; }
  try {
    if (action === 'delete') { await api('DELETE', `/containers/${currentContainer.name}/services/${service}`); toast(`Service "${service}" deleted`, 'success'); }
    else { await api('POST', `/containers/${currentContainer.name}/services/${service}/${action}`); toast(`Service "${service}" ${action}ed`, 'success'); }
    setTimeout(loadTaskManager, 500);
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function taskManagerViewLog(service) {
  if (!currentContainer) return;
  try {
    const data = await api('GET', `/containers/${currentContainer.name}/services/${service}/logs?lines=50`);
    const logs = data.logs || 'No logs for this service';
    openModal(`${service} — Logs`, `<pre style="max-height:400px;overflow:auto;font-size:12px;font-family:monospace;white-space:pre-wrap;margin:0">${logs.replace(/</g,'&lt;')}</pre>`);
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
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
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ═══════ LOGS ═══════ */
let logsPaused = false;
let logsOffset = 0;
const LOG_POLL_MS = 3000;
let logsTimer = null;

async function loadLogs(append) {
  try {
    const filter = document.getElementById('log-filter')?.value || 'all';
    const logNode = document.getElementById('log-node-selector')?.value || 'local';
    const params = new URLSearchParams({ filter });
    if (append && logsOffset > 0) params.set('offset', logsOffset);
    let data;
    if (logNode && logNode !== 'local') {
      data = await api('GET', `/nodes/${encodeURIComponent(logNode)}/logs?${params}`);
    } else {
      data = await api('GET', `/logs?${params}`);
    }
    const viewer = document.getElementById('log-viewer');
    if (!viewer) return;
    if (!data.lines || data.lines.length === 0) {
      if (!append) viewer.innerHTML = '<div class="log-empty"><i class="bi bi-terminal"></i><p>No logs available</p></div>';
      return;
    }
    if (append) {
      const wasAtBottom = viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 30;
      data.lines.forEach(line => { const div = document.createElement('div'); div.className = 'log-entry'; div.innerHTML = colorizeLog(line); viewer.appendChild(div); });
      if (wasAtBottom) viewer.scrollTop = viewer.scrollHeight;
    } else {
      viewer.innerHTML = data.lines.map(line => `<div class="log-entry">${colorizeLog(line)}</div>`).join('');
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

function startLogsPoll() { if (logsTimer) return; logsTimer = setInterval(() => { if (!logsPaused) loadLogs(true); }, LOG_POLL_MS); }
function stopLogsPoll() { if (logsTimer) { clearInterval(logsTimer); logsTimer = null; } }

document.getElementById('logs-pause-btn')?.addEventListener('click', () => {
  logsPaused = !logsPaused;
  const btn = document.getElementById('logs-pause-btn');
  const viewer = document.getElementById('log-viewer');
  if (logsPaused) { btn.innerHTML = '<i class="bi bi-play-fill"></i> Resume'; viewer?.classList.add('log-paused'); }
  else { btn.innerHTML = '<i class="bi bi-pause-fill"></i> Pause'; viewer?.classList.remove('log-paused'); loadLogs(true); }
});

document.getElementById('logs-clear-btn')?.addEventListener('click', () => {
  document.getElementById('log-viewer').innerHTML = '<div class="log-empty"><i class="bi bi-terminal"></i><p>Logs cleared</p></div>';
  logsOffset = 0;
});

document.getElementById('log-filter')?.addEventListener('change', () => { logsOffset = 0; loadLogs(false); });

/* ═══════ REFRESH TIMER ═══════ */
let refreshSeconds = parseInt(localStorage.getItem('ank_refresh') || '15');
let refreshTimer = null;

function startRefreshTimer() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (refreshSeconds <= 0) return;
  refreshTimer = setInterval(async () => {
    if (!isLoggedIn || document.getElementById('app').classList.contains('hidden') || document.hidden) return;
    try {
      const status = await api('GET', '/status');
      animateCounter('stat-running', status.containers_running || 0);
      animateCounter('stat-stopped', status.containers_stopped || 0);
      animateCounter('stat-total', status.containers_total || 0);
    } catch(e) {}
  }, refreshSeconds * 1000);
}

/* ═══════ CREATE CONTAINER ═══════ */
document.getElementById('btn-create-container')?.addEventListener('click', async () => {
  const sel = document.getElementById('container-image');
  if (sel) {
    let options = '';
    // Fetch images for dropdown
    try {
      const images = await api('GET', '/images/all');
      if (Array.isArray(images) && images.length) {
        options += '<optgroup label="--- Images ---">';
        images.forEach(i => { options += `<option value="${esc(i.name)}">${esc(i.name)}${i.complete ? ' (complete)' : ''}</option>`; });
        options += '</optgroup>';
      }
    } catch(e) {}
    // Hardcoded templates (like FUNCIONAL)
    options += `<optgroup label="--- Templates ---">
      <option value="template:python">Python 3.12 (Alpine + Python)</option>
      <option value="template:nginx">Nginx Static (Web server :8080)</option>
      <option value="template:apache">Apache Static (Web server :9090)</option>
      <option value="template:php">PHP 8.2 (Alpine + PHP :8000)</option>
      <option value="template:node">Node.js 20 (Alpine + Node :3000)</option>
    </optgroup>`;
    sel.innerHTML = options || '<option value="">No images available</option>';
  }
  // Populate node selector
  try {
    const d = await api('GET', '/system/dashboard');
    const nodes = (d.nodes || []).filter(n => n.status === 'online');
    const nodeSel = document.getElementById('container-target-node');
    if (nodeSel && nodes.length) {
      let nodeOpts = '<option value="local">Local</option>';
      nodes.forEach(n => { nodeOpts += `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`; });
      nodeSel.innerHTML = nodeOpts;
    }
  } catch(e) {}
  document.getElementById('create-modal-overlay').classList.add('active');
});

document.getElementById('create-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('container-name').value;
  const imageVal = document.getElementById('container-image').value;
  const nodeId = document.getElementById('container-target-node')?.value || 'local';
  const isRemote = nodeId !== 'local';
  if (imageVal.startsWith('template:')) {
    const templateId = imageVal.replace('template:', '');
    const rootPass = document.getElementById('container-root-password').value || 'ank123';
    try {
      if (isRemote) {
        toast(`Deploying on remote...`, 'info');
        await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name, image: templateId, root_password: rootPass });
      } else {
        toast(`Deploying as "${name}"...`, 'info');
        await api('POST', '/images/deploy', { template: templateId, name, root_password: rootPass });
        pollContainerStatus(name, 0);
      }
      closeCreateModal();
      toast(`Template deployed as "${name}"`, 'success');
      loadContainers();
    } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    return;
  }
  const data = {
    name, image: imageVal,
    root_password: document.getElementById('container-root-password').value,
    autostart: document.getElementById('container-autostart').checked,
    policies: { inter_container_p2p: document.getElementById('policy-p2p').checked, allow_host_access: document.getElementById('policy-host').checked, allow_internet: document.getElementById('policy-internet').checked },
    resources: { memory_limit: document.getElementById('mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('cpu-limit').value) }
  };
  const sshPortVal = document.getElementById('container-ssh-port').value;
  if (sshPortVal) data.ssh_port = parseInt(sshPortVal);
  try {
    if (isRemote) { await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, data); }
    else { await api('POST', '/containers', data); }
    closeCreateModal();
    toast(`Container "${data.name}" created`, 'success');
    loadContainers();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
});

/* ═══════ NOTCH HOVER PREVIEW ═══════ */
const notchPreview = document.getElementById('notch-preview');
let notchPreviewTimer = null;
let notchPreviewHideTimer = null;

const pageIcons = { dashboard:'bi-grid-1x2', containers:'bi-box-seam', images:'bi-hdd-stack', nodes:'bi-hdd-network', stacks:'bi-layers', backups:'bi-cloud-arrow-up', networks:'bi-globe2', logs:'bi-journal-text', settings:'bi-gear', shell:'bi-terminal' };
const pageNames = { dashboard:'Dashboard', containers:'Containers', images:'Images', nodes:'Nodes', stacks:'Stacks', backups:'Backups', networks:'Networks', logs:'Logs', settings:'Settings', shell:'Shell' };

async function loadNotchPreview(page) {
  let html = `<div class="np-header"><i class="bi ${pageIcons[page]||''}"></i><span>${pageNames[page]||page}</span><span class="np-goto" onclick="notchPreviewHide();navigateTo('${page}')" title="Open ${pageNames[page]}"><i class="bi bi-arrow-up-right"></i></span></div>`;
  try {
    if (page === 'containers') {
      const c = await api('GET', '/containers/all');
      if (!c.length) { html += '<div class="np-empty">No containers</div>'; }
      else { html += c.map(x => {
        const color = x.status === 'running' ? 'var(--success)' : x.status === 'building' ? 'var(--warning)' : 'var(--text-muted)';
        return `<div class="np-row"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(x.name)}</span><span class="badge badge-neutral" style="font-size:9px">${x.status}</span></div>`;
      }).join(''); }
    } else if (page === 'images') {
      const [img, tpl] = await Promise.all([api('GET', '/images/all').catch(()=>[]), api('GET', '/images/templates').catch(()=>({templates:[]}))]);
      if (tpl.templates?.length) {
        html += `<div style="margin-bottom:8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Quick Deploy</div>`;
        html += tpl.templates.map(t => `<div class="np-row"><i class="bi ${t.icon||'bi-box-seam'}" style="color:${t.color||'var(--primary)'};font-size:12px"></i><span class="np-name">${esc(t.name)}</span><span class="template-badge ${t.base_ready?'ready':'pending'}" style="font-size:9px">${t.base_ready?'Ready':'Pull'}</span></div>`).join('');
      }
      if (img.length) {
        html += `<div style="margin:12px 0 8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Ank Images (${img.length})</div>`;
        html += img.map(x => `<div class="np-row"><i class="bi bi-hdd-stack" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(x.name)}</span><span class="text-muted text-sm">${x.size_human||''}</span></div>`).join('');
      }
      if (!img.length && !tpl.templates?.length) html += '<div class="np-empty">No images</div>';
    } else if (page === 'nodes') {
      const d = await api('GET', '/nodes').catch(()=>({nodes:[]}));
      const nodes = d.nodes || [];
      if (!nodes.length) { html += '<div class="np-empty">No nodes</div>'; }
      else { html += nodes.map(n => {
        const color = n.status === 'online' ? 'var(--success)' : 'var(--danger)';
        return `<div class="np-row"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(n.alias||n.ip)}</span><span class="text-muted text-sm">${n.status} · CPU ${Math.round(n.cpu_percent||0)}% · RAM ${(n.mem_used_gb||0).toFixed(1)}GB · ${(n.containers_total||0)} containers</span></div>`;
      }).join(''); }
    } else if (page === 'stacks') {
      const d = await api('GET', '/stacks/all').catch(()=>({stacks:[]}));
      const stacks = d.stacks || [];
      if (!stacks.length) { html += '<div class="np-empty">No stacks</div>'; }
      else { html += stacks.map(s => {
        const running = (s.containers||[]).filter(c=>c.status==='running').length;
        const total = (s.containers||[]).length;
        return `<div class="np-row"><i class="bi bi-layers" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(s.name)}</span><span class="text-muted text-sm">${running}/${total} · LB ${s.port||s.lb_port||'-'}</span></div>`;
      }).join(''); }
    } else if (page === 'networks') {
      const nets = await api('GET', '/networks').catch(()=>[]);
      if (!nets.length) { html += '<div class="np-empty">No networks</div>'; }
      else { html += nets.map(n => `<div class="np-row"><i class="bi bi-globe2" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(n.name)}</span><span class="text-muted text-sm">${n.mode} · ${n.subnet||''} GW:${n.gateway||''} · NAT:${n.nat?'On':'Off'} · ${(n.containers?.length||0)} containers</span></div>`).join(''); }
    } else if (page === 'dashboard') {
      const [st, info] = await Promise.all([api('GET', '/status').catch(()=>({})), api('GET', '/system/info').catch(()=>({}))]);
      const cpuPct = info.cpu_usage != null ? Math.round(info.cpu_usage) : 0;
      const memT = info.memory?.total_kb || 0;
      const memA = info.memory?.available_kb || 0;
      const memPct = memT > 0 ? Math.round((memT-memA)/memT*100) : 0;
      html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">`;
      html += `<div class="np-row"><span class="dot" style="background:var(--success)"></span><span class="np-name">Running</span><span>${st.containers_running||0}</span></div>`;
      html += `<div class="np-row"><span class="dot" style="background:var(--danger)"></span><span class="np-name">Stopped</span><span>${st.containers_stopped||0}</span></div>`;
      html += `<div class="np-row"><span class="dot" style="background:var(--primary)"></span><span class="np-name">CPU</span><span>${cpuPct}%</span></div>`;
      html += `<div class="np-row"><span class="dot" style="background:var(--success)"></span><span class="np-name">RAM</span><span>${memPct}%</span></div>`;
      html += `</div>`;
      html += `<div style="margin-bottom:8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Device</div>`;
      html += `<div class="np-row"><i class="bi bi-phone" style="color:var(--primary);font-size:12px"></i><span class="np-name">${esc(info.device||'-')}</span><span class="text-muted text-sm">Kernel: ${esc(info.kernel||'-')}</span></div>`;
      const bat = info.battery;
      if (bat != null && bat >= 0) html += `<div class="np-row"><i class="bi bi-battery-half" style="color:var(--success);font-size:12px"></i><span class="np-name">Battery</span><span>${bat}%</span></div>`;
      const containers = await api('GET', '/containers/all').catch(()=>[]);
      if (containers.length) {
        html += `<div style="margin:12px 0 8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Containers (${containers.length})</div>`;
        html += containers.slice(0, 8).map(x => {
          const color = x.status === 'running' ? 'var(--success)' : x.status === 'building' ? 'var(--warning)' : 'var(--text-muted)';
          return `<div class="np-row"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(x.name)}</span><span class="badge badge-neutral" style="font-size:9px">${x.status}</span></div>`;
        }).join('');
        if (containers.length > 8) html += `<div class="np-empty">+${containers.length - 8} more</div>`;
      }
    } else if (page === 'settings') {
      html += `<div class="np-row"><i class="bi bi-person-gear" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Account</span><span class="text-muted text-sm">Change password</span></div>`;
      html += `<div class="np-row"><i class="bi bi-server" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Server</span><span class="text-muted text-sm">Bind, refresh, autostart</span></div>`;
      html += `<div class="np-row"><i class="bi bi-diagram-3" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Remote & SSH</span><span class="text-muted text-sm">Management, port</span></div>`;
      html += `<div class="np-row"><i class="bi bi-info-circle" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">About</span><span class="text-muted text-sm">Cache, storage</span></div>`;
      html += `<div class="np-row"><i class="bi bi-exclamation-triangle" style="color:var(--danger);font-size:12px"></i><span class="np-name" style="color:var(--danger)">Danger Zone</span><span class="text-muted text-sm">Restart, uninstall</span></div>`;
    } else if (page === 'logs') {
      html += `<div class="np-row"><i class="bi bi-terminal" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Live Log Viewer</span><span class="text-muted text-sm">Colorize · Pause · Filter</span></div>`;
      html += `<div class="np-row"><i class="bi bi-funnel" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Filter: All / Info / Warn / Error</span></div>`;
      html += `<div class="np-row"><i class="bi bi-arrow-clockwise" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Auto-refresh every 3s</span></div>`;
    } else if (page === 'shell') {
      html += `<div class="np-row"><i class="bi bi-terminal" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Core Shell</span><span class="text-muted text-sm">WebSocket terminal</span></div>`;
      html += `<div class="np-row"><i class="bi bi-hdd-network" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Select node (local + remotos)</span></div>`;
    } else if (page === 'backups') {
      const d = await api('GET', '/backups').catch(()=>({routines:[]}));
      const r = d.routines || [];
      if (!r.length) { html += '<div class="np-empty">No backups</div>'; }
      else { html += r.map(b => {
        const lastRun = b.last_run ? new Date(b.last_run).toLocaleString() : 'Never';
        const statusColor = b.last_status === 'success' ? 'var(--success)' : b.last_status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
        return `<div class="np-row"><i class="bi bi-cloud-arrow-up" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(b.name)}</span><span class="text-muted text-sm">${b.schedule||'-'} · Retention: ${b.retention||30}d · Last: ${lastRun}</span><span style="width:6px;height:6px;border-radius:50%;background:${statusColor};flex-shrink:0"></span></div>`;
      }).join(''); }
    }
  } catch(e) { html += `<div class="np-empty">Failed to load</div>`; }
  return html;
}

document.querySelectorAll('.notch-item').forEach(item => {
  const page = item.dataset.page;
  item.addEventListener('mouseenter', () => {
    if (notchPreviewHideTimer) { clearTimeout(notchPreviewHideTimer); notchPreviewHideTimer = null; }
    const isOpen = notchPreview.classList.contains('active');
    if (isOpen) {
      loadNotchPreview(page).then(html => { notchPreview.innerHTML = html; });
    } else {
      notchPreviewTimer = setTimeout(async () => {
        notchPreview.innerHTML = await loadNotchPreview(page);
        notchPreview.classList.add('active');
      }, 1500);
    }
  });
  item.addEventListener('mouseleave', () => {
    if (notchPreviewTimer) { clearTimeout(notchPreviewTimer); notchPreviewTimer = null; }
    notchPreviewHideTimer = setTimeout(() => {
      if (!notchPreview.matches(':hover')) notchPreview.classList.remove('active');
    }, 300);
  });
});

notchPreview.addEventListener('mouseenter', () => { if (notchPreviewHideTimer) { clearTimeout(notchPreviewHideTimer); notchPreviewHideTimer = null; } });
notchPreview.addEventListener('mouseleave', () => { notchPreviewHideTimer = setTimeout(() => notchPreview.classList.remove('active'), 200); });
function notchPreviewHide() { notchPreview.classList.remove('active'); }

/* ═══════ FOOTER MODAL ═══════ */
function openFooterModal() {
  openModal('About ANK', `
    <div class="footer-cards">
      <a href="https://linkedin.com/in/andrebarretoit" target="_blank" rel="noopener" class="footer-card">
        <i class="bi bi-linkedin"></i><div class="fc-title">LinkedIn</div><div class="fc-desc">Connect professionally</div>
      </a>
      <a href="https://andrebarreto.work" target="_blank" rel="noopener" class="footer-card">
        <i class="bi bi-globe2"></i><div class="fc-title">Portfolio</div><div class="fc-desc">View projects & work</div>
      </a>
    </div>
    <div style="text-align:center;margin-top:20px"><span class="text-sm text-muted">ANK · Android Konteiner v2.0.0</span></div>
  `);
}

/* ═══════ INIT ═══════ */
if (isLoggedIn) { showApp(); detectWsProtocol().then(() => startRefreshTimer()); }
