const API = '/api';
let ankToken = localStorage.getItem('ank_token') || '';
let isLoggedIn = !!ankToken;
let ankLiteMode = false;
let ankModeFeatures = {};

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

function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;') : ''; }
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
      return `<div class="form-group"><label class="form-label">${esc(f.label)}</label><input class="form-input" id="_cm-${f.id}" type="${f.type||'text'}" value="${esc(f.value||'')}" placeholder="${esc(f.placeholder||f.label)}">${f.hint?`<small class="form-hint">${esc(f.hint)}</small>`:''}</div>`;
    }).join('');
    html += `<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn btn-secondary" id="_cm-cancel">Cancel</button><button class="btn btn-primary" id="_cm-ok">OK</button></div>`;
    openModal(title, html);
    const first = document.querySelector('[id^="_cm-"]');
    if (first) setTimeout(() => first.focus(), 50);
    document.getElementById('_cm-ok').onclick = () => {
      const result = {};
      let allFilled = true;
      fields.forEach(f => { result[f.id] = document.getElementById(`_cm-${f.id}`).value.trim(); if (!result[f.id] && !f.optional) allFilled = false; });
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
function closeCreateModal() { closeModalById('create-modal-overlay'); const f = document.getElementById('create-form'); if (f) f.reset(); }

/* ═══════ RESTART PROGRESS MODAL ═══════ */
function showRestartModal(type) {
  const overlay = document.getElementById('restart-modal-overlay');
  const titleEl = document.getElementById('restart-modal-title');
  const stepsEl = document.getElementById('restart-modal-steps');
  const barEl = document.getElementById('restart-progress-bar');
  const pctEl = document.getElementById('restart-progress-pct');
  const statusEl = document.getElementById('restart-modal-status');

  const isServer = type === 'server';
  const steps = isServer
    ? ['Desligando containers...', 'Parando serviços...', 'Reiniciando ANK...', 'Aguardando ANK iniciar...']
    : ['Desligando containers...', 'Parando serviços...', 'Rebootando device...', 'Aguardando device iniciar...'];

  titleEl.textContent = isServer ? 'Reiniciando ANK...' : 'Reiniciando Device...';
  barEl.style.width = '0%';
  pctEl.textContent = '0%';
  statusEl.textContent = '';

  stepsEl.innerHTML = steps.map((s, i) => `
    <div class="restart-step pending" id="restart-step-${i}">
      <div class="restart-step-icon"></div>
      <span>${s}</span>
    </div>
  `).join('');

  overlay.classList.add('active');

  function setStep(idx, state) {
    const el = document.getElementById(`restart-step-${idx}`);
    if (!el) return;
    el.className = `restart-step ${state}`;
  }

  function updateProgress(pct, label) {
    barEl.style.width = pct + '%';
    pctEl.textContent = pct + '%';
    if (label) statusEl.textContent = label;
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  async function pollServerReady(timeoutMs) {
    const start = Date.now();
    const interval = 2000;
    while (Date.now() - start < timeoutMs) {
      try {
        const res = await fetch(`${API}/system/status`, { headers: { 'X-ANK-Client': 'ank-panel' } });
        if (res.ok) return true;
      } catch (e) {}
      await sleep(interval);
    }
    return false;
  }

  async function pollDeviceReady(timeoutMs) {
    const start = Date.now();
    const interval = 5000;
    while (Date.now() - start < timeoutMs) {
      try {
        const res = await fetch(`${API}/system/status`, { headers: { 'X-ANK-Client': 'ank-panel' } });
        if (res.ok) return true;
      } catch (e) {}
      updateProgress(Math.min(90, 50 + Math.round((Date.now() - start) / timeoutMs * 40)), 'Aguardando device...');
      await sleep(interval);
    }
    return false;
  }

  (async () => {
    try {
      // Step 1: Desligando containers
      setStep(0, 'active');
      updateProgress(10, 'Desligando containers...');
      await sleep(1000);
      setStep(0, 'done');

      // Step 2: Parando serviços
      setStep(1, 'active');
      updateProgress(25, 'Parando serviços...');
      await sleep(1000);
      setStep(1, 'done');

      // Step 3: Reiniciando
      setStep(2, 'active');
      updateProgress(40, isServer ? 'Reiniciando ANK...' : 'Rebootando device...');
      if (isServer) {
        api('POST', '/ank-manager/restart-server').catch(() => {});
      } else {
        api('POST', '/ank-manager/restart-device').catch(() => {});
      }
      await sleep(2000);
      setStep(2, 'done');

      // Step 4: Aguardando
      setStep(3, 'active');
      updateProgress(50, isServer ? 'Aguardando ANK iniciar...' : 'Aguardando device iniciar...');
      const timeoutMs = isServer ? 60000 : 300000;
      const ready = await (isServer ? pollServerReady(timeoutMs) : pollDeviceReady(timeoutMs));

      if (ready) {
        setStep(3, 'done');
        updateProgress(100, isServer ? 'ANK reiniciado com sucesso!' : 'Device reiniciado!');
        titleEl.textContent = isServer ? 'ANK Reiniciado!' : 'Device Reiniciado!';
        statusEl.textContent = 'Recarregando página...';
        await sleep(1500);
        location.reload();
      } else {
        setStep(3, 'error');
        updateProgress(100, 'Tempo esgotado — verifique manualmente');
        statusEl.innerHTML = '<span style="color:var(--danger)">Timeout. A página recarregará em 5s.</span>';
        await sleep(5000);
        location.reload();
      }
    } catch (e) {
      statusEl.innerHTML = `<span style="color:var(--danger)">Erro: ${esc(e.message)}</span>`;
      await sleep(3000);
      overlay.classList.remove('active');
    }
  })();
}

function refreshTab(btn, loadFn) {
  const icon = btn.querySelector('i');
  if (icon) icon.classList.add('spin');
  btn.disabled = true;
  const done = () => {
    if (icon) icon.classList.remove('spin');
    btn.disabled = false;
    btn.classList.add('refresh-pulse');
    setTimeout(() => btn.classList.remove('refresh-pulse'), 600);
  };
  const p = loadFn();
  if (p && typeof p.then === 'function') {
    p.then(done).catch(done);
  } else {
    setTimeout(done, 500);
  }
}

/* ═══════ NAVIGATION ═══════ */
let _currentPage = 'dashboard';

function hideTerminalContainers() {
  const shellTerminalContainer = document.querySelector('#page-shell .terminal-container');
  if (shellTerminalContainer) shellTerminalContainer.style.display = 'none';
}

function showTerminalContainers() {
  const shellTerminalContainer = document.querySelector('#page-shell .terminal-container');
  if (shellTerminalContainer) shellTerminalContainer.style.display = '';
}

function navigateTo(page) {
  _formDirty = false;
  const prevPage = _currentPage;
  _currentPage = page;

  if (prevPage === 'shell' && page !== 'shell') hideTerminalContainers();
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.notch-item, .mobile-bar-item').forEach(i => i.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');
  document.querySelectorAll(`[data-page="${page}"]`).forEach(i => i.classList.add('active'));
  document.getElementById('mobile-expanded')?.classList.remove('active');
  if (page === 'dashboard') loadDashboard();
  if (page === 'containers') loadContainers();
  if (page === 'images') {
    showImageSection('quick-deploy');
    loadImages().then(() => {
      const sel = document.querySelector('#images-list .split-list-card.selected');
      if (!sel) showImageSection('quick-deploy');
    });
  }
  if (page === 'nodes') { loadNodes(); loadPairingRequests(); }
  if (page === 'stacks') loadStacks();
  if (page === 'backups') loadBackups();
  if (page === 'networks') loadNetworks();
  if (page === 'logs') { logsOffset = 0; loadLogs(false); startLogsPoll(); }
  if (page === 'settings') loadSettings();
  if (page === 'shell') {
    showTerminalContainers();
    loadNodesForShellSelector();
    initCoreTerminal();
  }
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
  loadAll();
}

/* ═══════ LOAD ALL ═══════ */
async function loadAll() {
  try {
    const [containers, images, status, info, mode] = await Promise.all([
      api('GET', '/containers/all').catch(() => []),
      api('GET', '/images/all').catch(() => []),
      api('GET', '/status').catch(() => ({})),
      api('GET', '/system/info').catch(() => ({})),
      api('GET', '/mode').catch(() => ({ lite: false, features: {} }))
    ]);
    ankLiteMode = mode.lite || false;
    ankModeFeatures = mode.features || {};
    if (ankLiteMode) applyLiteOverlay();
    animateCounter('stat-running', status.containers_running || 0);
    animateCounter('stat-stopped', status.containers_stopped || 0);
    animateCounter('stat-total', status.containers_total || 0);
    document.getElementById('dash-uptime').textContent = 'uptime ' + fmtUptime(status.uptime || 0);

    const cpuPct = info.cpu_usage != null ? Math.round(info.cpu_usage) : 0;
    document.getElementById('gauge-cpu-text').textContent = cpuPct + '%';
    document.getElementById('gauge-cpu').style.width = cpuPct + '%';
    document.getElementById('cpu-cores').textContent = (info.cpu_cores || 0) > 0 ? info.cpu_cores + ' cores' : '';
    pushSpark('cpu', cpuPct);
    renderSparkline('spark-cpu', sparkHistory.cpu);

    const memT = info.memory?.total_kb || 0;
    const memA = info.memory?.available_kb || 0;
    const memUsed = memT - memA;
    const memPct = memT > 0 ? Math.round(memUsed / memT * 100) : 0;
    document.getElementById('gauge-ram-text').textContent = memPct + '%';
    document.getElementById('gauge-ram').style.width = memPct + '%';
    document.getElementById('ram-detail').textContent = memT > 0 ? `${fmtBytes(memUsed * 1024)} / ${fmtBytes(memT * 1024)}` : '';
    pushSpark('ram', memPct);
    renderSparkline('spark-ram', sparkHistory.ram);

    const disk = status.disk || {};
    const diskTotal = disk.total || 0;
    const diskUsedNum = disk.used_num || 0;
    const diskPct = diskTotal > 0 ? Math.round(diskUsedNum / diskTotal * 100) : 0;
    document.getElementById('gauge-disk-text').textContent = diskPct + '%';
    document.getElementById('gauge-disk').style.width = diskPct + '%';
    document.getElementById('disk-detail').textContent = diskTotal > 0 ? `${disk.used || '-'} / ${diskTotal} GB` : '';
    pushSpark('disk', diskPct);
    renderSparkline('spark-disk', sparkHistory.disk);

    // Identity
    const cfg = await api('GET', '/config').catch(()=>({}));
    document.getElementById('dash-device-name').textContent = cfg.node_name || info.device || 'ANK Device';
    document.getElementById('info-device').textContent = info.device || '-';
    document.getElementById('info-kernel').textContent = (info.device || '-') + ' \u00b7 ANK node';
    document.getElementById('info-kernel-val').textContent = info.kernel || '-';
    const bat = info.battery;
    document.getElementById('info-battery').textContent = (bat != null && bat >= 0) ? bat + '%' : '-';
    document.getElementById('info-subnet').textContent = (info.network?.subnet || '-') + '/24';

    renderDashboardContainers();
    renderDashboardNodes();
    cachedImages = Array.isArray(images) ? images : [];
    startRefreshTimer();
  } catch (e) { console.error('loadAll failed:', e); }
}

/* ═══════ DASHBOARD ═══════ */
let sparkHistory = { cpu: [], ram: [], disk: [] };
const SPARK_MAX = 10;

function pushSpark(key, val) {
  sparkHistory[key].push(val);
  if (sparkHistory[key].length > SPARK_MAX) sparkHistory[key].shift();
}

function renderSparkline(id, data) {
  const el = document.getElementById(id);
  if (!el || !data.length) return;
  const step = 64 / (SPARK_MAX - 1);
  const points = data.map((v, i) => `${i * step},${22 - (v / 100 * 20)}`).join(' ');
  el.setAttribute('points', points);
}

async function loadDashboard() {
  try {
    const [status, info, cfg, dash] = await Promise.all([api('GET', '/status'), api('GET', '/system/info'), api('GET', '/config').catch(()=>({})), api('GET', '/system/dashboard').catch(()=>null)]);
    animateCounter('stat-running', status.containers_running || 0);
    animateCounter('stat-stopped', status.containers_stopped || 0);
    animateCounter('stat-total', status.containers_total || 0);
    document.getElementById('dash-device-name').textContent = cfg.node_name || info.device || 'ANK Device';
    document.getElementById('dash-uptime').textContent = 'uptime ' + fmtUptime(status.uptime || 0);

    // Identity card
    document.getElementById('info-device').textContent = info.device || '-';
    document.getElementById('info-kernel').textContent = (info.device || '-') + ' \u00b7 ANK node';
    document.getElementById('info-kernel-val').textContent = info.kernel || '-';
    const bat = info.battery;
    document.getElementById('info-battery').textContent = (bat != null && bat >= 0) ? bat + '%' : '-';
    document.getElementById('info-subnet').textContent = (info.network?.subnet || '-') + '/24';

    // CPU — use cluster total if manager, else local
    const cluster = dash?.cluster;
    const totalCores = cluster ? cluster.cpu_cores : (info.cpu_cores || 0);
    const cpuPct = cluster ? Math.round(cluster.cpu_percent) : (info.cpu_usage != null ? Math.round(info.cpu_usage) : 0);
    document.getElementById('cpu-cores').textContent = totalCores > 0 ? totalCores + ' cores' : '';
    document.getElementById('gauge-cpu-text').textContent = cpuPct + '%';
    document.getElementById('gauge-cpu').style.width = cpuPct + '%';
    pushSpark('cpu', cpuPct);
    renderSparkline('spark-cpu', sparkHistory.cpu);

    // RAM — use cluster total if manager
    const ramUsedGB = cluster ? cluster.ram_used_gb : ((info.memory?.total_kb || 0) - (info.memory?.available_kb || 0)) / 1048576;
    const ramTotalGB = cluster ? cluster.ram_total_gb : (info.memory?.total_kb || 0) / 1048576;
    const memPct = ramTotalGB > 0 ? Math.round(ramUsedGB / ramTotalGB * 100) : 0;
    document.getElementById('ram-detail').textContent = ramTotalGB > 0 ? `${ramUsedGB.toFixed(1)} GB / ${ramTotalGB.toFixed(1)} GB` : '';
    document.getElementById('gauge-ram-text').textContent = memPct + '%';
    document.getElementById('gauge-ram').style.width = memPct + '%';
    pushSpark('ram', memPct);
    renderSparkline('spark-ram', sparkHistory.ram);

    // Disk — use cluster total if manager
    const diskUsedGB = cluster ? cluster.disk_used_gb : (status.disk?.used_num || 0);
    const diskTotalGB = cluster ? cluster.disk_total_gb : (status.disk?.total || 0);
    const diskPct = cluster ? Math.round(cluster.disk_percent) : (diskTotalGB > 0 ? Math.round(diskUsedGB / diskTotalGB * 100) : 0);
    document.getElementById('disk-detail').textContent = diskTotalGB > 0 ? `${diskUsedGB.toFixed(1)} GB / ${diskTotalGB.toFixed(1)} GB` : '';
    document.getElementById('gauge-disk-text').textContent = diskPct + '%';
    document.getElementById('gauge-disk').style.width = diskPct + '%';
    pushSpark('disk', diskPct);
    renderSparkline('spark-disk', sparkHistory.disk);

    renderDashboardContainers();
    renderDashboardNodes();
  } catch (e) { console.error('Dashboard load failed:', e); }
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
    if (!containers || !containers.length) { el.innerHTML = '<div class="empty-state" style="padding:30px"><i class="bi bi-box-seam"></i> No containers yet</div>'; return; }
    el.innerHTML = containers.map(c => {
      const s = c.status;
      const statusClass = s === 'running' ? 'running' : s === 'building' ? 'building' : s === 'failed' ? 'failed' : 'stopped';
      const img = c.template_name || c.image || '-';
      const ports = (c.port_mappings || []).map(p => p.host_port).filter(Boolean).join(', ');
      const sshHint = (c.ssh_port && s === 'running') ? `SSH :${c.ssh_port}` : '';
      return `<div class="cbox ${statusClass}" onclick="navigateTo('containers');setTimeout(()=>showContainerDetail('${esc(c.name)}','${c.node||'local'}'),100)">
        <div class="cbox-top"><span class="dot"></span><span class="nm">${esc(c.name)}</span><span class="st">${s}</span></div>
        <div class="cbox-img">${esc(img)}</div>
        <div class="cbox-meta">
          <span><i class="bi bi-hdd-network"></i> ${ports || '\u2014'}</span>
          <span><i class="bi bi-terminal"></i> ${sshHint || '\u2014'}</span>
        </div>
      </div>`;
    }).join('');
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
    const nodes = dashboard.nodes;
    let totalCpu = 0, totalCores = 0, totalMemUsed = 0, totalMemTotal = 0, totalDiskUsed = 0, totalDiskTotal = 0, totalContainers = 0, onlineCount = 0;
    nodes.forEach(n => {
      if (n.status === 'online') {
        onlineCount++;
        totalCpu += n.cpu_percent || 0;
        totalCores += n.cpu_cores || 0;
        totalMemUsed += n.mem_used_gb || 0;
        totalMemTotal += n.mem_total_gb || 0;
        totalDiskUsed += n.disk_used || 0;
        totalDiskTotal += n.disk_total || 0;
        totalContainers += n.containers_total || 0;
      }
    });
    // Add local node stats
    try {
      const localStatus = await api('GET', '/status');
      const localInfo = await api('GET', '/system/info');
      totalCpu += localStatus.cpu_usage || 0;
      totalCores += localStatus.cpu_cores || 0;
      const localMemTotal = (localInfo.memory?.total_kb || 0) / 1048576;
      const localMemAvail = (localInfo.memory?.available_kb || 0) / 1048576;
      totalMemUsed += localMemTotal - localMemAvail;
      totalMemTotal += localMemTotal;
      totalDiskUsed += (localStatus.disk?.used || 0);
      totalDiskTotal += (localStatus.disk?.total || 0);
      totalContainers += (localStatus.containers_total || 0);
      onlineCount++;
    } catch(e) {}
    const avgCpu = onlineCount > 0 ? Math.round(totalCpu / onlineCount) : 0;
    const memPct = totalMemTotal > 0 ? Math.round(totalMemUsed / totalMemTotal * 100) : 0;
    const diskPct = totalDiskTotal > 0 ? Math.round(totalDiskUsed / totalDiskTotal * 100) : 0;

    const clusterStatsHtml = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
      <div class="dash-cluster-stat"><div class="dcs-label">CPU</div><div class="dcs-value">${totalCores} cores</div><div class="dcs-sub">${avgCpu}% avg</div></div>
      <div class="dash-cluster-stat"><div class="dcs-label">Memory</div><div class="dcs-value">${totalMemUsed.toFixed(1)} GB</div><div class="dcs-sub">${memPct}% of ${totalMemTotal.toFixed(1)} GB</div></div>
      <div class="dash-cluster-stat"><div class="dcs-label">Disk</div><div class="dcs-value">${totalDiskUsed.toFixed(0)} GB</div><div class="dcs-sub">${diskPct}% of ${totalDiskTotal.toFixed(0)} GB</div></div>
      <div class="dash-cluster-stat"><div class="dcs-label">Containers</div><div class="dcs-value">${totalContainers}</div><div class="dcs-sub">${onlineCount} nodes online</div></div>
    </div>`;

    const modeBadge = document.getElementById('mode-badge');
    const modeNotice = document.getElementById('mode-notice');
    if (modeBadge && dashboard.mode) {
      modeBadge.textContent = dashboard.mode;
      modeBadge.style.display = '';
    }
    if (modeNotice && dashboard.mode) {
      const notices = {
        shared_host: 'No namespace isolation. Containers share host network and PID.',
        shared_network: 'PID namespace + overlay active. Host networking.',
        isolated: ''
      };
      const msg = notices[dashboard.mode] || '';
      if (msg) { modeNotice.textContent = msg; modeNotice.style.display = ''; }
      else { modeNotice.style.display = 'none'; }
    }

    info.innerHTML = clusterStatsHtml + nodes.map(n => {
      const color = n.status === 'online' ? 'var(--success)' : 'var(--danger)';
      return `<div class="dash-cluster-row">
        <span class="dcl-dot" style="background:${color}"></span>
        <span class="dcl-name">${esc(n.alias||n.ip)}</span>
        <span class="dcl-stats">CPU ${Math.round(n.cpu_percent||0)}% · RAM ${(n.mem_used_gb||0).toFixed(1)}/${(n.mem_total_gb||0).toFixed(1)}GB · ${(n.containers_total||0)} ctrs</span>
      </div>`;
    }).join('');
  } catch (e) { card.style.display = 'none'; }
}

/* ═══════ CONTAINERS ═══════ */
function isTransientStatus(s) { return /ing$/i.test(String(s || '')); }
function containerActionDisabled(s) {
  if (s === 'running') return { start: true, stop: false, restart: false, delete: true, exec: false };
  if (isTransientStatus(s)) return { start: true, stop: true, restart: true, delete: true, exec: true };
  if (s === 'stopped') return { start: false, stop: true, restart: true, delete: false, exec: true };
  if (s === 'failed') return { start: false, stop: true, restart: true, delete: false, exec: true };
  return { start: false, stop: true, restart: true, delete: true, exec: true };
}
let cachedContainers = [];
let containersRenderedOnce = false;
async function loadContainers() {
  const el = document.getElementById('containers-list');
  if (!el) return;
  try {
    const containers = await api('GET', '/containers/all');
    cachedContainers = Array.isArray(containers) ? containers : [];
    if (containersRenderedOnce && cachedContainers.length > 0) {
      updateContainersInPlace(cachedContainers);
    } else {
      el.innerHTML = '';
      renderContainers(cachedContainers, 'all');
      containersRenderedOnce = true;
    }
  } catch (e) { if (!containersRenderedOnce) el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}
function updateContainersInPlace(containers) {
  const el = document.getElementById('containers-list');
  if (!el) return;
  const cards = el.querySelectorAll('.split-list-card');
  const names = Array.from(cards).map(c => c.dataset.name);
  containers.forEach(c => {
    const name = c.name || '';
    const idx = names.indexOf(name);
    const badge = el.querySelector(`.split-list-card[data-name="${CSS.escape(name)}"] .badge`);
    if (badge) {
      const newClass = getStatusBadgeClass(c.status);
      if (badge.className !== `badge ${newClass}`) badge.className = `badge ${newClass} status-badge-animated`;
      const label = badge.textContent;
      const newLabel = getStatusLabel(c.status);
      if (label !== newLabel) badge.textContent = newLabel;
    }
  });
}

function renderContainers(containers, nodeId) {
  const el = document.getElementById('containers-list');
  if (!el) return;
  if (!containers.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-box-seam"></i><h3>No containers</h3><p>Create your first container</p></div>'; return; }
  el.innerHTML = containers.map(c => {
    const name = c.name || '';
    const node = c.node || 'local';
    const s = c.status;
    const bc = getStatusBadgeClass(s);
    const dis = containerActionDisabled(s);
    const nodeTag = node !== 'local' ? `<span class="badge badge-info" style="font-size:9px">${esc(c.node_alias||node.slice(0,6))}</span>` : '';
    const mem = c.stats && c.stats.memory_bytes ? fmtBytes(c.stats.memory_bytes) : '';
    const startDisabled = dis.start;
    const stopDisabled = dis.stop;
    const restartDisabled = dis.restart;
    const deleteDisabled = dis.delete;
    return `<div class="split-list-card" data-name="${esc(name)}" onclick="showContainerDetail('${esc(name)}','${node}')">
      <div class="slc-top"><span class="slc-name"><i class="bi bi-box-seam" style="color:var(--accent)"></i>${esc(name)}${nodeTag}</span><span class="badge ${bc}" style="font-size:10px">${getStatusLabel(s)}</span></div>
      <div class="slc-meta"><span><i class="bi bi-image"></i> ${esc(c.template_name||c.image||'-')}</span><span><i class="bi bi-globe2"></i> ${esc(c.ip_address||'N/A')}</span>${mem?`<span>${mem}</span>`:''}</div>
    </div>`;
  }).join('');
}

let selectedContainerName = null;
let currentContainer = null;
let detailLogTimer = null;

async function showContainerDetail(name, nodeId) {
  if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; }
  closeContainerTerminal();
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
    const isBuilding = s === 'building';
    const isFailed = s === 'failed';
    const dis = containerActionDisabled(s);
    const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
    const host = location.hostname || 'localhost';
    const sshHint = (c.ssh_port && s === 'running') ? `<div class="ssh-hint"><div class="ssh-hint-header"><i class="bi bi-terminal"></i> SSH</div><code class="ssh-hint-cmd">ssh root@${host} -p ${c.ssh_port}</code><button class="btn btn-sm btn-ghost" onclick="copyText(this.previousElementSibling.textContent);toast('Copied!','success')"><i class="bi bi-clipboard"></i></button></div>` : '';

    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-box-seam" style="color:var(--accent)"></i>${esc(c.name)} <span class="badge ${getStatusBadgeClass(s)}" style="font-size:11px">${getStatusLabel(s)}</span></h2>
        <div class="sr-actions">
          ${isRemote ? `
            ${s==='running'||s==='starting'?`<button class="btn btn-secondary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','stop')" ${dis.stop?'disabled':''}><i class="bi bi-stop-fill"></i> Stop</button>`:`<button class="btn btn-success btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','start')" ${dis.start?'disabled':''}><i class="bi bi-play-fill"></i> Start</button>`}
            <button class="btn btn-primary btn-sm" onclick="remoteContainerAction('${nodeId}','${esc(name)}','restart')" ${dis.restart?'disabled':''}><i class="bi bi-arrow-repeat"></i></button>
            <button class="btn btn-danger btn-sm" onclick="remoteDeleteContainer('${nodeId}','${esc(name)}')" ${dis.delete?'disabled':''}><i class="bi bi-trash3"></i></button>
          ` : `
            <button class="btn btn-success btn-sm" id="detail-start" onclick="startContainer('${esc(name)}')" ${dis.start?'disabled':''}><i class="bi bi-play-fill"></i> Start</button>
            <button class="btn btn-secondary btn-sm" id="detail-stop" onclick="stopContainer('${esc(name)}')" ${dis.stop?'disabled':''}><i class="bi bi-stop-fill"></i> Stop</button>
            <button class="btn btn-primary btn-sm" id="detail-restart" onclick="restartContainer('${esc(name)}')" ${dis.restart?'disabled':''}><i class="bi bi-arrow-repeat"></i></button>
            <button class="btn btn-secondary btn-sm" onclick="execInContainer('${esc(name)}')" ${dis.exec||s!=='running'?'disabled':''} title="Run command"><i class="bi bi-terminal"></i> Exec</button>
            <button class="btn btn-danger btn-sm" id="detail-delete" onclick="deleteContainer('${esc(name)}')" ${dis.delete?'disabled':''}><i class="bi bi-trash3"></i></button>
          `}
        </div>
      </div>

      <div class="detail-tabs">
        <div class="detail-tab active" data-dtab="overview"><i class="bi bi-info-circle"></i> Overview</div>
        <div class="detail-tab" data-dtab="terminal"><i class="bi bi-terminal"></i> Terminal</div>
        <div class="detail-tab" data-dtab="files"><i class="bi bi-folder2-open"></i> Files</div>
        <div class="detail-tab" data-dtab="network"><i class="bi bi-hdd-network"></i> Networks</div>
        <div class="detail-tab" data-dtab="backup"><i class="bi bi-cloud-arrow-up"></i> Backup</div>
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
        <div id="container-terminal" style="width:100%;min-height:400px;display:none"></div>
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

      <div class="detail-tab-content" id="dtab-backup">
        <form id="detail-backup-form">
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-cloud-arrow-up"></i> Create Backup Routine</div>
            <div class="form-group"><label class="form-label">Source Path</label><input type="text" class="form-input" id="detail-backup-source" placeholder="/data" value="/data"></div>
            <div class="form-group"><label class="form-label">Remote Host (SSH)</label><input type="text" class="form-input" id="detail-backup-host" placeholder="192.168.1.100"></div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">Remote Path</label><input type="text" class="form-input" id="detail-backup-rpath" value="/backups/ank"></div>
              <div class="form-group"><label class="form-label">SSH Password</label><input type="password" class="form-input" id="detail-backup-pass" placeholder="ssh password"></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label class="form-label">Schedule (cron)</label><input type="text" class="form-input" id="detail-backup-cron" placeholder="0 2 * * *" value="0 2 * * *"></div>
              <div class="form-group"><label class="form-label">Retention (days)</label><input type="number" class="form-input" id="detail-backup-retention" value="30" min="1"></div>
            </div>
          </div>
          <button type="submit" class="btn btn-primary"><i class="bi bi-cloud-arrow-up"></i> Create Backup Routine</button>
        </form>
      </div>

      <div class="detail-tab-content" id="dtab-settings">
        <form id="detail-settings-form">
          <div class="settings-section">
            <div class="settings-section-title"><i class="bi bi-gear"></i> General</div>
            <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="detail-autostart" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-power" style="color:var(--accent)"></i> Autostart on boot</label></div>
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
        const containerTerminalEl = document.getElementById('container-terminal');
        if (tab.dataset.dtab !== 'terminal') {
          closeContainerTerminal();
          if (containerTerminalEl) containerTerminalEl.style.display = 'none';
        }
        if (tab.dataset.dtab === 'terminal' && currentContainer) {
          if (containerTerminalEl) containerTerminalEl.style.display = '';
          initContainerTerminal();
        }
        if (tab.dataset.dtab === 'files' && currentContainer) {
          if (currentContainer.status !== 'running') {
            const fileContent = document.getElementById('dtab-files');
            if (fileContent) fileContent.innerHTML = '<div style="text-align:center;padding:40px 20px;color:var(--text-muted)"><i class="bi bi-folder2-open" style="font-size:2rem;display:block;margin-bottom:12px;opacity:0.3"></i><div style="font-size:13px">Start the container to access its filesystem</div></div>';
            return;
          }
          fileContainerName = currentContainer.name; fileCurrentPath = '/'; closeEditor(); loadFiles();
        }
        if (tab.dataset.dtab === 'services' && currentContainer) loadTaskManager();
      });
    });

    // Populate settings form
    document.getElementById('detail-autostart').checked = c.autostart || false;
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

    // Backup form handler
    document.getElementById('detail-backup-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentContainer) return;
      const routineName = `${currentContainer.name}-backup`;
      try {
        await api('POST', '/backups', {
          name: routineName,
          source: document.getElementById('detail-backup-source')?.value || '/data',
          remote_host: document.getElementById('detail-backup-host')?.value || '',
          remote_path: document.getElementById('detail-backup-rpath')?.value || '/backups/ank',
          ssh_user: 'root',
          ssh_pass: document.getElementById('detail-backup-pass')?.value || '',
          schedule: document.getElementById('detail-backup-cron')?.value || '0 2 * * *',
          retention: parseInt(document.getElementById('detail-backup-retention')?.value || '30')
        });
        toast(`Backup routine "${routineName}" created`, 'success');
      } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });

    // Start log polling for running containers
    if (s === 'running') {
      detailLogTimer = setInterval(async () => {
        try {
          if (!currentContainer || currentContainer.name !== name) { clearInterval(detailLogTimer); detailLogTimer = null; return; }
          let logs;
          if (isRemote) {
            logs = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}/logs`);
          } else {
            logs = await api('GET', `/containers/${name}/logs`);
          }
          const logText = typeof logs.logs === 'string' ? logs.logs : (Array.isArray(logs.logs) ? logs.logs.join('\n') : '');
          const el = document.getElementById('detail-log-output');
          if (el) el.textContent = logText || 'No logs available';
        } catch (e) { clearInterval(detailLogTimer); detailLogTimer = null; }
      }, 3000);
    }

    // Build-in-polling: auto-refresh detail when container is building
    if (!isRemote && isBuilding) {
      let pollAttempt = 0;
      const pollBuilding = setInterval(async () => {
        pollAttempt++;
        if (pollAttempt > 60) { clearInterval(pollBuilding); return; }
        try {
          const updated = await api('GET', `/containers/${name}`);
          if (updated.status !== 'building' && updated.status !== 'starting') {
            clearInterval(pollBuilding);
            showContainerDetail(name, nodeId);
            loadContainers();
          } else {
            updateContainerBadge(name, updated.status);
          }
        } catch(e) {}
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
async function execInContainer(name) {
  const cmd = prompt(`Run command in "${name}":`);
  if (!cmd || !cmd.trim()) return;
  try {
    const data = await api('POST', `/containers/${encodeURIComponent(name)}/exec`, { command: cmd });
    openModal(`Exec — ${name}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc((data.stdout||'') + (data.stderr||'') || '(no output)')}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}
async function deleteContainer(name) { const ok = await confirmAction('Delete Container',`Delete "${name}"? This cannot be undone.`); if (!ok) return; try { await api('DELETE',`/containers/${name}`); if(detailLogTimer){clearInterval(detailLogTimer);detailLogTimer=null;} closeContainerTerminal(); currentContainer=null; toast(`Deleted "${name}"`,'success'); loadContainers(); document.getElementById('container-detail').innerHTML='<div class="split-right-empty"><div><i class="bi bi-box-seam"></i><p>Select a container to manage</p></div></div>'; } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

let containerBusy = {};

function setContainerLoading(name, action) {
  containerBusy[name] = action;
  const label = { start: 'Starting...', stop: 'Stopping...', restart: 'Restarting...', delete: 'Deleting...' }[action] || 'Loading...';
  document.querySelectorAll(`#containers-list .split-list-card[data-name="${CSS.escape(name)}"] button`).forEach(b => b.disabled = true);
  document.querySelectorAll(`#containers-list .split-list-card[data-name="${CSS.escape(name)}"] .badge`).forEach(b => { b.className = 'badge badge-warning'; b.textContent = label; });
  if (currentContainer && currentContainer.name === name) {
    ['detail-start','detail-stop','detail-restart','detail-delete'].forEach(id => { const b = document.getElementById(id); if (b) b.disabled = true; });
    const detailBadge = document.querySelector('#container-detail .sr-header .badge');
    if (detailBadge) { detailBadge.className = 'badge badge-warning'; detailBadge.textContent = label; }
  }
}

function clearContainerLoading(name) {
  delete containerBusy[name];
  pollContainerStatus(name, 0);
}

function getStatusBadgeClass(status) {
  const map = {
    running: 'badge-success',
    running_degraded_ssh: 'badge-warning',
    running_degraded_ankd: 'badge-warning',
    starting: 'badge-info',
    building: 'badge-warning',
    stopping: 'badge-info',
    stopped: 'badge-neutral',
    failed: 'badge-danger',
    deleting: 'badge-danger'
  };
  return map[status] || 'badge-neutral';
}

function getStatusLabel(status) {
  const map = {
    running: 'running',
    running_degraded_ssh: 'degraded',
    running_degraded_ankd: 'degraded',
    building: 'building',
    starting: 'starting',
    stopping: 'stopping',
    stopped: 'stopped',
    failed: 'failed',
    deleting: 'deleting'
  };
  return map[status] || status;
}

function updateContainerBadge(name, status) {
  document.querySelectorAll(`#containers-list .split-list-card[data-name="${CSS.escape(name)}"] .badge`).forEach(b => {
    b.className = `badge ${getStatusBadgeClass(status)}`;
    b.textContent = getStatusLabel(status);
  });
  document.querySelectorAll(`#dashboard-containers .cbox`).forEach(box => {
    if (box.querySelector('.nm')?.textContent === name) {
      const dot = box.querySelector('.dot');
      const st = box.querySelector('.st');
      box.className = `cbox ${status === 'running' ? 'running' : status === 'building' ? 'building' : status === 'failed' ? 'failed' : 'stopped'}`;
      if (st) st.textContent = status;
    }
  });
  if (currentContainer && currentContainer.name === name) {
    const detailBadge = document.querySelector('#container-detail .sr-header .badge');
    if (detailBadge) { detailBadge.className = `badge ${getStatusBadgeClass(status)}`; detailBadge.textContent = getStatusLabel(status); }
    updateDetailButtons(name, status);
  }
}

function updateDetailButtons(name, status) {
  const dis = containerActionDisabled(status);
  const startBtn = document.getElementById('detail-start');
  const stopBtn = document.getElementById('detail-stop');
  const restartBtn = document.getElementById('detail-restart');
  const deleteBtn = document.getElementById('detail-delete');
  if (startBtn) startBtn.disabled = dis.start;
  if (stopBtn) stopBtn.disabled = dis.stop;
  if (restartBtn) restartBtn.disabled = dis.restart;
  if (deleteBtn) deleteBtn.disabled = dis.delete;
}

async function pollContainerStatus(name, attempt) {
  if (attempt > 30) { loadContainers(); return; }
  try {
    const c = await api('GET', `/containers/${name}`);
    updateContainerBadge(name, c.status);
    if (c.status === 'building' || c.status === 'starting' || c.status === 'stopping') {
      setTimeout(() => pollContainerStatus(name, attempt + 1), 2000);
    } else {
      clearContainerLoading(name);
      loadContainers();
      if (currentContainer && currentContainer.name === name) {
        currentContainer = c;
        updateDetailButtons(name, c.status);
      }
    }
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

/* ═══════ APK FAILURE MODAL ═══════ */
function showApkFailureModal(name, failedPackages, log) {
  const host = location.hostname || 'localhost';
  const sshCmd = currentContainer?.ssh_port ? `ssh root@${host} -p ${currentContainer.ssh_port}` : '';
  openModal('Package Installation Failed', `
    <div style="text-align:center;margin-bottom:16px">
      <i class="bi bi-exclamation-triangle" style="font-size:48px;color:var(--warning)"></i>
      <h3 style="margin:12px 0 4px">Build Partially Failed</h3>
      <p style="color:var(--text-secondary);font-size:13px">Container <strong>${esc(name)}</strong> was created but packages failed to install.</p>
    </div>
    <div class="settings-section">
      <div class="settings-section-title"><i class="bi bi-list-check"></i> Failed Packages</div>
      <pre style="font-size:12px;background:rgba(10,15,30,0.4);padding:10px;border-radius:6px;max-height:120px;overflow:auto;margin:0">${esc(failedPackages)}</pre>
    </div>
    ${sshCmd ? `<div class="settings-section">
      <div class="settings-section-title"><i class="bi bi-terminal"></i> Manual Install</div>
      <div class="ssh-hint"><code class="ssh-hint-cmd">${esc(sshCmd)}</code><button class="btn btn-sm btn-ghost" onclick="copyText('${esc(sshCmd)}');toast('Copied!','success')"><i class="bi bi-clipboard"></i></button></div>
      <p style="font-size:12px;color:var(--text-muted);margin-top:8px">Run inside container: <code>apk add --allow-untrusted ${esc(failedPackages)}</code></p>
    </div>` : ''}
    <div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
      <button class="btn btn-danger" onclick="closeModal();deleteContainer('${esc(name)}')"><i class="bi bi-trash3"></i> Cancel & Remove</button>
      <button class="btn btn-primary" onclick="closeModal()"><i class="bi bi-play-fill"></i> Continue Build</button>
    </div>
  `);
}

/* ═══════ CONTAINER TERMINAL CLEANUP ═══════ */
function closeContainerTerminal() {
  if (xtermWs) { try { xtermWs.close(); } catch(e){} xtermWs = null; }
  if (xtermTerminal) { try { xtermTerminal.dispose(); } catch(e){} xtermTerminal = null; }
  if (detailLogTimer) { clearInterval(detailLogTimer); detailLogTimer = null; }
  const ctEl = document.getElementById('container-terminal');
  if (ctEl) { ctEl.innerHTML = ''; ctEl.style.display = 'none'; }
}

/* ═══════ IMAGE TRANSFER ═══════ */
async function transferImage(imageName) {
  let nodes = [];
  try { const d = await api('GET', '/system/dashboard'); nodes = (d.nodes || []).filter(n => n.status === 'online'); } catch(e) {}
  if (!nodes.length) { toast('No online nodes available', 'warning'); return; }
  const result = await customModal('Transfer Image', [
    { id: 'target', label: 'Target Node', type: 'select', options: nodes.map(n => `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`).join('') }
  ]);
  if (!result) return;
  try {
    toast(`Transferring "${imageName}" to node...`, 'info');
    await api('POST', `/nodes/${encodeURIComponent(result.target)}/images/transfer`, { image: imageName });
    toast('Image transferred successfully', 'success');
  } catch (e) { toast(`Transfer failed: ${e.message}`, 'error'); }
}

/* ═══════ IMAGES ═══════ */
let cachedTemplates = [];
let cachedImages = [];

async function loadImages() {
  try {
    const [images, templates] = await Promise.all([
      api('GET', '/images/all').catch(() => []),
      api('GET', '/images/templates').catch(() => [])
    ]);
    cachedImages = Array.isArray(images) ? images : [];
    cachedTemplates = Array.isArray(templates) ? templates : [];
    document.getElementById('images-count-label').textContent = cachedImages.length + ' images';
  } catch (e) { console.error('Images load failed:', e); }
}

function handleAnkFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    const content = e.target.result;
    const ta = document.getElementById('ankfile-content');
    if (ta) {
      ta.value = content;
      toast(`Loaded ${file.name} (${content.length} bytes)`, 'success');
      const nameInput = document.getElementById('ankfile-name');
      if (nameInput && !nameInput.value) {
        nameInput.value = file.name.replace(/\.ank$/i, '').replace(/[^a-zA-Z0-9_-]/g, '-');
      }
    }
  };
  reader.readAsText(file);
}

async function showImageSection(section) {
  document.querySelectorAll('#images-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.section === section));
  const el = document.getElementById('image-detail');
  if (!el) return;

  if (section === 'quick-deploy') {
    if (cachedTemplates.length) {
      el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-lightning-charge" style="color:var(--accent)"></i> Quick Deploy</h2></div><p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">One-click containers — pick a template, name it, deploy.</p><div class="templates-grid">${cachedTemplates.map(t => `<div class="template-card" style="border-left:3px solid ${t.color||'var(--primary)'}" onclick="deployTemplate('${esc(t.id)}','${esc(t.name)}',${t.base_ready})"><div class="template-icon" style="color:${t.color||'var(--primary)'}"><i class="bi ${t.icon||'bi-box-seam'}"></i></div><div class="template-name">${esc(t.name)}</div><div class="template-desc">${esc(t.description||'')}</div><span class="template-badge ${t.base_ready?'ready':'pending'}">${t.base_ready?'Ready':'Pull base first'}</span></div>`).join('')}</div>`;
    } else if (cachedImages.length === 0 && !cachedTemplates.length && document.querySelector('#page-images.active')) {
      el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-lightning-charge" style="color:var(--accent)"></i> Quick Deploy</h2></div><div class="empty-state" style="padding:40px"><div class="spinner" style="width:24px;height:24px;margin:0 auto 8px"></div><p style="color:var(--text-muted)">Loading templates...</p></div>`;
    } else {
      el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-lightning-charge" style="color:var(--accent)"></i> Quick Deploy</h2></div><div class="empty-state" style="padding:40px"><i class="bi bi-cloud-download" style="font-size:32px;color:var(--text-muted)"></i><p style="margin-top:8px;color:var(--text-muted)">No templates available.<br>Pull an Alpine image first.</p></div>`;
    }
  } else if (section === 'ankfile') {
    el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-file-earmark-code" style="color:var(--accent)"></i> Ankfile Build</h2></div><p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Build custom images from an Ankfile (like Dockerfile).</p><div class="card" style="border:1px solid var(--accent)"><div class="card-body"><div class="form-group"><label class="form-label">Container Name</label><input type="text" class="form-input" id="ankfile-name" placeholder="my-app" value="ank-build"></div><div class="form-group"><label class="form-label">Ankfile</label><textarea class="ankfile-editor" id="ankfile-content" rows="10" placeholder="# FROM alpine-3.20&#10;PASSWD ank123&#10;RUN apk add nginx">FROM alpine-3.20\nPASSWD ank123\nRUN apk add --allow-untrusted nginx\nRUN mkdir -p /var/www/html\nRUN echo "&lt;h1&gt;Custom ANK Image&lt;/h1&gt;" > /var/www/html/index.html\nEXPOSE 8080</textarea></div><div class="form-group" style="display:flex;align-items:center;gap:8px"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="ankfile-save-image" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-bookmark" style="color:var(--accent)"></i> Save as Image</label></div><div class="form-group" id="ankfile-image-name-group" style="display:none"><label class="form-label">Image Name</label><input type="text" class="form-input" id="ankfile-image-name" placeholder="my-custom-image" pattern="[a-zA-Z0-9._-]+" maxlength="40"><small class="form-hint">Letters, numbers, dots, dashes only</small></div><div id="ankfile-node-select-container"></div><div style="display:flex;gap:8px"><button type="button" class="btn btn-primary" id="ankfile-build-btn"><i class="bi bi-hammer"></i> Build</button><button type="button" class="btn btn-ghost" id="ankfile-example-btn"><i class="bi bi-filetype-json"></i> Load Example</button></div></div></div><div class="card" style="border:1px dashed var(--border);margin-top:12px"><div class="card-body" id="ank-drop-zone" style="text-align:center;padding:24px;cursor:pointer;transition:background 0.2s"><i class="bi bi-cloud-arrow-up" style="font-size:28px;color:var(--accent);display:block;margin-bottom:8px"></i><p style="font-size:13px;color:var(--text-muted);margin:0">Drag & drop a <code>.ank</code> file here</p><p style="font-size:11px;color:var(--text-muted);margin:4px 0 0">or click to browse</p><input type="file" id="ank-file-input" accept=".ank,.txt" style="display:none"></div></div>`;
    document.getElementById('ank-drop-zone')?.addEventListener('click', () => document.getElementById('ank-file-input')?.click());
    const dz = document.getElementById('ank-drop-zone');
    const fi = document.getElementById('ank-file-input');
    if (dz && fi) {
      dz.addEventListener('dragover', e => { e.preventDefault(); dz.style.background = 'var(--bg-hover)'; });
      dz.addEventListener('dragleave', () => { dz.style.background = ''; });
      dz.addEventListener('drop', e => { e.preventDefault(); dz.style.background = ''; if (e.dataTransfer.files.length) handleAnkFile(e.dataTransfer.files[0]); });
      fi.addEventListener('change', () => { if (fi.files.length) handleAnkFile(fi.files[0]); fi.value = ''; });
    }
    document.getElementById('ankfile-build-btn')?.addEventListener('click', async () => {
      const content = document.getElementById('ankfile-content')?.value?.trim();
      const name = document.getElementById('ankfile-name')?.value?.trim() || 'ank-build';
      const saveAsImage = document.getElementById('ankfile-save-image')?.checked || false;
      const imageName = document.getElementById('ankfile-image-name')?.value?.trim() || '';
      const targetNode = document.getElementById('ankfile-target-node')?.value || 'local';
      if (!content) { toast('Ankfile is empty', 'error'); return; }
      if (!content.includes('FROM')) { toast('Ankfile must have a FROM instruction', 'error'); return; }
      if (saveAsImage && !imageName) { toast('Image name is required', 'error'); return; }
      if (saveAsImage && !/^[a-zA-Z0-9._-]+$/.test(imageName)) { toast('Image name: only letters, numbers, dots, dashes', 'error'); return; }
      try {
        toast(`Building from Ankfile as "${name}"...`, 'info');
        await api('POST', '/images/ankfile', { content, name, save_as_image: saveAsImage, image_name: imageName, target_node: targetNode });
        loadContainers();
        if (saveAsImage) loadImages();
        pollContainerStatus(name, 0);
      } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });
    document.getElementById('ankfile-save-image')?.addEventListener('change', (e) => {
      document.getElementById('ankfile-image-name-group').style.display = e.target.checked ? 'block' : 'none';
    });
    try {
      const d = await api('GET', '/system/dashboard');
      const onlineNodes = (d.nodes || []).filter(n => n.status === 'online');
      if (onlineNodes.length > 0) {
        let opts = '<option value="local">Local</option>';
        onlineNodes.forEach(n => { opts += `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`; });
        const nodeSelectContainer = document.getElementById('ankfile-node-select-container');
        if (nodeSelectContainer) nodeSelectContainer.innerHTML = `<div class="form-group"><label class="form-label">Target Node</label><select class="form-input" id="ankfile-target-node">${opts}</select></div>`;
      }
    } catch(e) {}
    document.getElementById('ankfile-example-btn')?.addEventListener('click', () => {
      document.getElementById('ankfile-content').value = 'FROM alpine-3.20\nPASSWD ank123\nRUN apk add --allow-untrusted curl tar sqlite\nRUN mkdir -p /opt/cloudreve\nRUN curl -L https://github.com/cloudreve/cloudreve/releases/download/4.18.0/cloudreve_4.18.0_linux_armv7.tar.gz | tar xz -C /opt/cloudreve\nEXPOSE 5212\nWORKDIR /opt/cloudreve\nCMD /opt/cloudreve/cloudreve';
      document.getElementById('ankfile-name').value = 'cloudreve';
      toast('Example Ankfile loaded', 'info');
    });
  } else if (section === 'images') {
    if (cachedImages.length) {
      el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-hdd-stack" style="color:var(--accent)"></i> Ank Images (${cachedImages.length})</h2></div>${cachedImages.map(img => `<div class="split-list-card" data-id="${esc(img.name)}" onclick="showImageDetail('${esc(img.name)}','${esc(img.node||'local')}')"><div class="slc-top"><span class="slc-name"><i class="bi bi-hdd-stack" style="color:var(--accent)"></i>${esc(img.name)}</span><span class="template-badge ready" style="font-size:10px;padding:2px 6px;border-radius:8px;background:${img.node==='local'?'var(--primary)':'var(--accent)'};color:#fff">${esc(img.node_alias||'local')}</span><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteImage('${esc(img.name)}')" title="Delete"><i class="bi bi-trash3"></i></button></div><div class="slc-meta"><span>${img.size_human || fmtBytes(img.size||0)}</span><span>${esc(img.version||'')}</span></div></div>`).join('')}`;
    } else {
      el.innerHTML = `<div class="sr-header"><h2><i class="bi bi-hdd-stack" style="color:var(--accent)"></i> Ank Images</h2></div><div class="empty-state" style="padding:40px"><i class="bi bi-hdd-stack" style="font-size:32px;color:var(--text-muted)"></i><p style="margin-top:8px;color:var(--text-muted)">No images downloaded yet</p></div>`;
    }
  }
}

function showImageDetail(name, node) {
  const el = document.getElementById('image-detail');
  if (!el) return;
  const containersUsing = (cachedContainers || []).filter(c => c.image === name || c.template === name);
  el.innerHTML = `
    <div class="sr-header">
      <h2><i class="bi bi-hdd-stack" style="color:var(--accent)"></i>${esc(name)}</h2>
      <div class="sr-actions">
        <button class="btn btn-ghost btn-sm" onclick="showImageSection('images')"><i class="bi bi-arrow-left"></i> Back</button>
        <button class="btn btn-sm" onclick="transferImage('${esc(name)}')" title="Transfer to node"><i class="bi bi-send"></i> Transfer</button>
        <button class="btn btn-danger btn-sm" onclick="deleteImage('${esc(name)}')"><i class="bi bi-trash3"></i></button>
      </div>
    </div>
    <div class="sr-info-grid">
      <div class="sr-info-item"><div class="sr-label">Name</div><div class="sr-value">${esc(name)}</div></div>
      ${node ? `<div class="sr-info-item"><div class="sr-label">Node</div><div class="sr-value">${esc(node)}</div></div>` : ''}
    </div>
    ${containersUsing.length ? `<div style="margin-top:16px"><h3 style="font-size:14px;margin-bottom:8px">Containers using this image</h3>${containersUsing.map(c => `<div class="split-list-card" onclick="navigateTo('containers');setTimeout(()=>showContainerDetail('${esc(c.name)}','${esc(c.node||'local')}'),200)" style="cursor:pointer"><div class="slc-top"><span class="slc-name"><i class="bi bi-box" style="color:var(--accent)"></i>${esc(c.name)}</span><span class="template-badge ${c.status==='running'?'ready':'pending'}">${esc(c.status)}</span></div></div>`).join('')}</div>` : ''}`;
}

async function pullImage() {
  let versionOpts = ['3.22','3.21','3.20','3.19','3.18'];
  try { const v = await api('GET', '/images/alpine-versions'); if (Array.isArray(v) && v.length) versionOpts = v; } catch(e) {}
  const result = await customModal('Pull Image', [
    { id: 'version', label: 'Alpine Version', type: 'select', options: versionOpts.map(v => `<option value="${esc(v)}"${v==='3.20'?' selected':''}>${esc(v)}</option>`).join(''), hint: 'Fetch available versions from Alpine CDN' }
  ]);
  if (!result) return;
  const version = result.version.trim();
  if (!/^\d+\.\d+$/.test(version)) { toast('Invalid version format (e.g. 3.20)', 'error'); return; }
  const pullId = `pull-${Date.now()}`;
  document.body.insertAdjacentHTML('beforeend', `<div class="modal-overlay active" id="${pullId}"><div class="modal-card" style="max-width:560px"><div class="modal-header"><h3>Pulling Alpine ${esc(version)}</h3><button class="modal-close" onclick="document.getElementById('${pullId}').remove()">&times;</button></div><div class="modal-body"><pre class="log-output" id="${pullId}-log" style="min-height:180px;max-height:400px;overflow:auto"></pre></div><div class="modal-footer"><button class="btn btn-ghost" onclick="document.getElementById('${pullId}').remove()">Close</button></div></div></div>`);
  const logEl = document.getElementById(`${pullId}-log`);
  try {
    await api('POST', '/images/pull', { version });
    let lastLen = 0;
    const poll = setInterval(async () => {
      try {
        const st = await api('GET', `/images/pull/status?version=${version}`);
        const lines = st.output || [];
        if (lines.length !== lastLen) {
          logEl.textContent = lines.join('\n');
          logEl.scrollTop = logEl.scrollHeight;
          lastLen = lines.length;
        }
        if (st.state === 'done') {
          clearInterval(poll);
          logEl.textContent += '\nDone!';
          toast('Image pulled successfully', 'success');
          loadImages().then(() => { const sel = document.querySelector('#images-list .split-list-card.selected'); showImageSection(sel ? sel.dataset.section : 'images'); });
        } else if (st.state === 'error') {
          clearInterval(poll);
          logEl.textContent += `\nError: ${st.error || 'Unknown error'}`;
          toast('Pull failed', 'error');
        }
      } catch(e) {}
    }, 1500);
  } catch (e) {
    logEl.textContent = `Error: ${e.message}`;
    toast(`Failed: ${e.message}`, 'error');
  }
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
  const tpl = cachedTemplates.find(t => t.id === id);
  const imageField = tpl ? tpl.image : id;
  try {
    if (nodeId !== 'local') {
      toast(`Deploying on remote...`, 'info');
      await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name: containerName, image: imageField, root_password: rootPass });
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
  try { await api('DELETE', `/images/${encodeURIComponent(id)}`); toast('Image deleted', 'success'); loadImages().then(() => { const sel = document.querySelector('#images-list .split-list-card.selected'); showImageSection(sel ? sel.dataset.section : 'images'); }); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
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
      const diskInfo = isOnline && n.disk_total ? `<span>Disk ${n.disk_used||0}/${n.disk_total}GB</span>` : '';
      const uptimeInfo = isOnline && n.uptime_seconds ? `<span>Up ${fmtUptime(n.uptime_seconds)}</span>` : '';
      const managedBy = n.managed_by ? `<span style="color:var(--text-muted)">by ${esc(n.managed_by)}</span>` : '';
      return `<div class="split-list-card" data-id="${esc(n.id)}" onclick="showNodeDetail('${esc(n.id)}','${esc(n.alias||n.ip)}','${esc(n.status)}')">
        <div class="slc-top"><span class="slc-name"><i class="bi bi-hdd-network" style="color:var(--primary)"></i>${esc(n.alias||n.ip)}${roleTag}</span><div style="display:flex;align-items:center;gap:6px"><span class="badge ${n.status==='online'?'badge-success':n.status==='pending'?'badge-warning':'badge-danger'}" style="font-size:10px">${label}</span>${isOnline?`<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();refreshNode('${esc(n.id)}')" title="Refresh"><i class="bi bi-arrow-clockwise"></i></button>`:''}</div></div>
        <div class="slc-meta"><span>CPU ${isOnline?Math.round(n.cpu_percent||0)+'%':'-'}</span><span>RAM ${isOnline?(n.mem_used_gb||0).toFixed(1)+'GB':'-'}</span>${diskInfo}${uptimeInfo}<span>${isOnline?(n.containers_total||0):'-'} containers</span>${managedBy}</div>
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
        const sc = getStatusBadgeClass(c.status);
        const dis = containerActionDisabled(c.status);
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
          <span style="font-size:13px">${esc(c.name)} <span class="badge ${sc}" style="font-size:9px">${getStatusLabel(c.status)}</span></span>
          <div style="display:flex;gap:4px">
            ${c.status==='running'||c.status==='starting'?`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','stop')" ${dis.stop?'disabled':''}><i class="bi bi-stop-fill"></i></button>`:`<button class="btn btn-icon btn-ghost sm" onclick="remoteContainerAction('${nodeId}','${esc(c.name)}','start')" ${dis.start?'disabled':''}><i class="bi bi-play-fill"></i></button>`}
            <button class="btn btn-icon btn-ghost sm" onclick="remoteDeleteContainer('${nodeId}','${esc(c.name)}')" ${dis.delete?'disabled':''}><i class="bi bi-trash3"></i></button>
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

async function refreshNode(id) {
  try { toast('Refreshing node...', 'info'); await api('POST', `/nodes/${encodeURIComponent(id)}/refresh`); loadNodes(); toast('Node refreshed', 'success'); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-add-node')?.addEventListener('click', sendPairingRequest);

async function sendPairingRequest() {
  const result = await customModal('Add Node', [
    { id: 'ip', label: 'Panel IP', type: 'text' },
    { id: 'port', label: 'Port', type: 'text', value: '8001' },
    { id: 'user', label: 'Username', type: 'text', value: 'admin' },
    { id: 'password', label: 'Password', type: 'text' },
    { id: 'alias', label: 'Alias (optional)', type: 'text', placeholder: 'Auto-fills from node name', optional: true }
  ]);
  if (!result) return;
  try { await api('POST', '/nodes/pairing/send', { ip: result.ip, port: parseInt(result.port), user: result.user || 'admin', password: result.password, alias: result.alias }); toast('Pairing request sent', 'success'); loadNodes(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function remoteContainerAction(nodeId, name, action) {
  try { await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}/${action}`); toast(`${action} sent`, 'success'); loadContainers(); pollRemoteContainerStatus(nodeId, name, 0); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function remoteDeleteContainer(nodeId, name) {
  const ok = await confirmAction('Delete Container', `Delete "${name}" on remote node?`);
  if (!ok) return;
  try { await api('DELETE', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`); toast('Deleted', 'success'); loadContainers(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function loadNodesForShellSelector() {
  try {
    const data = await api('GET', '/nodes');
    const nodes = data.nodes || [];
    updateNodeSelectors(nodes);
  } catch(e) {}
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
      const bc = running===total&&total>0 ? 'badge-success' : running>0 ? 'badge-warning' : total>0 ? 'badge-danger' : 'badge-neutral';
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
          <button class="btn btn-secondary btn-sm" onclick="rollingUpdateStack('${esc(s.name)}')" title="Rolling Update"><i class="bi bi-arrow-clockwise"></i></button>
          <button class="btn btn-secondary btn-sm" onclick="healStack('${esc(s.name)}')" title="Start Healing"><i class="bi bi-heart-pulse"></i></button>
          <button class="btn btn-secondary btn-sm" onclick="viewStackLogs('${esc(s.name)}')" title="Logs"><i class="bi bi-journal-text"></i></button>
          <button class="btn btn-secondary btn-sm" onclick="viewStackMetrics('${esc(s.name)}')" title="Metrics"><i class="bi bi-graph-up"></i></button>
          <button class="btn btn-secondary btn-sm" onclick="inspectStack('${esc(s.name)}')" title="Inspect"><i class="bi bi-info-circle"></i></button>
          <button class="btn btn-danger btn-sm" onclick="deleteStack('${esc(s.name)}')"><i class="bi bi-trash3"></i></button>
        </div>
      </div>
      <div class="sr-info-grid">
        <div class="sr-info-item"><div class="sr-label">Template</div><div class="sr-value">${esc(s.template||s.image||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Status</div><div class="sr-value">${running}/${total} running</div></div>
        <div class="sr-info-item"><div class="sr-label">LB Port</div><div class="sr-value">${s.port||s.lb_port||'-'}</div></div>
        <div class="sr-info-item"><div class="sr-label">LB Algorithm</div><div class="sr-value">${esc(s.load_balance||'least_conn')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Scale Range</div><div class="sr-value">${s.min||1} — ${s.max||10}</div></div>
        <div class="sr-info-item"><div class="sr-label">Trigger</div><div class="sr-value">${esc(s.trigger||'none')}</div></div>
      </div>
      <div style="font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:10px">Containers</div>
      ${(s.containers||[]).map(c => {
        const sc = getStatusBadgeClass(c.status);
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
          <span style="font-size:13px">${esc(c.name)} <span class="badge ${sc}" style="font-size:9px">${getStatusLabel(c.status)}</span></span>
          <span style="font-size:11px;color:var(--text-muted)">${esc(c.ip||'-')}</span>
        </div>`;
      }).join('') || '<div style="text-align:center;padding:16px;color:var(--text-muted);font-size:12px">No containers</div>'}`;
  }).catch(e => { el.innerHTML = `<div style="color:var(--danger);padding:20px">${esc(e.message)}</div>`; });
}

async function rollingUpdateStack(name) {
  const ok = await confirmAction('Rolling Update', `Perform rolling update on stack "${name}"? This will replace containers one by one.`);
  if (!ok) return;
  try { await api('POST', `/stacks/${encodeURIComponent(name)}/rolling-update`, {}); toast('Rolling update started', 'info'); loadStacks(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function healStack(name) {
  try { await api('POST', `/stacks/${encodeURIComponent(name)}/healing`, {}); toast(`Healing started for "${name}"`, 'success'); loadStacks(); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function viewStackLogs(name) {
  try {
    const data = await api('GET', `/stacks/${encodeURIComponent(name)}/logs`);
    const lines = data.lines || data.logs || [];
    openModal(`Stack Logs — ${name}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(lines.join('\n') || 'No logs')}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function viewStackMetrics(name) {
  try {
    const data = await api('GET', `/stacks/${encodeURIComponent(name)}/metrics`);
    openModal(`Stack Metrics — ${name}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(JSON.stringify(data, null, 2))}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function inspectStack(name) {
  try {
    const data = await api('GET', `/stacks/${encodeURIComponent(name)}`);
    openModal(`Inspect — ${name}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(JSON.stringify(data, null, 2))}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-create-stack')?.addEventListener('click', () => {
  document.getElementById('stack-modal-overlay').classList.add('active');
});
function toggleStackAnkfile() { const sel = document.getElementById('stack-image')?.value; const sec = document.getElementById('stack-ankfile-section'); if (sec) sec.style.display = sel === 'ankfile' ? 'block' : 'none'; }

async function createStack() {
  const name = document.getElementById('stack-name')?.value?.trim();
  const image = document.getElementById('stack-image')?.value;
  const min = parseInt(document.getElementById('stack-min')?.value || '1');
  const max = parseInt(document.getElementById('stack-max')?.value || '5');
  const lbPort = parseInt(document.getElementById('stack-lb-port')?.value || '30000');
  const lbAlgo = document.getElementById('stack-lb-algo')?.value || 'least_conn';
  const rootPass = document.getElementById('stack-root-pass')?.value || 'ankstack';
  const volume = document.getElementById('stack-volume')?.checked;
  const trigger = document.getElementById('stack-trigger')?.value;
  const ankfile = image === 'ankfile' ? (document.getElementById('stack-ankfile')?.value?.trim() || '') : '';
  if (!name) { toast('Stack name required', 'error'); return; }
  if (image === 'ankfile' && !ankfile) { toast('Ankfile content required', 'error'); return; }
  try {
    toast(`Creating stack "${name}"...`, 'info');
    await api('POST', '/stacks', { name, template: image, min, max, lb_port: lbPort, load_balance: lbAlgo, root_password: rootPass, shared_volume: volume, trigger: trigger === 'none' ? null : trigger, ankfile });
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
    if (!routines.length) { el.innerHTML = '<div class="empty-state"><i class="bi bi-cloud-arrow-up"></i><h3>No backup routines</h3><p>Create a backup routine to protect your containers</p><button class="btn btn-primary" onclick="document.getElementById(\'backup-modal-overlay\').classList.add(\'active\')"><i class="bi bi-plus-lg"></i> Create Routine</button></div>'; const btn = document.getElementById('btn-create-backup'); if (btn) btn.style.display = ''; return; }
    const btn = document.getElementById('btn-create-backup'); if (btn) btn.style.display = '';
    el.innerHTML = routines.map(r => {
      const lastRun = r.last_run ? new Date(r.last_run).toLocaleString() : 'Never';
      const statusColor = r.last_status === 'success' ? 'var(--success)' : r.last_status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
      const srcLabel = r._source_type_label || r.source_type || '-';
      return `<div class="split-list-card" data-id="${esc(r.id||r.name)}" onclick="showBackupDetail('${esc(r.id||r.name)}')">
        <div class="slc-top"><span class="slc-name"><i class="bi bi-cloud-arrow-up" style="color:var(--accent)"></i>${esc(r.name)}</span><span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span></div>
        <div class="slc-meta"><span>${esc(srcLabel)}</span><span>${esc(r.schedule||'Manual')}</span><span>Ret: ${r.retention_days||30}d</span></div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = '<div class="empty-state"><p>Failed to load</p></div>'; }
}

let currentBackupId = null;

async function showBackupDetail(id) {
  currentBackupId = id;
  document.querySelectorAll('#backups-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.id === id));
  const el = document.getElementById('backup-detail');
  if (!el) return;
  try {
    const r = await api('GET', `/backups/${encodeURIComponent(id)}`);
    const lastRun = r.last_run ? new Date(r.last_run).toLocaleString() : 'Never';
    const srcLabel = r._source_type_label || r.source_type || '-';
    const remote = r.remote || {};
    el.innerHTML = `
      <div class="sr-header">
        <h2><i class="bi bi-cloud-arrow-up" style="color:var(--accent)"></i>${esc(r.name||id)}</h2>
        <div class="sr-actions">
          <button class="btn btn-success btn-sm" onclick="executeBackup('${esc(id)}')"><i class="bi bi-play-fill"></i> Run</button>
          <button class="btn btn-secondary btn-sm" onclick="showBackupHistory('${esc(id)}')"><i class="bi bi-clock-history"></i> History</button>
          <button class="btn btn-secondary btn-sm" onclick="browseBackupFiles('${esc(id)}')"><i class="bi bi-folder2-open"></i> Browse</button>
          <button class="btn btn-secondary btn-sm" onclick="checkBackupBattery()" title="Battery guard status"><i class="bi bi-battery-half"></i> Battery</button>
          <button class="btn btn-danger btn-sm" onclick="deleteBackup('${esc(id)}')"><i class="bi bi-trash3"></i></button>
        </div>
      </div>
      <div class="sr-info-grid">
        <div class="sr-info-item"><div class="sr-label">Source Type</div><div class="sr-value">${esc(srcLabel)}</div></div>
        <div class="sr-info-item"><div class="sr-label">Remote Host</div><div class="sr-value">${esc(remote.host||'-')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Schedule</div><div class="sr-value">${esc(r.schedule||'Manual')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Retention</div><div class="sr-value">${r.retention_days||30} days</div></div>
        <div class="sr-info-item"><div class="sr-label">Mode</div><div class="sr-value">${esc(r.backup_mode||'full')}</div></div>
        <div class="sr-info-item"><div class="sr-label">Immutable</div><div class="sr-value">${r.immutable?'Yes':'No'}</div></div>
        <div class="sr-info-item" style="grid-column:span 2"><div class="sr-label">Last Run</div><div class="sr-value">${lastRun} ${r.last_status?`(${r.last_status})`:''}</div></div>
      </div>
      <div id="backup-sub-content"></div>`;
  } catch(e) { el.innerHTML = `<div style="color:var(--danger);padding:20px">${esc(e.message)}</div>`; }
}

async function showBackupHistory(id) {
  const sub = document.getElementById('backup-sub-content');
  if (!sub) return;
  sub.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Loading history...</div>';
  try {
    const data = await api('GET', `/backups/history?routine_id=${encodeURIComponent(id)}&limit=20`);
    const entries = data.history || [];
    if (!entries.length) { sub.innerHTML = '<div style="padding:12px;color:var(--text-muted)">No backup history</div>'; return; }
    sub.innerHTML = `<div style="padding:12px 0"><h4 style="margin-bottom:8px"><i class="bi bi-clock-history"></i> History</h4>${entries.map(e => {
      const ts = e.started_at ? new Date(e.started_at).toLocaleString() : '-';
      const statusColor = e.status==='success'?'var(--success)':e.status==='failed'?'var(--danger)':'var(--warning)';
      const size = e.size_bytes ? (e.size_bytes > 1048576 ? (e.size_bytes/1048576).toFixed(1)+'MB' : (e.size_bytes/1024).toFixed(1)+'KB') : '-';
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
        <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};flex-shrink:0"></span>
        <span style="flex:1;font-size:12px">${ts}</span>
        <span style="font-size:12px;color:var(--text-muted)">${size}</span>
        <span style="font-size:11px;color:${statusColor}">${e.status}</span>
        <button class="btn btn-ghost btn-sm" onclick="viewBackupLog('${esc(e.id)}')" title="View Log"><i class="bi bi-journal-text"></i></button>
      </div>`;
    }).join('')}</div>`;
  } catch(e) { sub.innerHTML = `<div style="color:var(--danger);padding:12px">${esc(e.message)}</div>`; }
}

async function viewBackupLog(historyId) {
  try {
    const data = await api('GET', `/backups/${encodeURIComponent(historyId)}/log`);
    openModal(`Backup Log — ${historyId}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(data.log||'No log')}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function browseBackupFiles(id) {
  const sub = document.getElementById('backup-sub-content');
  if (!sub) return;
  sub.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Loading files...</div>';
  try {
    const data = await api('GET', `/backups/${encodeURIComponent(id)}/browse?path=/`);
    const files = data.files || [];
    renderBackupFileBrowser(sub, id, files, '/');
  } catch(e) { sub.innerHTML = `<div style="color:var(--danger);padding:12px">${esc(e.message)}</div>`; }
}

function renderBackupFileBrowser(container, routineId, files, currentPath) {
  const html = `<div style="padding:12px 0">
    <h4 style="margin-bottom:8px"><i class="bi bi-folder2-open"></i> Remote Files</h4>
    <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">${esc(currentPath)}</div>
    ${files.length ? files.map(f => {
      const icon = f.type==='dir' ? 'bi-folder-fill' : 'bi-file-earmark';
      const color = f.type==='dir' ? 'var(--accent)' : 'var(--text-muted)';
      const size = f.type==='file' ? (f.size > 1048576 ? (f.size/1048576).toFixed(1)+'MB' : f.size > 1024 ? (f.size/1024).toFixed(1)+'KB' : f.size+'B') : '';
      const onclick = f.type==='dir' ? `browseBackupDir('${esc(routineId)}','${esc(currentPath+'/'+f.name).replace(/\/+/g,'/')}')` : '';
      return `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);cursor:${f.type==='dir'?'pointer':'default'}" ${onclick?`onclick="${onclick}"`:''}>
        <i class="bi ${icon}" style="color:${color}"></i>
        <span style="flex:1;font-size:12px">${esc(f.name)}</span>
        <span style="font-size:11px;color:var(--text-muted)">${size}</span>
        ${f.type==='file'?`<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();restoreBackupFile('${esc(routineId)}','${esc(f.name)}')" title="Restore"><i class="bi bi-arrow-counterclockwise"></i></button>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();previewBackupFile('${esc(routineId)}','${esc(f.name)}')" title="Preview"><i class="bi bi-eye"></i></button>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();renameBackupFile('${esc(routineId)}','${esc(f.name)}')" title="Rename"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();deleteBackupFile('${esc(routineId)}','${esc(f.name)}')" title="Delete" style="color:var(--danger)"><i class="bi bi-trash3"></i></button>`:''}
      </div>`;
    }).join('') : '<div style="padding:12px;color:var(--text-muted)">Empty</div>'}
  </div>`;
  container.innerHTML = html;
}

async function browseBackupDir(routineId, path) {
  const sub = document.getElementById('backup-sub-content');
  if (!sub) return;
  try {
    const data = await api('GET', `/backups/${encodeURIComponent(routineId)}/browse?path=${encodeURIComponent(path)}`);
    renderBackupFileBrowser(sub, routineId, data.files || [], path);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function restoreBackupFile(routineId, fileName) {
  const ok = await confirmAction('Restore', `Restore "${fileName}"?`);
  if (!ok) return;
  try {
    toast('Restoring...', 'info');
    const data = await api('POST', `/backups/${encodeURIComponent(routineId)}/restore`, { file: fileName });
    toast(`Restored to: ${data.restored_to}`, 'success');
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function previewBackupFile(routineId, fileName) {
  try {
    const data = await api('POST', `/backups/${encodeURIComponent(routineId)}/preview`, { file: fileName });
    openModal(`Preview — ${fileName}`, `<pre style="max-height:400px;overflow:auto;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(data.preview || data.content || JSON.stringify(data, null, 2))}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function renameBackupFile(routineId, fileName) {
  const result = await customModal('Rename Backup File', [
    { id: 'newname', label: 'New Name', type: 'text', value: fileName }
  ]);
  if (!result) return;
  const newname = result.newname.trim();
  if (!newname || newname === fileName) return;
  try {
    await api('POST', `/backups/${encodeURIComponent(routineId)}/rename`, { old_name: fileName, new_name: newname });
    toast('File renamed', 'success');
    browseBackupFiles(routineId);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function deleteBackupFile(routineId, fileName) {
  const ok = await confirmAction('Delete', `Delete "${fileName}"?`);
  if (!ok) return;
  try {
    await api('POST', `/backups/${encodeURIComponent(routineId)}/delete`, { file: fileName });
    toast('Deleted', 'success');
    browseBackupFiles(routineId);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}

document.getElementById('btn-create-backup')?.addEventListener('click', () => {
  backupWizardReset();
  document.getElementById('backup-modal-overlay').classList.add('active');
});

let backupWizardStep = 1;
let backupTestPassed = false;

function backupWizardReset() {
  backupWizardStep = 1;
  backupTestPassed = false;
  document.querySelectorAll('.backup-step-content').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.backup-step').forEach(s => { s.classList.remove('active','done'); });
  document.getElementById('backup-step-1').classList.add('active');
  document.querySelector('.backup-step[data-step="1"]').classList.add('active');
  document.getElementById('backup-prev-btn').style.display = 'none';
  document.getElementById('backup-next-btn').style.display = '';
  document.getElementById('backup-create-btn').style.display = 'none';
  document.getElementById('backup-test-result').textContent = '';
}

function backupWizardNav(dir) {
  const next = backupWizardStep + dir;
  if (next < 1 || next > 3) return;
  if (dir > 0 && backupWizardStep === 1 && !backupTestPassed) {
    toast('Test connection first', 'warning'); return;
  }
  if (dir > 0 && backupWizardStep === 2) {
    const name = document.getElementById('backup-name')?.value?.trim();
    if (!name) { toast('Routine name required', 'error'); return; }
    loadBackupSources();
  }
  document.querySelectorAll('.backup-step-content').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.backup-step').forEach(s => s.classList.remove('active'));
  document.getElementById(`backup-step-${next}`).classList.add('active');
  const prevStep = document.querySelector(`.backup-step[data-step="${backupWizardStep}"]`);
  prevStep.classList.remove('active');
  prevStep.classList.add('done');
  document.querySelector(`.backup-step[data-step="${next}"]`).classList.add('active');
  backupWizardStep = next;
  document.getElementById('backup-prev-btn').style.display = next > 1 ? '' : 'none';
  document.getElementById('backup-next-btn').style.display = next < 3 ? '' : 'none';
  document.getElementById('backup-create-btn').style.display = next === 3 ? '' : 'none';
}

async function testBackupConnection() {
  const btn = document.getElementById('backup-test-btn');
  const result = document.getElementById('backup-test-result');
  btn.disabled = true; result.textContent = 'Testing...'; result.style.color = 'var(--text-muted)';
  try {
    const body = {
      host: document.getElementById('backup-remote-host')?.value || '',
      port: document.getElementById('backup-remote-port')?.value || '22',
      user: document.getElementById('backup-ssh-user')?.value || '',
      pass: document.getElementById('backup-ssh-pass')?.value || '',
      path: document.getElementById('backup-remote-path')?.value || '/backups/ank'
    };
    const data = await api('POST', '/backups/test-connection', body);
    if (data.connected) { result.textContent = '✓ Connected'; result.style.color = 'var(--green)'; backupTestPassed = true; }
    else { result.textContent = '✗ Could not connect — check host, port and credentials'; result.style.color = 'var(--red)'; backupTestPassed = false; }
  } catch(e) {
    result.textContent = '✗ Could not connect — check host, port and credentials'; result.style.color = 'var(--red)'; backupTestPassed = false;
  }
  btn.disabled = false;
}

async function loadBackupSources() {
  const el = document.getElementById('backup-source-list');
  const srcType = document.getElementById('backup-source-type')?.value || 'container_full';
  try {
    if (srcType === 'container_full' || srcType === 'container_selective' || srcType === 'container_file') {
      const containers = await api('GET', '/containers/all');
      if (!containers.length) { el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">No containers found</div>'; return; }
      el.innerHTML = containers.map(c => `<label class="backup-source-item" data-name="${esc(c.name)}"><input type="checkbox" value="${esc(c.name)}" checked><span class="bi ${c.status==='running'?'bi-play-circle-fill':'bi-stop-circle'}" style="color:${c.status==='running'?'var(--green)':'var(--text-muted)'}"></span><span>${esc(c.name)}</span><span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${esc(c.image||'-')}</span></label>`).join('');
    } else {
      el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">Full system backup — no selection needed</div>';
    }
  } catch(e) { el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">Failed to load sources</div>'; }
  updateBackupSummary();
}

function updateBackupSummary() {
  const el = document.getElementById('backup-summary');
  const name = document.getElementById('backup-name')?.value || '-';
  const srcType = document.getElementById('backup-source-type')?.value || 'container_full';
  const mode = document.getElementById('backup-mode')?.value || 'full';
  const enc = document.getElementById('backup-encryption')?.value || 'none';
  const host = document.getElementById('backup-remote-host')?.value || '-';
  const selected = document.querySelectorAll('.backup-source-item input:checked');
  const srcText = srcType.includes('container') ? `${selected.length} container(s)` : 'Entire system';
  el.style.display = 'block';
  el.innerHTML = `<strong>Summary:</strong> "${esc(name)}" — ${srcType} (${srcText}) → ${esc(host)} | Mode: ${mode} | Encryption: ${enc}`;
}

async function createBackup() {
  const name = document.getElementById('backup-name')?.value?.trim();
  if (!name) { toast('Routine name required', 'error'); return; }
  const containers = Array.from(document.querySelectorAll('.backup-source-item input:checked')).map(cb => cb.value);
  try {
    toast(`Creating routine "${name}"...`, 'info');
    await api('POST', '/backups', {
      name,
      source_type: document.getElementById('backup-source-type')?.value || 'container_full',
      containers,
      remote_host: document.getElementById('backup-remote-host')?.value || '',
      remote_port: parseInt(document.getElementById('backup-remote-port')?.value || '22'),
      remote_path: document.getElementById('backup-remote-path')?.value || '/backups/ank',
      ssh_user: document.getElementById('backup-ssh-user')?.value || 'root',
      ssh_pass: document.getElementById('backup-ssh-pass')?.value || '',
      schedule: document.getElementById('backup-schedule')?.value || '',
      retention: parseInt(document.getElementById('backup-retention')?.value || '30'),
      backup_mode: document.getElementById('backup-mode')?.value || 'full',
      encryption: document.getElementById('backup-encryption')?.value || 'none',
      immutable: document.getElementById('backup-immutable')?.checked || false,
    });
    closeModalById('backup-modal-overlay');
    toast(`Routine "${name}" created`, 'success');
    loadBackups();
  } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
}

async function executeBackup(id) { try { toast('Running backup...','info'); await api('POST',`/backups/${encodeURIComponent(id)}/execute`); toast('Backup complete','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

async function checkBackupBattery() {
  try {
    const data = await api('GET', '/backups/battery');
    openModal('Battery Guard', `<pre style="font-size:12px;font-family:monospace;white-space:pre-wrap;margin:0">${esc(JSON.stringify(data, null, 2))}</pre>`);
  } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
}
async function deleteBackup(id) { const ok = await confirmAction('Delete Backup','Delete this routine and all its history?'); if(!ok) return; try { await api('DELETE',`/backups/${encodeURIComponent(id)}`); toast('Deleted','success'); loadBackups(); } catch(e) { toast(`Failed: ${e.message}`,'error'); } }

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
let settingsConfig = {};
let settingsInfo = {};

function showSettingsSection(section) {
  if (_ankMgrPoll) { clearInterval(_ankMgrPoll); _ankMgrPoll = null; }
  if (window._ankMgrLogPoll) { clearInterval(window._ankMgrLogPoll); window._ankMgrLogPoll = null; }
  document.querySelectorAll('#settings-sidebar .split-list-card').forEach(n => {
    n.classList.toggle('selected', n.dataset.section === section);
  });
  const el = document.getElementById('settings-content');
  if (!el) return;
  const cfg = settingsConfig;
  const info = settingsInfo;
  const sshPortDisplay = cfg.ssh_port || 2200;

  if (section === 'account') {
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-person-gear"></i> Account</h3></div><div class="card-body">
      <form id="password-form">
        <div class="form-group"><label class="form-label">Current Password</label><input type="password" class="form-input" id="current-password" required></div>
        <div class="form-group"><label class="form-label">New Password</label><input type="password" class="form-input" id="new-password" minlength="6"></div>
        <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Save</button>
      </form>
    </div></div>`;
    document.getElementById('password-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const newPass = document.getElementById('new-password').value;
        await api('POST', '/auth/password', {
          current_password: document.getElementById('current-password').value,
          new_password: newPass
        });
        toast('Password updated', 'success');
        if (newPass) {
          const loginRes = await fetch(`${API}/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' },
            body: JSON.stringify({ username: loginUsername.value, password: newPass })
          });
          const loginData = await loginRes.json();
          if (loginData.token) { ankToken = loginData.token; localStorage.setItem('ank_token', ankToken); }
        }
        document.getElementById('password-form').reset();
      } catch (e) { toast(`Failed: ${e.message}`, 'error'); }
    });
  } else if (section === 'server') {
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-server"></i> Server</h3></div><div class="card-body">
      <form id="panel-settings-form">
        <div class="form-group"><label class="form-label">Node Name</label><input type="text" class="form-input" id="setting-node-name" placeholder="e.g. ank-prod01" maxlength="30"><small class="form-hint">Identifies this server in the sidebar and on remote nodes</small></div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">Bind Address</label><select class="form-select" id="setting-bind"><option value="0.0.0.0">0.0.0.0 (all)</option><option value="127.0.0.1">127.0.0.1</option></select></div>
          <div class="form-group"><label class="form-label">Auto-Refresh</label><select class="form-select" id="setting-refresh"><option value="5">5s</option><option value="10" selected>10s</option><option value="30">30s</option><option value="60">60s</option><option value="0">Off</option></select></div>
        </div>
        <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="setting-autostart" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-power" style="color:var(--accent)"></i> Start server on device boot</label></div>
        <div class="form-group"><label class="form-label">Default Container Password</label><input type="password" class="form-input" id="setting-default-pass" placeholder="ank123" minlength="4"><small class="form-hint">Used when creating containers without specifying a password</small></div>
        <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg"></i> Save</button>
      </form>
      <hr style="border-color:var(--border);margin:16px 0">
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" id="restart-server-btn"><i class="bi bi-arrow-clockwise"></i> Restart Server</button>
        <button class="btn btn-ghost btn-sm" id="restart-device-btn"><i class="bi bi-phone"></i> Restart Device</button>
        <button class="btn btn-danger btn-sm" id="uninstall-btn"><i class="bi bi-trash3"></i> Uninstall ANK</button>
      </div>
    </div></div>`;
    document.getElementById('setting-bind').value = cfg.bind_address || '0.0.0.0';
    document.getElementById('setting-refresh').value = cfg.refresh_interval != null ? cfg.refresh_interval : 10;
    document.getElementById('setting-autostart').checked = cfg.autostart_on_boot !== false;
    document.getElementById('setting-node-name').value = cfg.node_name || '';
    document.getElementById('setting-default-pass').value = cfg.default_container_password || '';
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
    document.getElementById('restart-device-btn')?.addEventListener('click', async () => {
      const ok = await confirmAction('Restart Device', 'This will reboot the Android device. Continue?');
      if (!ok) return;
      showRestartModal('device');
    });
    document.getElementById('restart-server-btn')?.addEventListener('click', async () => {
      const ok = await confirmAction('Restart Server', 'Restart the ANK server?');
      if (!ok) return;
      showRestartModal('server');
    });
    document.getElementById('uninstall-btn')?.addEventListener('click', async () => {
      const ok = await confirmAction('Uninstall ANK', 'This will PERMANENTLY delete ALL containers, images, data, and ANK itself. This cannot be undone!');
      if (!ok) return;
      try { await api('POST', '/system/uninstall'); toast('Uninstalling...', 'info'); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
    });
  } else if (section === 'remote') {
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-diagram-3"></i> Remote Management & SSH</h3></div><div class="card-body">
      <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="setting-remote-mgmt" style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-diagram-3" style="color:var(--accent)"></i> Enable Remote Management</label><small class="form-hint">Allow other ANK instances to pair with this node</small></div>
      <div class="form-group" id="manager-ip-group" style="display:none"><label class="form-label">Manager IP / Range</label><input type="text" class="form-input" id="setting-manager-ip" placeholder="192.168.0.0/24 or 0.0.0.0" maxlength="30"><small class="form-hint">Single IP, CIDR range, or 0.0.0.0 (any)</small></div>
      <hr style="border-color:var(--border);margin:12px 0">
      <div class="form-group"><label class="checkbox-label" style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" id="setting-ssh-enabled" checked style="width:18px;height:18px;accent-color:var(--accent)"><i class="bi bi-terminal" style="color:var(--accent)"></i> Enable SSH (Android host)</label><small class="form-hint">SSH server on port <span id="setting-ssh-port-display">${sshPortDisplay}</span> — same password as this panel</small></div>
      <div class="form-group"><label class="form-label">SSH Port</label><input type="number" class="form-input" id="setting-ssh-port" value="${cfg.ssh_port || 2200}" min="1024" max="65535"></div>
      <button type="button" class="btn btn-primary" onclick="saveRemoteSSHSettings()"><i class="bi bi-check-lg"></i> Save</button>
    </div></div>`;
    const remoteMgmtEl = document.getElementById('setting-remote-mgmt');
    remoteMgmtEl.checked = cfg.enable_remote_management === true;
    document.getElementById('setting-manager-ip').value = cfg.manager_ip || '';
    document.getElementById('setting-ssh-enabled').checked = cfg.ssh_enabled !== false;
    document.getElementById('manager-ip-group').style.display = remoteMgmtEl.checked ? 'block' : 'none';
    remoteMgmtEl.addEventListener('change', () => { document.getElementById('manager-ip-group').style.display = remoteMgmtEl.checked ? 'block' : 'none'; });
  } else if (section === 'cache') {
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-database"></i> Cache</h3></div><div class="card-body">
      <div class="info-grid">
        <div class="info-item"><span class="info-label">Rootfs Size</span><span id="info-rootfs">...</span></div>
        <div class="info-item"><span class="info-label">Containers Data</span><span id="info-containers-size">...</span></div>
        <div class="info-item"><span class="info-label">Total Used</span><span id="info-total-size">...</span></div>
        <div class="info-item"><span class="info-label">Device Free</span><span id="info-device-free">${info.device_free||'-'}</span></div>
      </div>
      <button class="btn btn-ghost" style="margin-top:12px" onclick="refreshCacheInfo()"><i class="bi bi-arrow-clockwise"></i> Refresh</button>
    </div></div>`;
    refreshCacheInfo();
  } else if (section === 'about') {
    const sysInfo = settingsInfo || {};
    const diskFree = sysInfo.device_free || '-';
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-info-circle"></i> About</h3></div><div class="card-body">
      <div class="info-grid">
        <div class="info-item"><span class="info-label">Version</span><span>2.0.0</span></div>
        <div class="info-item"><span class="info-label">Panel Port</span><span>${sysInfo.panel_port||8001}</span></div>
        <div class="info-item"><span class="info-label">Device</span><span>${esc(sysInfo.device||'unknown')}</span></div>
        <div class="info-item"><span class="info-label">Kernel</span><span>${esc(sysInfo.kernel||'unknown')}</span></div>
        <div class="info-item"><span class="info-label">CPU Cores</span><span>${sysInfo.cpu_cores||'-'}</span></div>
        <div class="info-item"><span class="info-label">Free Storage</span><span>${diskFree}</span></div>
        <div class="info-item"><span class="info-label">Mode</span><span>${esc((sysInfo.mode||{}).mode||'unknown')}</span></div>
        <div class="info-item"><span class="info-label">Node Name</span><span>${esc(sysInfo.node_name||'local')}</span></div>
      </div>
      <hr style="border-color:var(--border);margin:16px 0">
      <div style="text-align:center;padding:12px 0">
        <p style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px">Powered by <span style="color:var(--accent)">ANDREBARRETOIT</span></p>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px">Android Konteiner Platform</p>
        <div style="display:flex;gap:12px;justify-content:center">
          <a href="https://linkedin.com/in/andrebarretoit" target="_blank" class="btn btn-ghost btn-sm"><i class="bi bi-linkedin"></i> LinkedIn</a>
          <a href="https://andrebarretoit.com" target="_blank" class="btn btn-ghost btn-sm"><i class="bi bi-globe"></i> Portfolio</a>
        </div>
      </div>
    </div></div>`;
  } else if (section === 'ank-manager') {
    el.innerHTML = `<div class="card"><div class="card-header"><h3><i class="bi bi-speedometer2"></i> ANK Manager</h3></div><div class="card-body">
      <div id="ank-mgr-status" style="display:flex;align-items:center;gap:12px;margin-bottom:20px;padding:16px;background:var(--bg-base);border-radius:8px">
        <span id="ank-mgr-dot" style="font-size:18px;color:var(--text-muted)">\u25cf</span>
        <div><div id="ank-mgr-state" style="font-weight:600;font-size:14px">Checking...</div><div id="ank-mgr-detail" style="font-size:12px;color:var(--text-secondary)"></div></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">
        <button class="btn btn-primary btn-sm" id="ank-mgr-restart-server"><i class="bi bi-arrow-clockwise"></i> Restart Server</button>
        <button class="btn btn-ghost btn-sm" id="ank-mgr-stop"><i class="bi bi-stop-circle"></i> Stop Server</button>
        <button class="btn btn-ghost btn-sm" id="ank-mgr-reboot"><i class="bi bi-phone"></i> Restart Device</button>
        <button class="btn btn-danger btn-sm" id="ank-mgr-uninstall"><i class="bi bi-trash3"></i> Uninstall ANK</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
        <label class="form-label" style="margin:0">Live Logs</label>
        <select class="form-select" id="ank-mgr-log-type" style="width:auto;padding:4px 8px;font-size:12px">
          <option value="server">Server (live)</option>
          <option value="service">Service (legacy)</option>
          <option value="install">Install</option>
        </select>
        <label style="display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-secondary);cursor:pointer"><input type="checkbox" id="ank-mgr-log-auto" checked style="accent-color:var(--accent)"> Auto-scroll</label>
        <button class="btn btn-ghost btn-sm" id="ank-mgr-log-refresh"><i class="bi bi-arrow-clockwise"></i></button>
      </div>
      <pre id="ank-mgr-logs" style="background:var(--bg-base);color:var(--text-secondary);border:1px solid var(--border);border-radius:8px;padding:12px;max-height:300px;overflow-y:auto;font-family:'Consolas','Courier New',monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-all"></pre>
    </div></div>`;
    let _mgrLogOffset = 0;
    let _mgrLogPoll = null;
    async function loadMgrStatus() {
      try {
        const s = await api('GET', '/ank-manager/status');
        document.getElementById('ank-mgr-dot').style.color = s.running ? 'var(--success)' : 'var(--danger)';
        document.getElementById('ank-mgr-state').textContent = s.running ? 'Running' : 'Stopped';
        document.getElementById('ank-mgr-detail').textContent = s.running ? `PID: ${s.pid} | Uptime: ${s.uptime} | Containers: ${s.containers}` : 'Server is not running';
      } catch(e) {
        document.getElementById('ank-mgr-dot').style.color = 'var(--danger)';
        document.getElementById('ank-mgr-state').textContent = 'Unreachable';
        document.getElementById('ank-mgr-detail').textContent = 'Cannot connect to ANK server';
      }
    }
    async function loadMgrLogs() {
      const logType = document.getElementById('ank-mgr-log-type')?.value || 'server';
      try {
        const r = await fetch(`${API}/ank-manager/logs?type=${logType}&lines=150`, { headers: { 'X-ANK-Client': 'ank-panel', 'Authorization': `Bearer ${ankToken}` } });
        const data = await r.json();
        const el = document.getElementById('ank-mgr-logs');
        if (!el) return;
        el.textContent = (data.lines && data.lines.length) ? data.lines.join('\n') : '(no log output yet)';
        if (document.getElementById('ank-mgr-log-auto')?.checked) el.scrollTop = el.scrollHeight;
      } catch(e) {}
    }
    loadMgrStatus();
    loadMgrLogs();
    if (window._ankMgrLogPoll) clearInterval(window._ankMgrLogPoll);
    window._ankMgrLogPoll = setInterval(loadMgrLogs, 5000);
    document.getElementById('ank-mgr-restart-server')?.addEventListener('click', async () => {
      const ok = await confirmAction('Restart Server', 'Restart the ANK server process?');
      if (!ok) return;
      showRestartModal('server');
    });
    document.getElementById('ank-mgr-stop')?.addEventListener('click', async () => {
      const ok = await confirmAction('Stop Server', 'Stop all containers and the ANK server?');
      if (!ok) return;
      try { await api('POST', '/ank-manager/stop'); toast('Stopping...', 'info'); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
    });
    document.getElementById('ank-mgr-reboot')?.addEventListener('click', async () => {
      const ok = await confirmAction('Restart Device', 'This will reboot the Android device. Continue?');
      if (!ok) return;
      showRestartModal('device');
    });
    document.getElementById('ank-mgr-uninstall')?.addEventListener('click', async () => {
      const ok = await confirmAction('Uninstall ANK', 'This will PERMANENTLY delete ALL containers, images, data, and ANK itself. This cannot be undone!');
      if (!ok) return;
      try { await api('POST', '/ank-manager/uninstall'); toast('Uninstalling... device will reboot.', 'info'); } catch(e) { toast(`Failed: ${e.message}`, 'error'); }
    });
    document.getElementById('ank-mgr-log-refresh')?.addEventListener('click', loadMgrLogs);
    document.getElementById('ank-mgr-log-type')?.addEventListener('change', loadMgrLogs);
  }
}

async function loadSettings() {
  try {
    settingsConfig = await api('GET', '/config');
  } catch(e) { settingsConfig = {}; }
  try {
    settingsInfo = await api('GET', '/system/info');
  } catch(e) { settingsInfo = {}; }
  refreshSeconds = parseInt(settingsConfig.refresh_interval != null ? settingsConfig.refresh_interval : localStorage.getItem('ank_refresh') || '10');
  localStorage.setItem('ank_refresh', refreshSeconds);
  showSettingsSection('account');
}

async function refreshCacheInfo() {
  try {
    const c = await api('GET', '/system/cache');
    const el = (id) => document.getElementById(id);
    if (el('info-rootfs')) el('info-rootfs').textContent = c.rootfs_size || '-';
    if (el('info-containers-size')) el('info-containers-size').textContent = c.containers_size || '-';
    if (el('info-total-size')) el('info-total-size').textContent = c.total_size || '-';
    toast('Cache info updated', 'success');
  } catch(e) { toast('Failed to refresh', 'error'); }
}

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

/* ═══════ SHELL ═══════ */
let coreTerminal = null;
let coreWs = null;
let wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';

async function detectWsProtocol() {
  try { const res = await fetch(API+'/protocol', { headers: { 'X-ANK-Client': 'ank-panel', 'Authorization': 'Bearer '+ankToken } }); if (res.ok) { const d = await res.json(); wsProtocol = d.protocol==='https'?'wss:':'ws:'; } } catch(e) {}
}

async function initCoreTerminal() {
  const el = document.getElementById('terminal');
  if (!el) return;
  if (coreTerminal) { try { coreTerminal.dispose(); } catch(e){} coreTerminal = null; }
  if (coreWs) { try { coreWs.close(); } catch(e){} coreWs = null; }
  el.innerHTML = '';
  let nodeLabel = 'ank-shell';
  try { const c = await api('GET', '/config'); nodeLabel = c.node_name || 'ank-shell'; } catch(e) {}
  try {
    coreTerminal = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: "'Cascadia Code','Fira Code',monospace", theme: { background: '#0a0d12', foreground: '#d3d9e3', cursor: '#58a6ff' }, scrollback: 5000 });
    coreTerminal.open(el);
    coreTerminal.writeln('\x1b[1;36m  ANK \x1b[1;32m●\x1b[0m \x1b[1;36mAndroid Konteiner\x1b[0m\r\n');
    coreTerminal.writeln('\x1b[90m  root@' + nodeLabel + '\x1b[0m\r\n');
    const titleEl = document.getElementById('shell-terminal-title');
    if (titleEl) titleEl.textContent = 'root@' + nodeLabel;
    coreTerminal.focus();
    connectCoreWs();
    const dcBtn = document.getElementById('btn-shell-disconnect');
    if (dcBtn) dcBtn.style.display = '';
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
  coreWs.onopen = () => {
    if (coreTerminal) {
      let remoteLabel = '';
      if (isRemote) {
        try {
          const sel = document.getElementById('shell-container-select');
          remoteLabel = sel?.options[sel.selectedIndex]?.text || nodeId;
        } catch(e) { remoteLabel = nodeId; }
      }
      const label = isRemote ? remoteLabel : (document.getElementById('shell-terminal-title')?.textContent?.replace('root@','') || 'ank-shell');
      coreTerminal.writeln('\x1b[90m  Connected' + (isRemote ? ' to ' + label : '') + '.\x1b[0m\r\n');
      coreTerminal.focus();
    }
  };
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
  const dcBtn = document.getElementById('btn-shell-disconnect');
  if (dcBtn) dcBtn.style.display = 'none';
});
document.getElementById('btn-shell-pip')?.addEventListener('click', () => {
  if (coreTerminal && coreWs && coreWs.readyState === WebSocket.OPEN) {
    openPip('shell');
  } else {
    toast('Connect to shell first', 'warning');
  }
});

/* ═══════ CONTAINER TERMINAL ═══════ */
let xtermTerminal = null;
let xtermWs = null;

function initContainerTerminal() {
  const el = document.getElementById('container-terminal');
  if (!el) return;
  const isRemote = currentContainer._nodeId && currentContainer._nodeId !== 'local';
  if (!currentContainer) {
    el.innerHTML = '<div style="color:var(--danger);padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> No container selected</div>';
    return;
  }
  if (!isRemote && currentContainer.status !== 'running') {
    el.innerHTML = '<div style="color:var(--danger);padding:20px;text-align:center"><i class="bi bi-exclamation-triangle"></i> Container not running</div>';
    return;
  }
  if (xtermTerminal) { try { xtermTerminal.dispose(); } catch(e){} xtermTerminal = null; }
  if (xtermWs) { try { xtermWs.close(); } catch(e){} xtermWs = null; }
  el.innerHTML = '';

  const pipBar = document.createElement('div');
  pipBar.className = 'terminal-pip-bar';
  pipBar.innerHTML = `<button class="btn btn-ghost btn-sm pip-open-btn" title="Picture-in-Picture"><i class="bi bi-window-stack"></i> PiP</button>`;
  pipBar.querySelector('.pip-open-btn').addEventListener('click', () => openPip('container'));
  el.appendChild(pipBar);

  const termWrap = document.createElement('div');
  termWrap.style.cssText = 'flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden;';
  el.appendChild(termWrap);

  try {
    xtermTerminal = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: "'Cascadia Code','Fira Code',monospace", theme: { background: '#0a0d12', foreground: '#d3d9e3', cursor: '#58a6ff' }, scrollback: 5000 });
    xtermTerminal.open(termWrap);
    xtermTerminal.writeln('\x1b[1;36m  ANK Terminal\x1b[0m');
    xtermTerminal.writeln('\x1b[90m  Connecting to: ' + currentContainer.name + (isRemote ? ' (node: ' + currentContainer._nodeId + ')' : '') + '...\x1b[0m\r\n');
    xtermTerminal.focus();
    let wsUrl;
    if (isRemote) {
      wsUrl = wsProtocol+'//'+location.host+'/ws/node-terminal/'+encodeURIComponent(currentContainer._nodeId)+'/'+encodeURIComponent(currentContainer.name)+'?cols='+(xtermTerminal.cols||80)+'&rows='+(xtermTerminal.rows||24)+'&token='+encodeURIComponent(ankToken);
    } else {
      wsUrl = wsProtocol+'//'+location.host+'/ws/terminal/'+currentContainer.name+'?cols='+(xtermTerminal.cols||80)+'&rows='+(xtermTerminal.rows||24)+'&token='+encodeURIComponent(ankToken);
    }
    xtermWs = new WebSocket(wsUrl);
    xtermWs.onopen = () => { xtermTerminal.focus(); };
    xtermWs.onmessage = ev => { xtermTerminal.write(ev.data); };
    xtermWs.onclose = () => { xtermTerminal.writeln('\r\n\x1b[31m[Connection closed]\x1b[0m'); };
    xtermWs.onerror = () => { xtermTerminal.writeln('\r\n\x1b[31m[Connection error]\x1b[0m'); };
    xtermTerminal.onData(data => { if (xtermWs && xtermWs.readyState === WebSocket.OPEN) xtermWs.send(JSON.stringify({ type: 'input', data })); });
    const resize = () => { const rect = termWrap.getBoundingClientRect(); const cols = Math.floor(rect.width/8.4); const rows = Math.floor(rect.height/18); if (cols>0&&rows>0) { xtermTerminal.resize(cols,rows); if (xtermWs&&xtermWs.readyState===WebSocket.OPEN) xtermWs.send(JSON.stringify({type:'resize',cols,rows})); } };
    window.addEventListener('resize', resize);
    setTimeout(resize, 100);
  } catch(e) { termWrap.innerHTML = '<div style="color:var(--danger);padding:20px">xterm.js failed to load</div>'; }
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
  try {
    const headers = { 'X-ANK-Client': 'ank-panel' };
    if (ankToken) headers['Authorization'] = 'Bearer ' + ankToken;
    const res = await fetch(`${API}/containers/${fileContainerName}/files/download?path=${encodeURIComponent(path)}`, { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    let name = path.split('/').pop();
    const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
    if (m) name = decodeURIComponent(m[1]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) {
    toast(`Download failed: ${e.message}`, 'error');
  }
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
    const isRemote = currentContainer._nodeId && currentContainer._nodeId !== 'local';
    let data, health;
    if (isRemote) {
      const nid = encodeURIComponent(currentContainer._nodeId);
      const cname = encodeURIComponent(currentContainer.name);
      data = await api('GET', `/nodes/${nid}/containers/${cname}/services`).catch(() => ({services:[]}));
      health = await api('GET', `/nodes/${nid}/containers/${cname}/health`).catch(() => null);
    } else {
      [data, health] = await Promise.all([
        api('GET', `/containers/${currentContainer.name}/services`),
        api('GET', `/containers/${currentContainer.name}/health`).catch(() => null)
      ]);
    }
    const services = data.services || [];
    const containerStatus = currentContainer.status || 'stopped';
    const isRunning = containerStatus === 'running';
    const isBuilding = containerStatus === 'building';
    const canManage = isRunning && !isBuilding;

    // Health status banner
    let healthBanner = '';
    if (health && health.status) {
      if (health.status === 'running') {
        healthBanner = `<div style="padding:8px 12px;border-radius:var(--radius-sm);background:var(--success-dim);margin-bottom:12px;font-size:12px;display:flex;align-items:center;gap:12px"><i class="bi bi-check-circle-fill" style="color:var(--success)"></i><span style="color:var(--success)">Container healthy</span></div>`;
      } else if (health.status === 'stopped') {
        healthBanner = `<div style="padding:8px 12px;border-radius:var(--radius-sm);background:var(--danger-dim);margin-bottom:12px;font-size:12px;display:flex;align-items:center;gap:12px"><i class="bi bi-x-circle-fill" style="color:var(--danger)"></i><span style="color:var(--danger)">Container stopped</span></div>`;
      } else {
        const sshOk = health.ssh_alive ? '<span style="color:var(--success)">SSH OK</span>' : '<span style="color:var(--danger)">SSH Down</span>';
        let ankdOk;
        if (health.ankd_alive) {
          ankdOk = `<span style="color:var(--success)">Ankd OK${health.ankd_port_probed && health.ankd_port ? ' (port ' + health.ankd_port + ')' : ''}</span>`;
        } else if (health.ankd_alive === false) {
          ankdOk = '<span style="color:var(--danger)">Ankd Down</span>';
        } else {
          ankdOk = '<span style="color:var(--warning)">Ankd N/A</span>';
        }
        healthBanner = `<div style="padding:8px 12px;border-radius:var(--radius-sm);background:var(--warning-dim);margin-bottom:12px;font-size:12px;display:flex;align-items:center;gap:12px"><i class="bi bi-exclamation-triangle" style="color:var(--warning)"></i><span>Degraded: ${sshOk} | ${ankdOk}</span></div>`;
      }
    }

    if (services.length === 0) {
      el.innerHTML = healthBanner + '<div class="empty-state" style="padding:20px"><p style="color:var(--text-muted)">No services configured</p></div>';
      return;
    }
    el.innerHTML = healthBanner + services.map(svc => {
      const isSvcRunning = svc.status === 'running';
      return `<div class="service-item">
        <div class="service-info">
          <div class="service-dot ${isSvcRunning?'running':'stopped'}"></div>
          <div>
            <div class="service-name">${esc(svc.name)} ${svc.enabled?'<span style="color:var(--success);font-size:11px">ON</span>':'<span style="color:var(--text-muted);font-size:11px">OFF</span>'}</div>
            <div class="service-cmd">${esc(svc.cmd||'no command')}</div>
          </div>
        </div>
        <div class="service-actions">
          <button class="btn btn-sm btn-ghost" onclick="taskManagerViewLog('${esc(svc.name)}')" title="View Log"><i class="bi bi-journal-text"></i></button>
          ${isSvcRunning
            ? `<button class="btn btn-sm btn-secondary" onclick="taskManagerServiceAction('${esc(svc.name)}','stop')" title="Stop" ${!canManage?'disabled':''}><i class="bi bi-stop-fill"></i></button>
               <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','restart')" title="Restart" ${!canManage?'disabled':''}><i class="bi bi-arrow-clockwise"></i></button>`
            : `<button class="btn btn-sm btn-success" onclick="taskManagerServiceAction('${esc(svc.name)}','start')" title="Start" ${!canManage?'disabled':''}><i class="bi bi-play-fill"></i></button>`
          }
          <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','${svc.enabled?'disable':'enable'}')" title="${svc.enabled?'Disable':'Enable'}" ${!canManage?'disabled':''}><i class="bi bi-${svc.enabled?'pause':'play'}-circle"></i></button>
          <button class="btn btn-sm btn-ghost" onclick="taskManagerServiceAction('${esc(svc.name)}','delete')" title="Delete" style="color:var(--danger)" ${!canManage?'disabled':''}><i class="bi bi-trash3"></i></button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = `<div class="empty-state">Failed to load services: ${esc(e.message)}</div>`; }
}

async function taskManagerServiceAction(service, action) {
  if (!currentContainer) return;
  if (action === 'delete') { const ok = await confirmAction('Delete Service', `Delete service "${service}"?`); if (!ok) return; }
  const past = { stop: 'stopped', start: 'started', restart: 'restarted', enable: 'enabled', disable: 'disabled' }[action] || 'updated';
  try {
    if (action === 'delete') { await api('DELETE', `/containers/${currentContainer.name}/services/${service}`); }
    else { await api('POST', `/containers/${currentContainer.name}/services/${service}/${action}`); }
    toast(`Service "${service}" ${past}`, 'success');
    setTimeout(loadTaskManager, 500);
    // ankd completes the action asynchronously (the daemon may pick up
    // the request up to ~3s later) — re-poll to catch the final state.
    if (action === 'stop' || action === 'start' || action === 'restart') {
      setTimeout(loadTaskManager, 4000);
    }
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
let refreshCycle = 0;
let _formDirty = false;
let _ankMgrPoll = null;

function startRefreshTimer() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (refreshSeconds <= 0) return;
  refreshTimer = setInterval(async () => {
    if (!isLoggedIn || document.getElementById('app').classList.contains('hidden') || document.hidden) return;
    if (_formDirty) return;
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT' || ae.isContentEditable)) return;
    refreshCycle++;
    try {
      const activePage = document.querySelector('.page.active');
      if (!activePage) return;
      const pageId = activePage.id;

      if (pageId === 'page-dashboard') {
        const [status, info] = await Promise.all([api('GET', '/status'), api('GET', '/system/info')]);
        animateCounter('stat-running', status.containers_running || 0);
        animateCounter('stat-stopped', status.containers_stopped || 0);
        animateCounter('stat-total', status.containers_total || 0);
        document.getElementById('dash-uptime').textContent = 'uptime ' + fmtUptime(status.uptime || 0);
        const cpuPct = info.cpu_usage != null ? Math.round(info.cpu_usage) : 0;
        document.getElementById('gauge-cpu-text').textContent = cpuPct + '%';
        document.getElementById('gauge-cpu').style.width = cpuPct + '%';
        pushSpark('cpu', cpuPct);
        renderSparkline('spark-cpu', sparkHistory.cpu);
        const memT = info.memory?.total_kb || 0;
        const memA = info.memory?.available_kb || 0;
        const memPct = memT > 0 ? Math.round((memT - memA) / memT * 100) : 0;
        document.getElementById('gauge-ram-text').textContent = memPct + '%';
        document.getElementById('gauge-ram').style.width = memPct + '%';
        document.getElementById('ram-detail').textContent = memT > 0 ? `${fmtBytes((memT-memA) * 1024)} / ${fmtBytes(memT * 1024)}` : '';
        pushSpark('ram', memPct);
        renderSparkline('spark-ram', sparkHistory.ram);
        const disk = status.disk || {};
        const diskTotal = disk.total || 0;
        const diskUsedNum = disk.used_num || 0;
        const diskPct = diskTotal > 0 ? Math.round(diskUsedNum / diskTotal * 100) : 0;
        document.getElementById('gauge-disk-text').textContent = diskPct + '%';
        document.getElementById('gauge-disk').style.width = diskPct + '%';
        document.getElementById('disk-detail').textContent = diskTotal > 0 ? `${disk.used || '-'} / ${diskTotal} GB` : '';
        pushSpark('disk', diskPct);
        renderSparkline('spark-disk', sparkHistory.disk);
        renderDashboardContainers();
        renderDashboardNodes();
      } else if (pageId === 'page-containers') {
        await loadContainers();
        if (selectedContainerName) {
          document.querySelectorAll('#containers-list .split-list-card').forEach(c => c.classList.toggle('selected', c.dataset.name === selectedContainerName));
        }
        if (currentContainer) {
          try {
            const updated = await api('GET', `/containers/${currentContainer.name}`);
            if (updated) {
              currentContainer = updated;
              updateContainerBadge(currentContainer.name, updated.status);
              updateDetailButtons(currentContainer.name, updated.status);
            }
          } catch(e) {}
        }
      } else if (pageId === 'page-images') {
        const sel = document.querySelector('#images-list .split-list-card.selected');
        const activeSection = sel ? sel.dataset.section : 'quick-deploy';
        await loadImages();
        showImageSection(activeSection);
      } else if (pageId === 'page-nodes') {
        loadNodes();
      } else if (pageId === 'page-stacks') {
        loadStacks();
      } else if (pageId === 'page-backups') {
        loadBackups();
      } else if (pageId === 'page-networks') {
        loadNetworks();
      }
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
    const tpl = cachedTemplates.find(t => t.id === templateId);
    const imageField = tpl ? tpl.image : templateId;
    try {
      if (isRemote) {
        toast(`Deploying on remote...`, 'info');
        await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name, image: imageField, root_password: rootPass });
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
        const color = x.status === 'running' ? 'var(--success)' : x.status === 'building' ? 'var(--warning)' : x.status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
        return `<div class="np-row" onclick="notchPreviewHide();navigateTo('containers');setTimeout(()=>showContainerDetail('${esc(x.name)}','${x.node||'local'}'),100)" style="cursor:pointer"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(x.name)}</span><span class="badge ${getStatusBadgeClass(x.status)}" style="font-size:9px">${getStatusLabel(x.status)}</span></div>`;
      }).join(''); }
    } else if (page === 'images') {
      const [img, tpl] = await Promise.all([api('GET', '/images/all').catch(()=>[]), api('GET', '/images/templates').catch(()=>[])]);
      const templates = Array.isArray(tpl) ? tpl : (tpl.templates || []);
      html += `<div style="margin-bottom:8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Quick Deploy</div>`;
      html += templates.map(t => `<div class="np-row" onclick="notchPreviewHide();deployTemplate('${esc(t.id)}','${esc(t.name)}',${t.base_ready})" style="cursor:pointer"><i class="bi ${t.icon||'bi-box-seam'}" style="color:${t.color||'var(--primary)'};font-size:12px"></i><span class="np-name">${esc(t.name)}</span><span class="template-badge ${t.base_ready?'ready':'pending'}" style="font-size:9px">${t.base_ready?'Ready':'Pull'}</span></div>`).join('');
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('images');setTimeout(()=>showImageSection('ankfile'),100)" style="cursor:pointer"><i class="bi bi-file-earmark-code" style="color:var(--accent);font-size:12px"></i><span class="np-name">Ankfile Builder</span><span class="text-muted text-sm">Custom image</span></div>`;
      if (img.length) {
        html += `<div style="margin:12px 0 8px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase">Ank Images (${img.length})</div>`;
        html += img.map(x => `<div class="np-row" onclick="notchPreviewHide();navigateTo('images')" style="cursor:pointer"><i class="bi bi-hdd-stack" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(x.name)}</span><span class="text-muted text-sm">${x.size_human||''}</span></div>`).join('');
      }
      if (!img.length && !templates.length) html += '<div class="np-empty">No images</div>';
    } else if (page === 'nodes') {
      const d = await api('GET', '/nodes').catch(()=>({nodes:[]}));
      const nodes = d.nodes || [];
      if (!nodes.length) { html += '<div class="np-empty">No nodes</div>'; }
      else { html += nodes.map(n => {
        const color = n.status === 'online' ? 'var(--success)' : 'var(--danger)';
        return `<div class="np-row" onclick="notchPreviewHide();navigateTo('nodes');setTimeout(()=>showNodeDetail('${esc(n.id)}','','${n.status}'),100)" style="cursor:pointer"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(n.alias||n.ip)}</span><span class="text-muted text-sm">${n.status} · CPU ${Math.round(n.cpu_percent||0)}% · RAM ${(n.mem_used_gb||0).toFixed(1)}GB · ${(n.containers_total||0)} containers</span></div>`;
      }).join(''); }
    } else if (page === 'stacks') {
      const d = await api('GET', '/stacks/all').catch(()=>({stacks:[]}));
      const stacks = d.stacks || [];
      if (!stacks.length) { html += '<div class="np-empty">No stacks</div>'; }
      else { html += stacks.map(s => {
        const running = (s.containers||[]).filter(c=>c.status==='running').length;
        const total = (s.containers||[]).length;
        return `<div class="np-row" onclick="notchPreviewHide();navigateTo('stacks')" style="cursor:pointer"><i class="bi bi-layers" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(s.name)}</span><span class="text-muted text-sm">${running}/${total} · LB ${s.port||s.lb_port||'-'}</span></div>`;
      }).join(''); }
    } else if (page === 'networks') {
      const nets = await api('GET', '/networks').catch(()=>[]);
      if (!nets.length) { html += '<div class="np-empty">No networks</div>'; }
      else { html += nets.map(n => `<div class="np-row" onclick="notchPreviewHide();navigateTo('networks')" style="cursor:pointer"><i class="bi bi-globe2" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(n.name)}</span><span class="text-muted text-sm">${n.mode} · ${n.subnet||''} GW:${n.gateway||''} · NAT:${n.nat?'On':'Off'} · ${(n.containers?.length||0)} containers</span></div>`).join(''); }
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
        html += containers.map(x => {
          const color = x.status === 'running' ? 'var(--success)' : x.status === 'building' ? 'var(--warning)' : x.status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
          return `<div class="np-row" onclick="notchPreviewHide();navigateTo('containers');setTimeout(()=>showContainerDetail('${esc(x.name)}','${x.node||'local'}'),100)" style="cursor:pointer"><span class="dot" style="background:${color}"></span><span class="np-name">${esc(x.name)}</span><span class="badge ${getStatusBadgeClass(x.status)}" style="font-size:9px">${getStatusLabel(x.status)}</span></div>`;
        }).join('');
      }
    } else if (page === 'settings') {
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('settings');setTimeout(()=>showSettingsSection('account'),100)" style="cursor:pointer"><i class="bi bi-person-gear" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Account</span><span class="text-muted text-sm">Change password</span></div>`;
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('settings');setTimeout(()=>showSettingsSection('server'),100)" style="cursor:pointer"><i class="bi bi-server" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Server</span><span class="text-muted text-sm">Bind, refresh, autostart</span></div>`;
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('settings');setTimeout(()=>showSettingsSection('remote'),100)" style="cursor:pointer"><i class="bi bi-diagram-3" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Remote & SSH</span><span class="text-muted text-sm">Management, port</span></div>`;
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('settings');setTimeout(()=>showSettingsSection('about'),100)" style="cursor:pointer"><i class="bi bi-info-circle" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">About</span><span class="text-muted text-sm">Cache, storage</span></div>`;
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('settings');setTimeout(()=>showSettingsSection('danger'),100)" style="cursor:pointer"><i class="bi bi-exclamation-triangle" style="color:var(--danger);font-size:12px"></i><span class="np-name" style="color:var(--danger)">Danger Zone</span><span class="text-muted text-sm">Restart, uninstall</span></div>`;
    } else if (page === 'logs') {
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('logs')" style="cursor:pointer"><i class="bi bi-terminal" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Live Log Viewer</span><span class="text-muted text-sm">Colorize · Pause · Filter</span></div>`;
    } else if (page === 'shell') {
      html += `<div class="np-row" onclick="notchPreviewHide();navigateTo('shell')" style="cursor:pointer"><i class="bi bi-terminal" style="color:var(--text-muted);font-size:12px"></i><span class="np-name">Core Shell</span><span class="text-muted text-sm">WebSocket terminal</span></div>`;
    } else if (page === 'backups') {
      const d = await api('GET', '/backups').catch(()=>({routines:[]}));
      const r = d.routines || [];
      if (!r.length) { html += '<div class="np-empty">No backups</div>'; }
      else { html += r.map(b => {
        const lastRun = b.last_run ? new Date(b.last_run).toLocaleString() : 'Never';
        const statusColor = b.last_status === 'success' ? 'var(--success)' : b.last_status === 'failed' ? 'var(--danger)' : 'var(--text-muted)';
        return `<div class="np-row" onclick="notchPreviewHide();navigateTo('backups')" style="cursor:pointer"><i class="bi bi-cloud-arrow-up" style="color:var(--accent);font-size:12px"></i><span class="np-name">${esc(b.name)}</span><span class="text-muted text-sm">${b.schedule||'-'} · Retention: ${b.retention||30}d · Last: ${lastRun}</span><span style="width:6px;height:6px;border-radius:50%;background:${statusColor};flex-shrink:0"></span></div>`;
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
      }, 1000);
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

/* ═══════ LITE MODE OVERLAY ═══════ */
function applyLiteOverlay() {
  if (!ankLiteMode) return;
  document.body.classList.add('ank-lite');

  // Networks page: full overlay
  const networksPage = document.getElementById('page-networks');
  if (networksPage && !ankModeFeatures.network_isolation) {
    const layout = networksPage.querySelector('.split-layout');
    if (layout && !layout.classList.contains('lite-overlay')) {
      layout.classList.add('lite-overlay');
      const badge = document.createElement('div');
      badge.className = 'lite-badge';
      badge.innerHTML = '<i class="bi bi-globe2"></i><strong>Limited</strong><span>Network isolation not available in lite mode</span><small>Containers share host network</small>';
      layout.appendChild(badge);
    }
  }

  // Hide nav items that are disabled
  if (!ankModeFeatures.network_isolation) {
    document.querySelectorAll('[data-page="networks"]').forEach(el => {
      el.style.opacity = '0.4';
      el.title = 'Network isolation not available in lite mode';
    });
  }
}

/* ═══════ THEME TOGGLE ═══════ */
function getTheme() { return localStorage.getItem('ank_theme') || document.documentElement.getAttribute('data-theme') || 'dark'; }
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('ank_theme', theme);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0a0d12' : '#ffffff');
  const icon = theme === 'dark' ? 'bi-moon-stars' : 'bi-sun';
  document.querySelectorAll('#theme-toggle-login i, #theme-toggle-mobile i, #theme-toggle-desktop i, .theme-toggle-page i').forEach(i => {
    i.className = 'bi ' + icon;
  });
}
function toggleTheme() { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); }
// Apply saved theme on boot
setTheme(getTheme());

/* ═══════ PICTURE-IN-PICTURE TERMINAL ═══════ */
let pipState = {
  active: false,
  terminal: null,
  ws: null,
  container: null,
  containerName: '',
  source: null,
  dragOffsetX: 0,
  dragOffsetY: 0,
  isDragging: false
};

function createPipOverlay() {
  if (pipState.container) return;
  const overlay = document.createElement('div');
  overlay.id = 'pip-overlay';
  overlay.className = 'pip-overlay';
  overlay.innerHTML = `
    <div class="pip-titlebar" id="pip-titlebar">
      <span class="pip-title" id="pip-title">Terminal</span>
      <div class="pip-controls">
        <button class="pip-btn pip-restore" id="pip-restore" title="Restore to full view"><i class="bi bi-box-arrow-up-left"></i></button>
        <button class="pip-btn pip-close" id="pip-close" title="Close PiP"><i class="bi bi-x-lg"></i></button>
      </div>
    </div>
    <div class="pip-terminal" id="pip-terminal"></div>
  `;
  document.body.appendChild(overlay);
  pipState.container = overlay;

  overlay.style.right = '20px';
  overlay.style.bottom = '80px';

  document.getElementById('pip-close').addEventListener('click', closePip);
  document.getElementById('pip-restore').addEventListener('click', restorePip);

  const titlebar = document.getElementById('pip-titlebar');
  titlebar.addEventListener('mousedown', (e) => {
    if (e.target.closest('.pip-btn')) return;
    pipState.isDragging = true;
    const rect = overlay.getBoundingClientRect();
    pipState.dragOffsetX = e.clientX - rect.left;
    pipState.dragOffsetY = e.clientY - rect.top;
    overlay.style.transition = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!pipState.isDragging) return;
    const x = e.clientX - pipState.dragOffsetX;
    const y = e.clientY - pipState.dragOffsetY;
    pipState.container.style.left = Math.max(0, Math.min(window.innerWidth - 310, x)) + 'px';
    pipState.container.style.top = Math.max(0, Math.min(window.innerHeight - 230, y)) + 'px';
    pipState.container.style.right = 'auto';
    pipState.container.style.bottom = 'auto';
  });
  document.addEventListener('mouseup', () => {
    if (pipState.isDragging) {
      pipState.isDragging = false;
      pipState.container.style.transition = '';
    }
  });
}

function openPip(sourceType) {
  if (pipState.active) return;
  createPipOverlay();
  pipState.source = sourceType;
  pipState.active = true;

  const pipTerminalEl = document.getElementById('pip-terminal');
  pipTerminalEl.innerHTML = '';

  try {
    pipState.terminal = new Terminal({
      cursorBlink: true,
      fontSize: 11,
      fontFamily: "'Cascadia Code','Fira Code',monospace",
      theme: { background: '#0a0d12', foreground: '#d3d9e3', cursor: '#58a6ff' },
      scrollback: 2000
    });
    pipState.terminal.open(pipTerminalEl);

    if (sourceType === 'shell') {
      document.getElementById('pip-title').textContent = 'Shell Terminal';
      if (coreTerminal && coreWs && coreWs.readyState === WebSocket.OPEN) {
        pipState.terminal.writeln('\x1b[1;36m  ANK PiP \x1b[1;32m●\x1b[0m \x1b[90mShell mirror\x1b[0m\r\n');
        pipState.terminal.writeln('\x1b[90m  Live view of shell terminal\x1b[0m\r\n');
        const origWrite = coreTerminal.write.bind(coreTerminal);
        coreTerminal.write = (data) => {
          origWrite(data);
          if (pipState.terminal && pipState.active) pipState.terminal.write(data);
        };
        pipState._restoreWrite = origWrite;
        pipState.terminal.focus();
      } else {
        pipState.terminal.writeln('\x1b[31m  No active shell connection\x1b[0m');
      }
    } else if (sourceType === 'container' && currentContainer) {
      const cname = currentContainer.name;
      pipState.containerName = cname;
      document.getElementById('pip-title').textContent = cname + ' Terminal';

      const isRemote = currentContainer._nodeId && currentContainer._nodeId !== 'local';
      const cols = pipState.terminal.cols || 80;
      const rows = pipState.terminal.rows || 24;
      let wsUrl;
      if (isRemote) {
        wsUrl = wsProtocol+'//'+location.host+'/ws/node-terminal/'+encodeURIComponent(currentContainer._nodeId)+'/'+encodeURIComponent(cname)+'?cols='+cols+'&rows='+rows+'&token='+encodeURIComponent(ankToken);
      } else {
        wsUrl = wsProtocol+'//'+location.host+'/ws/terminal/'+cname+'?cols='+cols+'&rows='+rows+'&token='+encodeURIComponent(ankToken);
      }

      pipState.ws = new WebSocket(wsUrl);
      pipState.ws.onopen = () => {
        pipState.terminal.writeln('\x1b[1;36m  ANK PiP \x1b[1;32m●\x1b[0m \x1b[90m' + esc(cname) + '\x1b[0m\r\n');
        pipState.terminal.focus();
      };
      pipState.ws.onmessage = ev => { if (pipState.terminal) pipState.terminal.write(ev.data); };
      pipState.ws.onclose = () => { if (pipState.terminal) pipState.terminal.writeln('\r\n\x1b[31m[Connection closed]\x1b[0m'); };
      pipState.ws.onerror = () => { if (pipState.terminal) pipState.terminal.writeln('\r\n\x1b[31m[Connection error]\x1b[0m'); };
      pipState.terminal.onData(data => { if (pipState.ws && pipState.ws.readyState === WebSocket.OPEN) pipState.ws.send(JSON.stringify({ type: 'input', data })); });

      const resize = () => {
        if (!pipState.terminal || !pipState.container) return;
        const rect = pipTerminalEl.getBoundingClientRect();
        const c = Math.floor(rect.width / 7);
        const r = Math.floor(rect.height / 15);
        if (c > 0 && r > 0) {
          pipState.terminal.resize(c, r);
          if (pipState.ws && pipState.ws.readyState === WebSocket.OPEN) pipState.ws.send(JSON.stringify({ type: 'resize', cols: c, rows: r }));
        }
      };
      pipState._resizeHandler = resize;
      window.addEventListener('resize', resize);
      setTimeout(resize, 100);
    }

    pipState.container.style.display = '';
    toast('PiP terminal opened', 'info', 2000);
  } catch (e) {
    console.error('PiP failed:', e);
    closePip();
  }
}

function closePip() {
  if (pipState._resizeHandler) {
    window.removeEventListener('resize', pipState._resizeHandler);
    pipState._resizeHandler = null;
  }
  if (pipState.source === 'shell' && pipState._restoreWrite) {
    if (coreTerminal) coreTerminal.write = pipState._restoreWrite;
    pipState._restoreWrite = null;
  }
  if (pipState.ws) { try { pipState.ws.close(); } catch(e){} pipState.ws = null; }
  if (pipState.terminal) { try { pipState.terminal.dispose(); } catch(e){} pipState.terminal = null; }
  if (pipState.container) { pipState.container.remove(); pipState.container = null; }
  pipState.active = false;
  pipState.source = null;
  pipState.containerName = '';
  pipState.isDragging = false;
}

function restorePip() {
  const source = pipState.source;
  const cname = pipState.containerName;
  closePip();
  if (source === 'shell') {
    navigateTo('shell');
  } else if (source === 'container' && cname) {
    navigateTo('containers');
    setTimeout(() => showContainerDetail(cname, currentContainer?._nodeId || 'local'), 200);
  }
}

function addPipButton(targetEl, sourceType) {
  if (!targetEl || targetEl.querySelector('.pip-open-btn')) return;
  const btn = document.createElement('button');
  btn.className = 'btn btn-ghost btn-sm pip-open-btn';
  btn.innerHTML = '<i class="bi bi-window-stack"></i> PiP';
  btn.title = 'Picture-in-Picture terminal';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    openPip(sourceType);
  });
  targetEl.appendChild(btn);
}
document.addEventListener('input', (e) => { if (e.target.matches('input,textarea,select')) _formDirty = true; }, true);
document.addEventListener('change', (e) => { if (e.target.matches('input,textarea,select')) _formDirty = true; }, true);
if (isLoggedIn) { showApp(); detectWsProtocol().then(() => startRefreshTimer()); }
// Theme toggle listeners
document.getElementById('theme-toggle-login')?.addEventListener('click', toggleTheme);
document.getElementById('theme-toggle-mobile')?.addEventListener('click', toggleTheme);
document.getElementById('theme-toggle-desktop')?.addEventListener('click', toggleTheme);
