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
document.getElementById('modal-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });

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
  if (page === 'settings') loadSettings();
  if (page === 'shell') initCoreTerminal();
}

document.querySelectorAll('.notch-item, .mobile-bar-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();
    navigateTo(item.dataset.page);
  });
});

document.getElementById('mobile-more-btn')?.addEventListener('click', () => {
  document.getElementById('mobile-expanded')?.classList.toggle('active');
});

/* ═══════ LOGIN ═══════ */
document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const pass = document.getElementById('login-password').value;
  const btn = document.getElementById('login-btn');
  try {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
      body: JSON.stringify({ password: pass })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Login failed');
    ankToken = data.token;
    localStorage.setItem('ank_token', ankToken);
    isLoggedIn = true;
    showApp();
  } catch (e) {
    toast(e.message || 'Invalid password', 'error');
  }
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
    const images = await api('GET', '/images').catch(() => []);
    animateCounter('stat-images', Array.isArray(images) ? images.length : 0);
    const cpuPct = info.cpu_usage != null ? Math.round(info.cpu_usage) : 0;
    const memT = info.memory?.total_kb || 0;
    const memA = info.memory?.available_kb || 0;
    const memPct = memT > 0 ? Math.round((memT - memA) / memT * 100) : 0;
    const disk = status.disk || {};
    const diskPct = disk.total > 0 ? Math.round((disk.used_num || 0) / (disk.total_num || 1) * 100) : 0;
    setGauge('gauge-cpu', cpuPct, 'gauge-cpu-text');
    setGauge('gauge-ram', memPct, 'gauge-ram-text');
    setGauge('gauge-disk', diskPct, 'gauge-disk-text');
    renderDashboardContainers();
    renderDashboardNodes();
  } catch (e) { console.error('Dashboard load failed:', e); }
}

function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = parseInt(el.textContent) || 0;
  if (start === target) { el.textContent = target; return; }
  const duration = 600;
  const startTime = performance.now();
  function tick(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function setGauge(id, pct, textId) {
  const circle = document.getElementById(id);
  const text = document.getElementById(textId);
  if (!circle || !text) return;
  const circumference = 226.2;
  circle.style.strokeDashoffset = circumference - (circumference * pct / 100);
  text.textContent = pct + '%';
  if (pct > 80) circle.classList.add('red');
  else if (pct > 60) circle.classList.add('yellow');
}

async function renderDashboardContainers() {
  const el = document.getElementById('dashboard-containers');
  if (!el) return;
  try {
    const containers = await api('GET', '/containers/all');
    if (!containers || !containers.length) { el.innerHTML = '<div class="empty-state"><p>No containers yet</p></div>'; return; }
    el.innerHTML = '<div class="table-container"><table><thead><tr><th>Name</th><th>Status</th><th>Image</th><th></th></tr></thead><tbody>' +
      containers.map(c => {
        const s = c.status;
        const bc = s === 'running' ? 'badge-success' : s === 'building' ? 'badge-warning' : s === 'failed' ? 'badge-danger' : 'badge-neutral';
        const node = c.node && c.node !== 'local' ? `<span class="badge badge-info" style="margin-left:6px;font-size:10px">${esc(c.node_alias||c.node.slice(0,8))}</span>` : '';
        return `<tr onclick="showContainerDetail('${esc(c.name)}','${c.node||'local'}')" style="cursor:pointer">
          <td><i class="bi bi-box-seam" style="color:var(--accent);margin-right:8px"></i>${esc(c.name)}${node}</td>
          <td><span class="badge ${bc}">${s==='building'?'<i class="bi bi-arrow-repeat spin"></i> ':''}${s}</span></td>
          <td class="text-muted text-sm">${esc(c.template_name||c.image||'-')}</td>
          <td>${s==='running'?`<button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();stopContainer('${esc(c.name)}')"><i class="bi bi-stop-fill"></i></button>`:`<button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();startContainer('${esc(c.name)}')"><i class="bi bi-play-fill"></i></button>`}</td>
        </tr>`;
      }).join('') + '</tbody></table></div>';
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load containers</p></div>'; }
}

async function renderDashboardNodes() {
  const card = document.getElementById('cluster-card');
  const info = document.getElementById('cluster-info');
  if (!card || !info) return;
  try {
    const dashboard = await api('GET', '/system/dashboard');
    animateCounter('stat-nodes', (dashboard.nodes || []).length);
    if (!dashboard.is_manager || !dashboard.nodes || !dashboard.nodes.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const nodes = dashboard.nodes;
    info.innerHTML = nodes.map(n => {
      const color = n.status === 'online' ? 'var(--success)' : 'var(--danger)';
      return `<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;${n.status==='online'?'box-shadow:0 0 6px '+color:''}"></span>
        <div style="flex:1"><strong>${esc(n.alias||n.ip)}</strong><span class="text-muted text-sm" style="margin-left:8px">${n.status}</span></div>
        <span class="text-sm text-muted">CPU ${Math.round(n.cpu_percent||0)}% · RAM ${(n.mem_used_gb||0).toFixed(1)}/${(n.mem_total_gb||0).toFixed(1)} GB</span>
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
  if (!containers.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-box-seam"></i><h3>No containers</h3><p>Create your first container to get started</p></div>'; return; }
  el.innerHTML = containers.map(c => {
    const name = c.name || '';
    const node = c.node || 'local';
    const isRemote = node !== 'local';
    const s = c.status;
    const bc = s === 'running' ? 'badge-success' : s === 'building' ? 'badge-warning' : s === 'failed' ? 'badge-danger' : 'badge-neutral';
    const nodeLabel = c.node_alias || (isRemote ? node.slice(0,8) : '');
    const nodeTag = nodeLabel ? `<span class="badge badge-info" style="margin-left:6px;font-size:10px">${esc(nodeLabel)}</span>` : '';
    const isBuilding = s === 'building';
    const isRunning = s === 'running';
    return `<div class="container-card ${isBuilding?'building':''}" data-name="${esc(name)}" data-node="${node}" onclick="showContainerDetail('${esc(name)}','${node}')">
      <div class="card-top"><span class="card-name"><i class="bi bi-box-seam" style="color:var(--accent)"></i>${esc(name)}${nodeTag}</span>
        <span class="badge ${bc}">${isBuilding?'<i class="bi bi-arrow-repeat spin"></i> ':''}${s}</span></div>
      <div class="card-meta"><span><i class="bi bi-image"></i> ${esc(c.template_name||c.image||'-')}</span></div>
      <div class="card-actions">
        ${isRunning ? `<button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();stopContainer('${esc(name)}')" title="Stop"><i class="bi bi-stop-fill"></i></button>` : ''}
        ${!isRunning && !isBuilding ? `<button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();startContainer('${esc(name)}')" title="Start"><i class="bi bi-play-fill"></i></button>` : ''}
        <button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();restartContainer('${esc(name)}')" title="Restart"><i class="bi bi-arrow-repeat"></i></button>
        <button class="btn btn-icon btn-ghost sm" onclick="event.stopPropagation();deleteContainer('${esc(name)}')" title="Delete" style="color:var(--danger)"><i class="bi bi-trash3"></i></button>
      </div></div>`;
  }).join('');
}

async function startContainer(name) { setContainerLoading(name,'start'); try { await api('POST',`/containers/${name}/start`); toast(`Starting "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function stopContainer(name) { setContainerLoading(name,'stop'); try { await api('POST',`/containers/${name}/stop`); toast(`Stopping "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function restartContainer(name) { setContainerLoading(name,'restart'); try { await api('POST',`/containers/${name}/restart`); toast(`Restarting "${name}"...`,'info'); pollContainerStatus(name,0); } catch(e) { toast(`Failed: ${e.message}`,'error'); clearContainerLoading(name); } }
async function deleteContainer(name) { const ok = await confirmAction('Delete Container',`Delete "${name}"?`); if (!ok) return; try { await api('DELETE',`/containers/${name}`); toast(`Deleted "${name}"`,'success'); loadContainers(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

let containerBusy = {};
function setContainerLoading(name, action) { containerBusy[name] = action; document.querySelectorAll(`.container-card[data-name="${name}"] button`).forEach(b => b.disabled = true); }
function clearContainerLoading(name) { delete containerBusy[name]; document.querySelectorAll(`.container-card[data-name="${name}"] button`).forEach(b => b.disabled = false); }

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

let currentContainer = null;
async function showContainerDetail(name, nodeId) {
  try {
    const isRemote = nodeId && nodeId !== 'local';
    let c;
    if (isRemote) { c = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`); }
    else { c = await api('GET', `/containers/${name}`); }
    currentContainer = c;
    currentContainer._nodeId = nodeId || 'local';
    const s = c.status;
    const bc = s === 'running' ? 'badge-success' : s === 'building' ? 'badge-warning' : s === 'failed' ? 'badge-danger' : 'badge-neutral';
    const actionsHtml = isRemote
      ? `<div style="display:flex;gap:8px">
          ${s==='running'?`<button class="btn btn-secondary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','stop')"><i class="bi bi-stop-fill"></i> Stop</button>`:`<button class="btn btn-success btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','start')"><i class="bi bi-play-fill"></i> Start</button>`}
          <button class="btn btn-primary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','restart')"><i class="bi bi-arrow-repeat"></i> Restart</button>
          <button class="btn btn-danger btn-sm" onclick="remoteDeleteContainer('${nodeId}','${esc(name)}')"><i class="bi bi-trash3"></i> Delete</button></div>`
      : `<div style="display:flex;gap:8px">
          ${s==='running'||s==='starting'?`<button class="btn btn-secondary btn-sm" onclick="stopContainer('${esc(name)}')"><i class="bi bi-stop-fill"></i> Stop</button>`:`<button class="btn btn-success btn-sm" onclick="startContainer('${esc(name)}')"><i class="bi bi-play-fill"></i> Start</button>`}
          <button class="btn btn-primary btn-sm" onclick="restartContainer('${esc(name)}')"><i class="bi bi-arrow-repeat"></i> Restart</button>
          <button class="btn btn-danger btn-sm" onclick="deleteContainer('${esc(name)}')"><i class="bi bi-trash3"></i> Delete</button></div>`;

    const logs = isRemote ? (c.log || '') : (await api('GET', `/containers/${name}/logs`).catch(()=>({logs:''}))).logs || '';
    const logText = typeof logs === 'string' ? logs : (Array.isArray(logs) ? logs.join('\n') : '');

    openModal(c.name, `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <span class="badge ${bc}" style="font-size:13px">${s}</span>
        ${actionsHtml}
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:16px">
        <div class="card" style="padding:12px"><div class="text-sm text-muted mb-8">Image</div><div>${esc(c.template_name||c.image||'-')}</div></div>
        <div class="card" style="padding:12px"><div class="text-sm text-muted mb-8">IP Address</div><div class="font-mono">${esc(c.ip_address||'-')}</div></div>
        <div class="card" style="padding:12px"><div class="text-sm text-muted mb-8">Mode</div><div>${esc(c.mode||'-')}</div></div>
        <div class="card" style="padding:12px"><div class="text-sm text-muted mb-8">Memory</div><div>${esc(c.resources?.memory_limit||'-')}</div></div>
      </div>
      <div class="card" style="padding:12px"><div class="text-sm text-muted mb-8">Logs</div><pre style="max-height:200px;overflow:auto;font-size:11px;margin:0;white-space:pre-wrap">${esc(logText||'No logs')}</pre></div>
    `);
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

/* ═══════ IMAGES ═══════ */
async function loadImages() {
  const el = document.getElementById('images-list');
  if (!el) return;
  el.innerHTML = '<div class="skeleton skeleton-card"></div>';
  try {
    const images = await api('GET', '/images/all');
    renderImages(Array.isArray(images) ? images : []);
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

function renderImages(images) {
  const el = document.getElementById('images-list');
  if (!el) return;
  if (!images.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-stack"></i><h3>No images</h3><p>Pull an image to get started</p></div>'; return; }
  el.innerHTML = images.map(img => {
    const nodeLabel = img.node_alias || (img.node && img.node !== 'local' ? img.node.slice(0,8) : '');
    const nodeTag = nodeLabel ? `<span class="badge badge-info" style="font-size:10px">${esc(nodeLabel)}</span>` : '';
    return `<div class="container-card">
      <div class="card-top"><span class="card-name"><i class="bi bi-hdd-stack" style="color:var(--accent)"></i>${esc(img.name)}${nodeTag}</span></div>
      <div class="card-meta"><span>${img.size_human || fmtBytes(img.size||0)}</span></div>
    </div>`;
  }).join('');
}

async function pullImage() {
  const result = await customModal('Pull Image', [
    { id: 'version', label: 'Alpine Version', type: 'select', options: '<option value="3.20">Alpine 3.20</option><option value="3.19">Alpine 3.19</option><option value="3.18">Alpine 3.18</option>' }
  ]);
  if (!result) return;
  try { toast('Pulling image...', 'info'); await api('POST', '/images/pull', { version: result.version }); toast('Image pulled', 'success'); loadImages(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deployTemplate(id) {
  const result = await customModal('Deploy Template', [
    { id: 'name', label: 'Container Name', type: 'text' },
    { id: 'root_password', label: 'Root Password', type: 'text', value: 'ank123' }
  ]);
  if (!result) return;
  if (!result.name) { toast('Name required', 'error'); return; }
  try { toast(`Deploying as "${result.name}"...`, 'info'); await api('POST', '/images/deploy', { template: id, name: result.name, root_password: result.root_password }); pollContainerStatus(result.name, 0); loadContainers(); } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-pull-image')?.addEventListener('click', pullImage);

/* ═══════ NODES ═══════ */
async function loadNodes() {
  const el = document.getElementById('nodes-list');
  if (!el) return;
  el.innerHTML = '<div class="skeleton skeleton-card"></div>';
  try {
    const data = await api('GET', '/nodes');
    const nodes = data.nodes || [];
    if (!nodes.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-hdd-network"></i><h3>No nodes</h3><p>Add a remote ANK device</p></div>'; return; }
    el.innerHTML = nodes.map(n => {
      const color = n.status === 'online' ? 'var(--success)' : n.status === 'pending' ? 'var(--warning)' : 'var(--danger)';
      const label = n.status === 'online' ? 'Online' : n.status === 'pending' ? 'Pending' : 'Offline';
      const isOnline = n.status === 'online';
      return `<div class="node-card" onclick="openNodeDetail('${esc(n.id)}','${esc(n.alias||n.ip)}','${esc(n.status)}')">
        <div class="node-header">
          <div class="node-avatar"><i class="bi bi-hdd-network"></i></div>
          <div class="node-info"><div class="node-name">${esc(n.alias||n.ip)}</div><div class="node-ip">${esc(n.ip||'')}</div></div>
          <span class="badge ${n.status==='online'?'badge-success':n.status==='pending'?'badge-warning':'badge-danger'}">${label}</span>
        </div>
        <div class="node-stats">
          <div class="node-stat"><div class="node-stat-value">${isOnline?Math.round(n.cpu_percent||0)+'%':'-'}</div><div class="node-stat-label">CPU</div></div>
          <div class="node-stat"><div class="node-stat-value">${isOnline?(n.mem_used_gb||0).toFixed(1)+'GB':'-'}</div><div class="node-stat-label">RAM</div></div>
          <div class="node-stat"><div class="node-stat-value">${isOnline?(n.containers_total||0):'-'}</div><div class="node-stat-label">Containers</div></div>
        </div>
      </div>`;
    }).join('');
    updateNodeSelectors(nodes);
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load nodes</p></div>'; }
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

let currentNodeDetailId = null;
async function openNodeDetail(nodeId, name, status) {
  currentNodeDetailId = nodeId;
  openModal(name, '<div class="skeleton skeleton-card"></div>');
  try {
    const [st, sysInfo, containers] = await Promise.all([
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/status`).catch(()=>({})),
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/system/info`).catch(()=>({})),
      api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers`).catch(()=>[])
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
    const contArr = Array.isArray(containers) ? containers : [];

    openModal(name, `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <span class="badge ${status==='online'?'badge-success':'badge-danger'}">${status}</span>
        ${status==='online'?`<button class="btn btn-danger btn-sm" onclick="restartRemoteNode()"><i class="bi bi-arrow-clockwise"></i> Restart Device</button>`:''}
        <button class="btn btn-danger btn-sm" onclick="deleteNode('${esc(nodeId)}')"><i class="bi bi-trash3"></i> Remove</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:16px">
        <div class="card" style="padding:10px"><div class="text-sm text-muted">Device</div><div>${esc(dev)}</div></div>
        <div class="card" style="padding:10px"><div class="text-sm text-muted">CPU</div><div>${esc(cpu)}</div></div>
        <div class="card" style="padding:10px"><div class="text-sm text-muted">Memory</div><div>${esc(mem)}</div></div>
        <div class="card" style="padding:10px"><div class="text-sm text-muted">Battery</div><div>${esc(batteryText)}</div></div>
      </div>
      <div class="card" style="padding:10px;margin-bottom:16px"><div class="text-sm text-muted">Kernel</div><div class="font-mono text-sm">${esc(kernel)}</div></div>
      ${contArr.length ? `<div class="text-sm text-muted mb-8">Containers (${contArr.length})</div>
        <div style="display:flex;flex-direction:column;gap:6px">${contArr.map(c => {
          const sc = c.status==='running'?'badge-success':c.status==='building'?'badge-warning':'badge-neutral';
          return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px">
            <span>${esc(c.name)} <span class="badge ${sc}" style="font-size:10px">${c.status}</span></span>
            <div style="display:flex;gap:4px">
              ${c.status==='running'?`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','stop')"><i class="bi bi-stop-fill"></i></button>`:`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','start')"><i class="bi bi-play-fill"></i></button>`}
            </div></div>`;
        }).join('')}</div>` : '<div class="text-center text-muted">No containers</div>'}
    `);
  } catch (e) { openModal(name, `<div class="text-center" style="color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message)}</div>`); }
}

async function restartRemoteNode() {
  if (!currentNodeDetailId) return;
  const ok = await confirmAction('Restart Device', 'Reboot remote device?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(currentNodeDetailId)}/restart`); toast('Restart sent', 'success'); closeModal(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteNode(id) {
  const ok = await confirmAction('Remove Node', 'Remove this node?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(id)}/delete`); toast('Node removed', 'success'); closeModal(); loadNodes(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

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
document.getElementById('btn-add-node')?.addEventListener('click', sendPairingRequest);

async function remoteContainerAction(nodeId, name, action) {
  try { await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}/${action}`); toast(`${action} sent`, 'success'); loadContainers(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
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
      return `<div class="container-card">
        <div class="card-top"><span class="card-name"><i class="bi bi-layers" style="color:var(--accent)"></i>${esc(s.name)}</span><span class="badge ${bc}">${running}/${total}</span></div>
        <div class="card-meta"><span>Template: ${esc(s.template||'-')}</span></div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

/* ═══════ BACKUPS ═══════ */
async function loadBackups() {
  const el = document.getElementById('backups-list');
  if (!el) return;
  try {
    const data = await api('GET', '/backups');
    const routines = data.routines || [];
    if (!routines.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-cloud-arrow-up"></i><h3>No backups</h3><p>Create a backup routine</p></div>'; return; }
    el.innerHTML = routines.map(r => `<div class="container-card">
      <div class="card-top"><span class="card-name"><i class="bi bi-cloud-arrow-up" style="color:var(--accent)"></i>${esc(r.name)}</span>
        <div style="display:flex;gap:4px"><button class="btn btn-icon btn-ghost sm" onclick="executeBackup('${esc(r.id||r.name)}')" title="Run"><i class="bi bi-play-fill"></i></button>
        <button class="btn btn-icon btn-ghost sm" onclick="deleteBackup('${esc(r.id||r.name)}')" title="Delete" style="color:var(--danger)"><i class="bi bi-trash3"></i></button></div></div>
      <div class="card-meta"><span>Schedule: ${esc(r.schedule||'-')}</span><span>Retention: ${r.retention||30}d</span></div>
    </div>`).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

async function executeBackup(id) { try { toast('Running backup...','info'); await api('POST',`/backups/${encodeURIComponent(id)}/execute`); toast('Backup complete','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }
async function deleteBackup(id) { const ok = await confirmAction('Delete Backup','Delete this routine?'); if(!ok) return; try { await api('POST',`/backups/${encodeURIComponent(id)}/delete`); toast('Deleted','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

document.getElementById('btn-create-backup')?.addEventListener('click', async () => {
  const result = await customModal('Create Backup Routine', [
    { id: 'name', label: 'Routine Name', type: 'text' },
    { id: 'source', label: 'Source Path', type: 'text' },
    { id: 'remote_host', label: 'Remote Host (SSH)', type: 'text' },
    { id: 'schedule', label: 'Schedule (cron)', type: 'text', value: '0 2 * * *' }
  ]);
  if (!result || !result.name) return;
  try { await api('POST', '/backups', { name: result.name, source: result.source, remote_host: result.remote_host, schedule: result.schedule, retention: 30 }); toast('Created','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); }
});

/* ═══════ NETWORKS ═══════ */
async function loadNetworks() {
  const el = document.getElementById('networks-list');
  if (!el) return;
  try {
    const [networks, info] = await Promise.all([api('GET', '/networks'), api('GET', '/networks/info')]);
    if (!networks || !networks.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-globe2"></i><h3>No networks</h3></div>'; return; }
    el.innerHTML = networks.map(net => `<div class="container-card">
      <div class="card-top"><span class="card-name"><i class="bi bi-globe2" style="color:var(--accent)"></i>${esc(net.name)}</span><span class="badge badge-success">${net.mode}</span></div>
      <div class="card-meta"><span>Subnet: ${esc(net.subnet)}</span><span>Gateway: ${esc(net.gateway)}</span><span>NAT: ${net.nat?'On':'Off'}</span></div>
    </div>`).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

/* ═══════ SETTINGS ═══════ */
async function loadSettings() {
  try {
    const cfg = await api('GET', '/config');
    const el = document.getElementById('settings-content');
    if (!el) return;
    el.innerHTML = `
      <div class="card" style="max-width:600px">
        <form id="settings-form">
          <div class="form-group"><label class="form-label">Bind Address</label><input class="form-input" id="set-bind" value="${esc(cfg.bind_address||'0.0.0.0')}"></div>
          <div class="form-group"><label class="form-label">Refresh Interval (s)</label><input class="form-input" id="set-refresh" type="number" value="${cfg.refresh_interval||10}"></div>
          <div class="form-group"><label class="form-label">Node Name</label><input class="form-input" id="set-node-name" value="${esc(cfg.node_name||'')}"></div>
          <div class="form-group"><label class="form-label">Default Container Password</label><input class="form-input" id="set-default-pass" value="${esc(cfg.default_container_password||'ank123')}"></div>
          <div class="flex items-center gap-8 mb-16"><label class="toggle"><input type="checkbox" id="set-autostart" ${cfg.autostart_on_boot!==false?'checked':''}><span class="slider"></span></label><span class="text-sm">Autostart on boot</span></div>
          <div class="flex gap-8"><button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Save</button></div>
        </form>
      </div>`;
    document.getElementById('settings-form').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        await api('POST', '/config', { bind_address: document.getElementById('set-bind').value, refresh_interval: parseInt(document.getElementById('set-refresh').value), autostart_on_boot: document.getElementById('set-autostart').checked, node_name: document.getElementById('set-node-name').value.trim(), default_container_password: document.getElementById('set-default-pass').value.trim() });
        toast('Settings saved', 'success');
      } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
    });
  } catch(e) {}
}

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
  let templates = [];
  try { const t = await api('GET', '/images/templates'); templates = t.templates || []; } catch(e) {}
  const opts = templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
  const result = await customModal('Create Container', [
    { id: 'name', label: 'Container Name', type: 'text' },
    { id: 'template', label: 'Template', type: 'select', options: opts || '<option value="">No templates</option>' },
    { id: 'password', label: 'Root Password', type: 'text', value: 'ank123' }
  ]);
  if (!result || !result.name) return;
  try { toast(`Deploying "${result.name}"...`,'info'); await api('POST', '/images/deploy', { template: result.template, name: result.name, root_password: result.password }); pollContainerStatus(result.name, 0); loadContainers(); } catch(e) { toast(`Failed: ${e.message}`,'error'); }
});

/* ═══════ FOOTER MODAL ═══════ */
function openFooterModal() {
  openModal('About ANK', `
    <div class="footer-cards">
      <a href="https://linkedin.com/in/andrebarretoit" target="_blank" rel="noopener" class="footer-card">
        <i class="bi bi-linkedin"></i>
        <div class="fc-title">LinkedIn</div>
        <div class="fc-desc">Connect professionally</div>
      </a>
      <a href="https://andrebarreto.work" target="_blank" rel="noopener" class="footer-card">
        <i class="bi bi-globe2"></i>
        <div class="fc-title">Portfolio</div>
        <div class="fc-desc">View projects & work</div>
      </a>
    </div>
    <div style="text-align:center;margin-top:20px">
      <span class="text-sm text-muted">ANK · Android Konteiner v2.0.0</span>
    </div>
  `);
}

/* ═══════ INIT ═══════ */
if (isLoggedIn) { showApp(); detectWsProtocol().then(() => startRefreshTimer()); }
