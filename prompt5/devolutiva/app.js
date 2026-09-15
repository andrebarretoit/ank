'use strict';
const API = '/api';
let token = localStorage.getItem('ank_token') || '';
let wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
let refreshTimer = null;
let refreshSeconds = parseInt(localStorage.getItem('ank_refresh') || '10');
let logsPollTimer = null;
let logsOffset = 0;
let currentContainer = null;
let cdTerm = null, cdWs = null;
let shellTerm = null, shellWs = null;

/* ---------------- core fetch ---------------- */
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (res.status === 401) { doLogout(); throw new Error('Sessão expirada'); }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/* ---------------- toast / confirm ---------------- */
function toast(msg, type = 'info', duration = 4200) {
  const stack = document.getElementById('toast-stack');
  const icons = { success: 'bi-check-circle-fill', error: 'bi-x-circle-fill', warning: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill' };
  const el = document.createElement('div');
  el.className = `toast t-${type}`;
  el.innerHTML = `<i class="bi ${icons[type] || icons.info}"></i><span>${esc(msg)}</span>`;
  stack.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; el.style.transition = 'all .2s'; setTimeout(() => el.remove(), 200); }, duration);
}

function confirmDialog(title, message) {
  return new Promise((resolve) => {
    const modal = document.getElementById('modal-confirm');
    document.getElementById('cf-title').textContent = title;
    document.getElementById('cf-message').textContent = message;
    openModal('modal-confirm');
    const ok = document.getElementById('cf-ok'), cancel = document.getElementById('cf-cancel');
    const closeBtns = modal.querySelectorAll('[data-close]');
    function cleanup(val) {
      closeModal('modal-confirm');
      ok.replaceWith(ok.cloneNode(true));
      cancel.replaceWith(cancel.cloneNode(true));
      resolve(val);
    }
    document.getElementById('cf-ok').addEventListener('click', () => cleanup(true));
    document.getElementById('cf-cancel').addEventListener('click', () => cleanup(false));
    closeBtns.forEach(b => b.addEventListener('click', () => cleanup(false), { once: true }));
  });
}

/* ---------------- helpers ---------------- */
function esc(s) { if (s === null || s === undefined) return ''; return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function fmtBytes(b) { if (!b) return '0 B'; const k = 1024, u = ['B', 'KB', 'MB', 'GB', 'TB']; const i = Math.floor(Math.log(b) / Math.log(k)); return (b / Math.pow(k, i)).toFixed(1) + ' ' + u[i]; }
function fmtUptime(sec) { sec = sec || 0; const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60); if (d > 0) return `${d}d ${h}h`; if (h > 0) return `${h}h ${m}m`; return `${m}m`; }
function statusBadgeClass(s) { return `badge badge-${s || 'stopped'}`; }
function statusLabel(s) {
  const map = { running: 'Rodando', stopped: 'Parado', building: 'Compilando…', failed: 'Falhou', starting: 'Iniciando…', stopping: 'Parando…', pending: 'Pendente', online: 'Online', offline: 'Offline' };
  return map[s] || s || '-';
}

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
document.querySelectorAll('.modal').forEach(m => {
  m.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => closeModal(m.id)));
});
document.getElementById('modal-container-detail').addEventListener('click', (e) => { if (e.target.dataset.close !== undefined) closeContainerTerminal(); });

/* ---------------- auth ---------------- */
document.getElementById('form-login').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('btn-login');
  const username = document.getElementById('in-username').value;
  const password = document.getElementById('in-password').value;
  const err = document.getElementById('login-error');
  err.textContent = '';
  btn.disabled = true; btn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Entrando…';
  try {
    const res = await fetch(API + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ANK-Client': 'ank-panel' }, body: JSON.stringify({ username, password }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha no login');
    token = data.token;
    localStorage.setItem('ank_token', token);
    enterApp();
    if (data.force_change) toast('Altere sua senha padrão em Configurações.', 'warning');
  } catch (ex) {
    err.textContent = ex.message || 'Usuário ou senha inválidos';
  } finally {
    btn.disabled = false; btn.innerHTML = '<i class="bi bi-arrow-right-short"></i> Entrar';
  }
});

function doLogout() {
  token = '';
  localStorage.removeItem('ank_token');
  stopRefreshTimer(); stopLogsPoll();
  closeContainerTerminal(); closeShellTerminal();
  document.getElementById('screen-app').classList.add('hidden');
  document.getElementById('screen-login').classList.remove('hidden');
}
document.getElementById('btn-logout').addEventListener('click', doLogout);
document.getElementById('btn-logout-mobile').addEventListener('click', doLogout);

function enterApp() {
  document.getElementById('screen-login').classList.add('hidden');
  document.getElementById('screen-app').classList.remove('hidden');
  loadEverything();
  startRefreshTimer();
}
if (token) enterApp();

/* ---------------- nav ---------------- */
document.querySelectorAll('.rail-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.rail-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    item.classList.add('active');
    document.getElementById('view-' + item.dataset.view).classList.add('active');
    stopLogsPoll();
    if (item.dataset.view === 'networks') loadNetworks();
    if (item.dataset.view === 'stacks') loadStacks();
    if (item.dataset.view === 'backups') loadBackups();
    if (item.dataset.view === 'nodes') { loadNodes(); loadPairing(); }
    if (item.dataset.view === 'logs') { logsOffset = 0; loadLogs(); startLogsPoll(); }
    if (item.dataset.view === 'shell') initShellTerminal();
    closeRail();
  });
});
document.getElementById('btn-open-rail').addEventListener('click', () => { document.getElementById('rail').classList.add('open'); document.getElementById('rail-backdrop').classList.add('open'); });
document.getElementById('rail-backdrop').addEventListener('click', closeRail);
function closeRail() { document.getElementById('rail').classList.remove('open'); document.getElementById('rail-backdrop').classList.remove('open'); }

/* ---------------- footer about ---------------- */
document.getElementById('btn-footer-about').addEventListener('click', () => openModal('modal-about'));

/* ---------------- websocket protocol detect ---------------- */
async function detectWsProto() {
  try {
    const res = await fetch(API + '/protocol', { headers: { 'X-ANK-Client': 'ank-panel', Authorization: 'Bearer ' + token } });
    if (res.ok) { const d = await res.json(); wsProto = d.protocol === 'https' ? 'wss:' : 'ws:'; }
  } catch (e) {}
}

/* ================= DASHBOARD ================= */
function gaugeSVG(id, value, max, colorVar, label, sub) {
  const r = 40, c = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  const offset = c * (1 - pct);
  return `
  <div class="gauge-card">
    <svg viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--border)" stroke-width="8"/>
      <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(${colorVar})" stroke-width="8" stroke-linecap="round"
        stroke-dasharray="${c}" stroke-dashoffset="${c}" transform="rotate(-90 50 50)" id="${id}"
        data-offset="${offset}" style="transition:stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)"/>
      <text x="50" y="54" text-anchor="middle" class="gauge-val">${value}</text>
    </svg>
    <div class="gauge-label">${label}</div>
    <div class="gauge-sub">${sub}</div>
  </div>`;
}
function animateGauges() {
  requestAnimationFrame(() => {
    document.querySelectorAll('#gauges circle[data-offset]').forEach(el => {
      el.style.strokeDashoffset = el.dataset.offset;
    });
  });
}

async function loadEverything() {
  try {
    const [status, info] = await Promise.all([api('GET', '/status'), api('GET', '/system/info')]);
    document.getElementById('conn-label').textContent = 'v' + (status.version || '-');
    const mode = info.mode?.mode || 'shared_host';
    document.getElementById('mode-tag').textContent = mode;
    renderModeNotice(mode);

    const running = status.containers_running || 0, stopped = status.containers_stopped || 0, total = status.containers_total || 0;
    document.getElementById('gauges').innerHTML =
      gaugeSVG('g-running', running, Math.max(total, 1), '--success', 'Rodando', `de ${total} total`) +
      gaugeSVG('g-stopped', stopped, Math.max(total, 1), '--text-faint', 'Parados', `de ${total} total`) +
      gaugeSVG('g-cpu', Math.round(info.cpu_usage || 0), 100, '--accent', 'CPU', `${info.cpu_cores || 0} núcleos`) +
      gaugeSVG('g-mem', (memPct(info)), 100, '--accent-2', 'Memória', memSub(info));
    animateGauges();

    const memT = info.memory?.total_kb || 0, memA = info.memory?.available_kb || 0;
    const memUsed = memT - memA;
    const disk = status.disk || {};
    document.getElementById('device-stats').innerHTML = [
      tile('s-blue', info.device || '-', 'Dispositivo'),
      tile('s-blue', info.kernel || '-', 'Kernel'),
      tile('s-violet', memT > 0 ? `${fmtBytes(memUsed * 1024)} / ${fmtBytes(memT * 1024)}` : '-', 'Memória'),
      tile('s-green', disk.total ? `${disk.used} / ${disk.total} GB` : '-', 'Disco'),
      tile('s-amber', fmtUptime(status.uptime), 'Uptime'),
      tile('s-blue', (info.battery != null && info.battery >= 0) ? info.battery + '%' : '-', 'Bateria'),
    ].join('');

    renderDashContainers();
    renderDashClusterAndNodes();
    populateNodeFilters();
    loadContainers();
    loadImages();
    loadTemplates();
  } catch (e) { console.error(e); toast('Falha ao carregar painel: ' + e.message, 'error'); }
}
function tile(cls, v, l) { return `<div class="stat-tile ${cls}"><div class="v mono">${esc(v)}</div><div class="l">${l}</div></div>`; }
function memPct(info) { const t = info.memory?.total_kb || 0, a = info.memory?.available_kb || 0; return t > 0 ? Math.round(((t - a) / t) * 100) : 0; }
function memSub(info) { const t = info.memory?.total_kb || 0; return t > 0 ? fmtBytes(t * 1024) + ' total' : '-'; }

function renderModeNotice(mode) {
  const notice = document.getElementById('mode-notice');
  const title = document.getElementById('mode-notice-title'), body = document.getElementById('mode-notice-body');
  const map = {
    shared_host: ['Modo Shared Host ativo', 'Sem isolamento de namespace. Containers compartilham rede e PID do host.'],
    native_host: ['Modo Shared Host ativo', 'Sem isolamento de namespace. Containers compartilham rede e PID do host.'],
    shared_network: ['Modo Shared Network ativo', 'Namespace de PID + overlay ativos. Rede compartilhada com o host.'],
    isolated: null
  };
  const entry = map[mode];
  if (entry) { notice.classList.remove('hidden'); title.textContent = entry[0]; body.textContent = entry[1]; }
  else notice.classList.add('hidden');
}

async function renderDashContainers() {
  const el = document.getElementById('dash-containers');
  try {
    const list = await api('GET', '/containers/all');
    if (!list.length) { el.innerHTML = emptyState('bi-box-seam', 'Nenhum container criado ainda.'); return; }
    el.innerHTML = list.slice(0, 8).map(c => containerRow(c, true)).join('');
  } catch (e) { el.innerHTML = ''; }
}

let clusterNodesCache = [];
async function renderDashClusterAndNodes() {
  try {
    const d = await api('GET', '/system/dashboard');
    document.getElementById('nav-nodes').style.display = d.is_manager ? '' : 'none';
    clusterNodesCache = d.nodes || [];
    const clusterSec = document.getElementById('cluster-section');
    const miniSec = document.getElementById('nodes-mini-section');
    if (d.is_manager && d.nodes?.length && d.cluster) {
      clusterSec.classList.remove('hidden');
      const cl = d.cluster;
      document.getElementById('cluster-stats').innerHTML = [
        tile('s-blue', `${cl.cpu_percent || 0}%`, `${cl.cpu_cores || 0} núcleos · CPU média`),
        tile('s-violet', cl.ram_total_gb ? `${(cl.ram_used_gb || 0).toFixed(1)} / ${cl.ram_total_gb.toFixed(1)} GB` : '-', `${(cl.ram_percent || 0).toFixed(0)}% memória`),
        tile('s-green', cl.disk_total_gb ? `${(cl.disk_used_gb || 0).toFixed(1)} / ${cl.disk_total_gb.toFixed(1)} GB` : '-', `${(cl.disk_percent || 0).toFixed(0)}% disco`),
        tile('s-amber', `${cl.containers_running || 0}/${cl.containers_total || 0}`, 'Containers no cluster'),
      ].join('');
    } else clusterSec.classList.add('hidden');

    if (d.is_manager && d.nodes?.length) {
      miniSec.classList.remove('hidden');
      document.getElementById('nodes-mini-grid').innerHTML = d.nodes.map(n => {
        const online = n.status === 'online';
        return `<div class="tpl-card" style="border-left-color:${online ? 'var(--success)' : 'var(--danger)'}" onclick="document.querySelector('.rail-item[data-view=nodes]').click()">
          <h4><span class="badge ${statusBadgeClass(n.status)}" style="margin-right:6px">${statusLabel(n.status)}</span>${esc(n.alias || n.ip || n.id)}</h4>
          <p>${online ? `${Math.round(n.cpu_percent || 0)}% CPU · ${(n.containers_running || 0)}/${n.containers || 0} containers` : 'sem conexão'}</p>
        </div>`;
      }).join('');
    } else miniSec.classList.add('hidden');
  } catch (e) {}
}

function populateNodeFilters() {
  const online = clusterNodesCache.filter(n => n.status === 'online');
  const opts = ['<option value="local">Local</option>', '<option value="all">Todos os nós</option>', ...online.map(n => `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`)].join('');
  const filter = document.getElementById('containers-node-filter');
  const prev = filter.value;
  filter.innerHTML = opts;
  if ([...filter.options].some(o => o.value === prev)) filter.value = prev; else filter.value = 'local';
  document.getElementById('logs-node-select').innerHTML = '<option value="local">Local</option>' + online.map(n => `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`).join('');
}

function startRefreshTimer() {
  stopRefreshTimer();
  refreshTimer = setInterval(() => {
    const active = document.querySelector('.view.active')?.id;
    if (active === 'view-dashboard') loadEverything();
    else if (active === 'view-containers') loadContainers();
    else if (active === 'view-nodes') { loadNodes(); loadPairing(); }
  }, Math.max(refreshSeconds, 5) * 1000);
}
function stopRefreshTimer() { if (refreshTimer) clearInterval(refreshTimer); refreshTimer = null; }

/* ================= CONTAINERS ================= */
function emptyState(icon, msg) { return `<div class="empty"><i class="bi ${icon}"></i><p>${msg}</p></div>`; }

function containerRow(c, compact) {
  const name = c.name || '';
  const node = c.node || 'local';
  const isRemote = node !== 'local';
  const status = c.status || 'stopped';
  const busy = ['building', 'starting', 'stopping'].includes(status);
  const running = status === 'running' || status === 'starting';
  const nodeTag = isRemote ? `<span class="tag">${esc(c.node_alias || node.slice(0, 8))}</span>` : '';
  const startFn = isRemote ? `remoteAction('${node}','${esc(name)}','start')` : `containerAction('${esc(name)}','start')`;
  const stopFn = isRemote ? `remoteAction('${node}','${esc(name)}','stop')` : `containerAction('${esc(name)}','stop')`;
  const restartFn = isRemote ? `remoteAction('${node}','${esc(name)}','restart')` : `containerAction('${esc(name)}','restart')`;
  const deleteFn = isRemote ? `remoteDeleteContainer('${node}','${esc(name)}')` : `deleteContainer('${esc(name)}')`;
  return `
  <div class="row" data-name="${esc(name)}" data-node="${node}">
    <div class="row-icon"><i class="bi bi-box-seam"></i></div>
    <div class="row-main" onclick="showContainerDetail('${esc(name)}','${node}')">
      <div class="row-name">${esc(name)} ${nodeTag}</div>
      <div class="row-meta">
        <span><i class="bi bi-hdd-stack"></i> ${esc(c.template_name || c.image || '-')}</span>
        <span><i class="bi bi-globe2"></i> ${esc(c.ip_address || 'N/A')}</span>
        ${c.stats?.memory_bytes ? `<span><i class="bi bi-memory"></i> ${fmtBytes(c.stats.memory_bytes)}</span>` : ''}
      </div>
    </div>
    <div class="row-actions">
      <span class="${statusBadgeClass(status)}">${busy ? '<i class="bi bi-arrow-repeat spin"></i> ' : ''}${statusLabel(status)}</span>
      ${!compact ? `
      ${running ? `<button class="btn btn-warning btn-icon" ${busy ? 'disabled' : ''} onclick="event.stopPropagation();${stopFn}" title="Parar"><i class="bi bi-stop-fill"></i></button>`
                 : `<button class="btn btn-success btn-icon" ${busy ? 'disabled' : ''} onclick="event.stopPropagation();${startFn}" title="Iniciar"><i class="bi bi-play-fill"></i></button>`}
      <button class="btn btn-ghost btn-icon" ${busy ? 'disabled' : ''} onclick="event.stopPropagation();${restartFn}" title="Reiniciar"><i class="bi bi-arrow-repeat"></i></button>
      <button class="btn btn-danger btn-icon" ${(running || busy) ? 'disabled' : ''} onclick="event.stopPropagation();${deleteFn}" title="Excluir"><i class="bi bi-trash3"></i></button>` : ''}
    </div>
  </div>`;
}

async function loadContainers() {
  const el = document.getElementById('containers-list');
  const nodeId = document.getElementById('containers-node-filter').value || 'local';
  try {
    let list;
    if (nodeId === 'all') list = await api('GET', '/containers/all');
    else if (nodeId === 'local') list = await api('GET', '/containers');
    else list = await api('GET', `/nodes/${encodeURIComponent(nodeId)}/containers`);
    if (!list || !list.length) { el.innerHTML = emptyState('bi-box-seam', 'Nenhum container encontrado. Clique em "Novo container".'); return; }
    el.innerHTML = list.map(c => containerRow(c, false)).join('');
  } catch (e) { el.innerHTML = emptyState('bi-exclamation-triangle', 'Falha ao carregar: ' + e.message); }
}
document.getElementById('containers-node-filter').addEventListener('change', loadContainers);

async function containerAction(name, action) {
  try { await api('POST', `/containers/${encodeURIComponent(name)}/${action}`); toast(`${action} enviado para "${name}"`, 'info'); setTimeout(loadContainers, 600); }
  catch (e) { toast(`Falha: ${e.message}`, 'error'); }
}
async function remoteAction(nodeId, name, action) {
  try { await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}/${action}`); toast(`${action} enviado para "${name}"`, 'info'); setTimeout(loadContainers, 800); }
  catch (e) { toast(`Falha: ${e.message}`, 'error'); }
}
async function deleteContainer(name) {
  const ok = await confirmDialog('Excluir container', `Excluir "${name}"? Essa ação não pode ser desfeita.`);
  if (!ok) return;
  try { await api('DELETE', `/containers/${encodeURIComponent(name)}`); toast(`"${name}" excluído`, 'success'); loadContainers(); }
  catch (e) { toast(`Falha: ${e.message}`, 'error'); }
}
async function remoteDeleteContainer(nodeId, name) {
  const ok = await confirmDialog('Excluir container remoto', `Excluir "${name}" no node remoto?`);
  if (!ok) return;
  try { await api('DELETE', `/nodes/${encodeURIComponent(nodeId)}/containers/${encodeURIComponent(name)}`); toast(`"${name}" excluído`, 'success'); loadContainers(); }
  catch (e) { toast(`Falha: ${e.message}`, 'error'); }
}

/* ---- create container modal ---- */
document.getElementById('btn-new-container').addEventListener('click', async () => {
  const sel = document.getElementById('cc-node');
  const filterVal = document.getElementById('containers-node-filter').value;
  sel.innerHTML = document.getElementById('containers-node-filter').innerHTML.replace('<option value="all">Todos os nós</option>', '');
  sel.value = (filterVal && filterVal !== 'all') ? filterVal : 'local';
  populateImageSelect(document.getElementById('cc-image'));
  openModal('modal-create-container');
});

async function populateImageSelect(sel) {
  let images = [];
  try { images = await api('GET', '/images'); } catch (e) {}
  const base = images.map(i => `<option value="${esc(i.name)}">${esc(i.name)}${i.size ? ' · ' + fmtBytes(i.size) : ''}</option>`).join('');
  const templates = ['alpine', 'python', 'nginx', 'apache', 'php', 'node'];
  const labels = { alpine: 'Alpine base', python: 'Python 3.12', nginx: 'Nginx estático', apache: 'Apache estático', php: 'PHP 8.2', node: 'Node.js 20' };
  const tpl = templates.map(t => `<option value="template:${t}">${labels[t]}</option>`).join('');
  sel.innerHTML = `<optgroup label="Imagens locais">${base || '<option disabled>nenhuma</option>'}</optgroup><optgroup label="Templates">${tpl}</optgroup>`;
}

document.getElementById('form-create-container').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('btn-create-container-submit');
  btn.disabled = true; btn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Criando…';
  const name = document.getElementById('cc-name').value.trim();
  const imageVal = document.getElementById('cc-image').value;
  const nodeId = document.getElementById('cc-node').value || 'local';
  const isRemote = nodeId !== 'local';
  try {
    if (imageVal.startsWith('template:')) {
      const templateId = imageVal.replace('template:', '');
      const rootPass = document.getElementById('cc-root-pass').value || 'ank123';
      if (isRemote) await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name, image: templateId, root_password: rootPass });
      else await api('POST', '/images/deploy', { template: templateId, name, root_password: rootPass });
    } else {
      const data = {
        name, image: imageVal,
        root_password: document.getElementById('cc-root-pass').value,
        autostart: document.getElementById('cc-autostart').checked,
        policies: {
          inter_container_p2p: document.getElementById('cc-p2p').checked,
          allow_host_access: document.getElementById('cc-host').checked,
          allow_internet: document.getElementById('cc-internet').checked
        },
        resources: { memory_limit: document.getElementById('cc-mem-limit').value, cpu_limit_percent: parseInt(document.getElementById('cc-cpu-limit').value) || undefined }
      };
      const sshPort = document.getElementById('cc-ssh-port').value;
      if (sshPort) data.ssh_port = parseInt(sshPort);
      if (isRemote) await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, data);
      else await api('POST', '/containers', data);
    }
    closeModal('modal-create-container');
    document.getElementById('form-create-container').reset();
    toast(`Container "${name}" ${isRemote ? 'enviado para o node remoto' : 'criado'}`, 'success');
    loadContainers();
  } catch (ex) { toast(`Falha: ${ex.message}`, 'error'); }
  btn.disabled = false; btn.innerHTML = '<i class="bi bi-check-lg"></i> Criar';
});

/* ---- container detail ---- */
async function showContainerDetail(name, nodeId) {
  currentContainer = { name, nodeId: nodeId || 'local' };
  document.getElementById('cd-name').textContent = name;
  document.getElementById('cd-status').textContent = '…';
  document.getElementById('cd-info-grid').innerHTML = '<div class="skel skel-row"></div>';
  document.getElementById('cd-logs-view').textContent = 'Carregando…';
  document.querySelectorAll('#modal-container-detail .modal-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
  document.querySelectorAll('#modal-container-detail .modal-pane').forEach((p, i) => p.classList.toggle('active', i === 0));
  openModal('modal-container-detail');
  try {
    const isRemote = currentContainer.nodeId !== 'local';
    const c = isRemote ? await api('GET', `/nodes/${encodeURIComponent(currentContainer.nodeId)}/containers/${encodeURIComponent(name)}`) : await api('GET', `/containers/${encodeURIComponent(name)}`);
    document.getElementById('cd-status').className = statusBadgeClass(c.status);
    document.getElementById('cd-status').textContent = statusLabel(c.status);
    document.getElementById('cd-info-grid').innerHTML = [
      tile('s-blue', c.image || c.template_name || '-', 'Imagem'),
      tile('s-blue', c.ip_address || '-', 'IP'),
      tile('s-violet', c.stats?.memory_bytes ? fmtBytes(c.stats.memory_bytes) : '-', 'Memória'),
      tile('s-green', c.stats?.cpu_percent != null ? c.stats.cpu_percent + '%' : '-', 'CPU'),
      tile('s-amber', c.ssh_port || '-', 'Porta SSH'),
      tile('s-blue', c.node_alias || currentContainer.nodeId, 'Node'),
    ].join('');
    if (!isRemote) {
      const logs = await api('GET', `/containers/${encodeURIComponent(name)}/logs`);
      document.getElementById('cd-logs-view').textContent = (logs.logs || logs.output || '(sem logs)') + '';
    } else {
      document.getElementById('cd-logs-view').textContent = 'Logs remotos não disponíveis nesta visão.';
    }
    renderContainerDetailActions(c);
  } catch (e) { toast('Falha ao carregar container: ' + e.message, 'error'); }
}

function renderContainerDetailActions(c) {
  const el = document.getElementById('cd-actions');
  const { name, nodeId } = currentContainer;
  const isRemote = nodeId !== 'local';
  const running = c.status === 'running' || c.status === 'starting';
  const startFn = isRemote ? `remoteAction('${nodeId}','${esc(name)}','start')` : `containerAction('${esc(name)}','start')`;
  const stopFn = isRemote ? `remoteAction('${nodeId}','${esc(name)}','stop')` : `containerAction('${esc(name)}','stop')`;
  const restartFn = isRemote ? `remoteAction('${nodeId}','${esc(name)}','restart')` : `containerAction('${esc(name)}','restart')`;
  el.innerHTML = `
    ${running ? `<button class="btn btn-warning" onclick="${stopFn}"><i class="bi bi-stop-fill"></i> Parar</button>` : `<button class="btn btn-success" onclick="${startFn}"><i class="bi bi-play-fill"></i> Iniciar</button>`}
    <button class="btn btn-ghost" onclick="${restartFn}"><i class="bi bi-arrow-repeat"></i> Reiniciar</button>`;
}

document.querySelectorAll('#modal-container-detail .modal-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#modal-container-detail .modal-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('#modal-container-detail .modal-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.pane).classList.add('active');
    if (tab.dataset.pane === 'cd-terminal') openContainerTerminal();
    else closeContainerTerminal();
  });
});

async function openContainerTerminal() {
  if (!currentContainer || currentContainer.nodeId !== 'local') { document.getElementById('cd-term-body').innerHTML = '<div style="padding:16px;color:var(--text-faint);font-size:12px">Terminal disponível apenas para containers locais.</div>'; return; }
  const el = document.getElementById('cd-term-body');
  el.innerHTML = '';
  closeContainerTerminal();
  await detectWsProto();
  cdTerm = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: "'JetBrains Mono',monospace", theme: { background: '#05070c', foreground: '#d6deeb', cursor: '#3d8bfd' }, scrollback: 4000 });
  cdTerm.open(el);
  cdTerm.focus();
  const cols = cdTerm.cols || 80, rows = cdTerm.rows || 24;
  const url = `${wsProto}//${location.host}/api/exec?container=${encodeURIComponent(currentContainer.name)}&token=${encodeURIComponent(token)}&cols=${cols}&rows=${rows}`;
  cdWs = new WebSocket(url);
  const dot = document.getElementById('cd-term-dot'), status = document.getElementById('cd-term-status');
  cdWs.onopen = () => { dot.classList.add('live'); status.textContent = 'conectado'; };
  cdWs.onmessage = (ev) => cdTerm.write(ev.data);
  cdWs.onclose = () => { dot.classList.remove('live'); status.textContent = 'desconectado'; };
  cdWs.onerror = () => { status.textContent = 'erro de conexão'; };
  cdTerm.onData(d => { if (cdWs && cdWs.readyState === WebSocket.OPEN) cdWs.send(d); });
}
function closeContainerTerminal() {
  if (cdWs) { try { cdWs.close(); } catch (e) {} cdWs = null; }
  if (cdTerm) { try { cdTerm.dispose(); } catch (e) {} cdTerm = null; }
}

/* upload */
const cdUploadArea = document.getElementById('cd-upload-area');
cdUploadArea.addEventListener('click', () => document.getElementById('cd-upload-input').click());
cdUploadArea.addEventListener('dragover', e => { e.preventDefault(); cdUploadArea.style.borderColor = 'var(--accent)'; });
cdUploadArea.addEventListener('dragleave', () => cdUploadArea.style.borderColor = 'var(--border)');
cdUploadArea.addEventListener('drop', e => { e.preventDefault(); cdUploadArea.style.borderColor = 'var(--border)'; uploadToContainer(e.dataTransfer.files); });
document.getElementById('cd-upload-input').addEventListener('change', e => uploadToContainer(e.target.files));
async function uploadToContainer(files) {
  if (!currentContainer || !files.length) return;
  const result = document.getElementById('cd-upload-result');
  result.textContent = 'Enviando…';
  const form = new FormData();
  for (const f of files) form.append('file', f);
  try {
    const headers = { 'X-ANK-Client': 'ank-panel' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(`${API}/containers/${encodeURIComponent(currentContainer.name)}/upload`, { method: 'PUT', headers, body: form });
    const data = await res.json();
    if (res.ok) { result.textContent = `${data.files?.length || 0} arquivo(s) enviados.`; toast('Upload concluído', 'success'); }
    else { result.textContent = data.error || 'Falha no upload'; }
  } catch (e) { result.textContent = e.message; }
}

/* ================= IMAGES ================= */
async function loadImages() {
  const el = document.getElementById('images-list');
  try {
    const images = await api('GET', '/images');
    if (!images.length) { el.innerHTML = emptyState('bi-stack', 'Nenhuma imagem local. Baixe o Alpine base.'); return; }
    el.innerHTML = images.map(i => `
      <div class="row">
        <div class="row-icon"><i class="bi bi-hdd-stack"></i></div>
        <div class="row-main" style="cursor:default">
          <div class="row-name">${esc(i.name)}</div>
          <div class="row-meta"><span>${i.size ? fmtBytes(i.size) : '-'}</span></div>
        </div>
        <div class="row-actions"><button class="btn btn-danger btn-icon" onclick="deleteImage('${esc(i.name)}')" title="Excluir"><i class="bi bi-trash3"></i></button></div>
      </div>`).join('');
  } catch (e) { el.innerHTML = emptyState('bi-exclamation-triangle', e.message); }
}
async function deleteImage(name) {
  const ok = await confirmDialog('Excluir imagem', `Excluir a imagem "${name}"?`);
  if (!ok) return;
  try { await api('DELETE', `/images/${encodeURIComponent(name)}`); toast('Imagem excluída', 'success'); loadImages(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
}

const TEMPLATE_META = {
  alpine: { name: 'Alpine base', color: 'var(--accent)', icon: 'bi-box' },
  python: { name: 'Python 3.12', color: '#4b8bbe', icon: 'bi-filetype-py' },
  nginx: { name: 'Nginx estático', color: '#2ecc71', icon: 'bi-hdd-network' },
  apache: { name: 'Apache estático', color: '#d64d4d', icon: 'bi-server' },
  php: { name: 'PHP 8.2', color: '#8993be', icon: 'bi-filetype-php' },
  node: { name: 'Node.js 20', color: '#68a063', icon: 'bi-filetype-js' },
};
async function loadTemplates() {
  const grid = document.getElementById('templates-grid');
  try {
    const templates = await api('GET', '/images/templates');
    if (!templates.length) { grid.innerHTML = emptyState('bi-stack', 'Nenhum template disponível.'); return; }
    grid.innerHTML = templates.map(t => {
      const meta = TEMPLATE_META[t.id] || { name: t.name, color: 'var(--accent)', icon: 'bi-box' };
      return `<div class="tpl-card ${t.base_ready ? '' : 'disabled'}" style="border-left-color:${meta.color}" onclick="${t.base_ready ? `deployTemplate('${t.id}','${esc(t.name)}')` : `toast('Baixe a imagem Alpine base primeiro','warning')`}">
        <h4><i class="bi ${meta.icon}" style="color:${meta.color};margin-right:6px"></i>${esc(t.name)}</h4>
        <p>${t.base_ready ? 'pronto para implantar' : 'requer imagem base'}</p>
      </div>`;
    }).join('');
  } catch (e) { grid.innerHTML = emptyState('bi-exclamation-triangle', e.message); }
}

document.getElementById('btn-pull-image').addEventListener('click', async () => {
  const version = prompt('Versão do Alpine para baixar:', '3.20');
  if (!version) return;
  try { toast(`Baixando alpine-${version}…`, 'info'); await api('POST', '/images/pull', { version }); toast('Imagem baixada', 'success'); loadImages(); loadTemplates(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
});

let deployTemplateCtx = null;
async function deployTemplate(id, name) {
  deployTemplateCtx = { id, name };
  document.getElementById('dt-template-name').textContent = name;
  document.getElementById('dt-name').value = name.toLowerCase().replace(/\s+/g, '-');
  let defaultPass = 'ank123';
  try { const cfg = await api('GET', '/config'); if (cfg.default_container_password) defaultPass = cfg.default_container_password; } catch (e) {}
  document.getElementById('dt-pass').value = defaultPass;
  const nodeSel = document.getElementById('dt-node');
  const online = clusterNodesCache.filter(n => n.status === 'online');
  nodeSel.innerHTML = '<option value="local">Local</option>' + online.map(n => `<option value="${esc(n.id)}">${esc(n.alias || n.ip)}</option>`).join('');
  openModal('modal-deploy-template');
}
document.getElementById('btn-deploy-template-submit').addEventListener('click', async () => {
  if (!deployTemplateCtx) return;
  const containerName = document.getElementById('dt-name').value.trim();
  const rootPass = document.getElementById('dt-pass').value;
  const nodeId = document.getElementById('dt-node').value || 'local';
  if (!containerName) { toast('Nome do container é obrigatório', 'warning'); return; }
  if (!rootPass || rootPass.length < 4) { toast('Senha deve ter ao menos 4 caracteres', 'warning'); return; }
  try {
    if (nodeId !== 'local') await api('POST', `/nodes/${encodeURIComponent(nodeId)}/containers`, { name: containerName, image: deployTemplateCtx.id, root_password: rootPass });
    else await api('POST', '/images/deploy', { template: deployTemplateCtx.id, name: containerName, root_password: rootPass });
    closeModal('modal-deploy-template');
    toast(`"${containerName}" implantado`, 'success');
    setTimeout(loadContainers, 800);
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});

/* ================= NETWORKS ================= */
async function loadNetworks() {
  try {
    const [networks, info] = await Promise.all([api('GET', '/networks'), api('GET', '/networks/info')]);
    document.getElementById('network-info').innerHTML = [
      tile('s-blue', info.subnet || '-', 'Subnet'),
      tile('s-blue', info.gateway || '-', 'Gateway'),
      tile('s-violet', info.bridge || '-', 'Bridge'),
    ].join('');
    const el = document.getElementById('networks-list');
    if (!networks.length) { el.innerHTML = emptyState('bi-diagram-3', 'Nenhuma rede adicional configurada.'); return; }
    el.innerHTML = networks.map(n => `
      <div class="row"><div class="row-icon"><i class="bi bi-diagram-3"></i></div>
        <div class="row-main" style="cursor:default"><div class="row-name">${esc(n.name || n.subnet)}</div>
        <div class="row-meta"><span>${esc(n.subnet || '-')}</span><span>${esc(n.gateway || '-')}</span></div></div>
      </div>`).join('');
  } catch (e) { toast('Falha ao carregar redes: ' + e.message, 'error'); }
}
document.getElementById('btn-new-network').addEventListener('click', () => openModal('modal-create-network'));
document.getElementById('btn-create-network-submit').addEventListener('click', async () => {
  const subnet = document.getElementById('nw-subnet').value.trim();
  const gateway = document.getElementById('nw-gateway').value.trim();
  const bridge = document.getElementById('nw-bridge').value.trim();
  const nat = document.getElementById('nw-nat').checked;
  if (!subnet) { toast('Subnet é obrigatória', 'warning'); return; }
  try { await api('POST', '/networks', { subnet, gateway, bridge, nat }); closeModal('modal-create-network'); toast('Rede criada', 'success'); loadNetworks(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
});

/* ================= STACKS ================= */
async function loadStacks() {
  const el = document.getElementById('stacks-list');
  try {
    const data = await api('GET', '/stacks/all').catch(() => api('GET', '/stacks'));
    const stacks = Array.isArray(data) ? data : (data.stacks || []);
    if (!stacks.length) { el.innerHTML = emptyState('bi-layers', 'Nenhuma stack criada ainda.'); return; }
    el.innerHTML = stacks.map(s => {
      const running = s.running || s.instances_running || 0;
      const total = s.instances || s.total_instances || 0;
      return `<div class="row">
        <div class="row-icon"><i class="bi bi-layers"></i></div>
        <div class="row-main" style="cursor:default">
          <div class="row-name">${esc(s.name)} <span class="tag">${esc(s.template || s.image || '-')}</span></div>
          <div class="row-meta"><span>${running}/${total} rodando</span><span>LB porta ${s.lb_port || '-'}</span></div>
        </div>
        <div class="row-actions">
          <button class="btn btn-ghost btn-icon" onclick="scaleStack('${esc(s.name || s.id)}',1)" title="Escalar +1"><i class="bi bi-plus-lg"></i></button>
          <button class="btn btn-ghost btn-icon" onclick="scaleStack('${esc(s.name || s.id)}',-1)" title="Escalar -1"><i class="bi bi-dash-lg"></i></button>
          <button class="btn btn-danger btn-icon" onclick="deleteStack('${esc(s.name || s.id)}')" title="Excluir"><i class="bi bi-trash3"></i></button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { el.innerHTML = emptyState('bi-exclamation-triangle', e.message); }
}
document.getElementById('btn-new-stack').addEventListener('click', async () => {
  const sel = document.getElementById('st-image');
  let images = [];
  try { images = await api('GET', '/images'); } catch (e) {}
  sel.innerHTML = images.map(i => `<option value="${esc(i.name)}">${esc(i.name)}</option>`).join('') || '<option value="alpine">alpine</option>';
  openModal('modal-create-stack');
});
document.getElementById('btn-create-stack-submit').addEventListener('click', async () => {
  const name = document.getElementById('st-name').value.trim();
  const image = document.getElementById('st-image').value;
  const instances = parseInt(document.getElementById('st-instances').value || '1');
  const lbPort = parseInt(document.getElementById('st-lb-port').value || '30000');
  const volume = document.getElementById('st-volume').checked;
  const trigger = document.getElementById('st-trigger').value;
  if (!name) { toast('Nome da stack é obrigatório', 'warning'); return; }
  try {
    await api('POST', '/stacks', { name, template: image, instances, lb_port: lbPort, shared_volume: volume, trigger: trigger === 'none' ? null : trigger });
    closeModal('modal-create-stack');
    toast(`Stack "${name}" criada`, 'success');
    loadStacks();
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});
async function scaleStack(name, delta) {
  try {
    if (delta > 0) await api('POST', `/stacks/${encodeURIComponent(name)}/scale`, { count: 1 });
    else await api('POST', `/stacks/${encodeURIComponent(name)}/scale-down`, { count: 1 });
    toast(`Stack "${name}" escalada`, 'success'); loadStacks();
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
}
async function deleteStack(name) {
  const ok = await confirmDialog('Excluir stack', `Excluir "${name}"? Todos os containers da stack serão removidos.`);
  if (!ok) return;
  try { await api('POST', `/stacks/${encodeURIComponent(name)}/delete`); toast('Stack excluída', 'success'); loadStacks(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
}

/* ================= BACKUPS ================= */
async function loadBackups() {
  const el = document.getElementById('backups-list');
  try {
    const data = await api('GET', '/backups');
    const routines = data.routines || data || [];
    if (!routines.length) { el.innerHTML = emptyState('bi-cloud-arrow-up', 'Nenhuma rotina de backup configurada.'); return; }
    el.innerHTML = routines.map(r => `
      <div class="row">
        <div class="row-icon"><i class="bi bi-cloud-arrow-up"></i></div>
        <div class="row-main" style="cursor:default">
          <div class="row-name">${esc(r.name)}</div>
          <div class="row-meta"><span>${esc(r.schedule || 'manual')}</span><span>retenção ${r.retention || '-'}d</span><span>${esc(r.remote_host || '-')}</span></div>
        </div>
        <div class="row-actions">
          <button class="btn btn-ghost btn-icon" onclick="runBackup('${esc(r.id)}')" title="Executar agora"><i class="bi bi-play-fill"></i></button>
          <button class="btn btn-danger btn-icon" onclick="deleteBackup('${esc(r.id)}')" title="Excluir"><i class="bi bi-trash3"></i></button>
        </div>
      </div>`).join('');
  } catch (e) { el.innerHTML = emptyState('bi-exclamation-triangle', e.message); }
}
document.getElementById('btn-new-backup').addEventListener('click', () => openModal('modal-create-backup'));
document.getElementById('btn-create-backup-submit').addEventListener('click', async () => {
  const name = document.getElementById('bk-name').value.trim();
  if (!name) { toast('Nome da rotina é obrigatório', 'warning'); return; }
  try {
    await api('POST', '/backups', {
      name,
      source: document.getElementById('bk-source').value.trim(),
      remote_host: document.getElementById('bk-remote-host').value.trim(),
      remote_path: document.getElementById('bk-remote-path').value.trim(),
      ssh_user: document.getElementById('bk-ssh-user').value.trim() || 'root',
      ssh_pass: document.getElementById('bk-ssh-pass').value,
      schedule: document.getElementById('bk-schedule').value.trim(),
      retention: parseInt(document.getElementById('bk-retention').value || '30')
    });
    closeModal('modal-create-backup');
    toast('Rotina de backup criada', 'success');
    loadBackups();
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});
async function runBackup(id) {
  try { toast('Executando backup…', 'info'); const r = await api('POST', `/backups/${encodeURIComponent(id)}/execute`); toast(r.message || 'Backup concluído', 'success'); loadBackups(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
}
async function deleteBackup(id) {
  const ok = await confirmDialog('Excluir rotina', 'Excluir esta rotina de backup?');
  if (!ok) return;
  try { await api('POST', `/backups/${encodeURIComponent(id)}/delete`); toast('Rotina excluída', 'success'); loadBackups(); }
  catch (e) { toast('Falha: ' + e.message, 'error'); }
}

/* ================= NODES ================= */
async function loadNodes() {
  const el = document.getElementById('nodes-list');
  try {
    const nodes = await api('GET', '/nodes');
    if (!nodes.length) { el.innerHTML = emptyState('bi-hdd-network', 'Nenhum node pareado ainda.'); return; }
    el.innerHTML = nodes.map(n => `
      <div class="row" onclick="showNodeDetail('${esc(n.id)}')">
        <div class="row-icon"><i class="bi bi-hdd-network"></i></div>
        <div class="row-main">
          <div class="row-name">${esc(n.alias || n.ip)}</div>
          <div class="row-meta"><span><i class="bi bi-globe2"></i> ${esc(n.ip || '-')}</span>${n.status === 'online' ? `<span><i class="bi bi-cpu"></i> ${Math.round(n.cpu_percent || 0)}%</span>` : ''}</div>
        </div>
        <div class="row-actions"><span class="${statusBadgeClass(n.status)}">${statusLabel(n.status)}</span></div>
      </div>`).join('');
    populateNodeFilters();
  } catch (e) { el.innerHTML = emptyState('bi-exclamation-triangle', e.message); }
}
async function loadPairing() {
  try {
    const reqs = await api('GET', '/nodes/pairing');
    const sec = document.getElementById('pairing-section');
    const el = document.getElementById('pairing-list');
    if (!reqs.length) { sec.classList.add('hidden'); return; }
    sec.classList.remove('hidden');
    el.innerHTML = reqs.map(r => `
      <div class="row">
        <div class="row-icon"><i class="bi bi-link-45deg"></i></div>
        <div class="row-main" style="cursor:default"><div class="row-name">${esc(r.alias || r.ip)}</div><div class="row-meta"><span>${esc(r.ip)}</span></div></div>
        <div class="row-actions">
          <button class="btn btn-success btn-icon" onclick="approvePairing('${esc(r.id)}')" title="Aprovar"><i class="bi bi-check-lg"></i></button>
          <button class="btn btn-danger btn-icon" onclick="rejectPairing('${esc(r.id)}')" title="Rejeitar"><i class="bi bi-x-lg"></i></button>
        </div>
      </div>`).join('');
  } catch (e) {}
}
async function approvePairing(id) { try { await api('POST', `/nodes/pairing/${encodeURIComponent(id)}/approve`); toast('Node aprovado', 'success'); loadPairing(); loadNodes(); } catch (e) { toast('Falha: ' + e.message, 'error'); } }
async function rejectPairing(id) { try { await api('POST', `/nodes/pairing/${encodeURIComponent(id)}/reject`); toast('Solicitação rejeitada', 'info'); loadPairing(); } catch (e) { toast('Falha: ' + e.message, 'error'); } }

document.getElementById('btn-new-node').addEventListener('click', () => openModal('modal-add-node'));
document.getElementById('btn-add-node-submit').addEventListener('click', async () => {
  const ip = document.getElementById('nd-ip').value.trim();
  if (!ip) { toast('IP do painel é obrigatório', 'warning'); return; }
  try {
    toast(`Enviando pareamento para "${ip}"…`, 'info');
    await api('POST', '/nodes/pairing/send', {
      ip, port: parseInt(document.getElementById('nd-port').value || '8001'),
      user: document.getElementById('nd-user').value.trim() || 'admin',
      password: document.getElementById('nd-pass').value,
      alias: document.getElementById('nd-alias').value.trim()
    });
    closeModal('modal-add-node');
    toast('Solicitação de pareamento enviada', 'success');
    loadNodes();
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});

async function showNodeDetail(id) {
  document.getElementById('nde-name').textContent = '…';
  document.getElementById('nde-status').textContent = '';
  document.getElementById('nde-body').innerHTML = '<div class="skel skel-row"></div><div class="skel skel-row"></div>';
  document.getElementById('nde-actions').innerHTML = '';
  openModal('modal-node-detail');
  try {
    const [status, info, containers] = await Promise.all([
      api('GET', `/nodes/${encodeURIComponent(id)}/status`).catch(() => ({})),
      api('GET', `/nodes/${encodeURIComponent(id)}/system/info`).catch(() => ({})),
      api('GET', `/nodes/${encodeURIComponent(id)}/containers`).catch(() => [])
    ]);
    const node = clusterNodesCache.find(n => n.id === id) || {};
    document.getElementById('nde-name').textContent = node.alias || node.ip || id;
    document.getElementById('nde-status').className = statusBadgeClass(status.status || node.status);
    document.getElementById('nde-status').textContent = statusLabel(status.status || node.status);
    const memT = info.memory?.total_kb || 0, memA = info.memory?.available_kb || 0;
    let body = `<div class="node-detail-grid">
      ${tile('', info.device || '-', 'Dispositivo')}
      ${tile('', info.cpu_usage != null ? info.cpu_usage + '%' : '-', 'CPU')}
      ${tile('', memT ? fmtBytes((memT - memA) * 1024) + ' / ' + fmtBytes(memT * 1024) : '-', 'Memória')}
      ${tile('', containers.length, 'Containers')}
    </div>`;
    body += `<div class="section-title">Containers no node</div><div class="row-list">`;
    body += containers.length ? containers.map(c => containerRow({ ...c, node: id, node_alias: node.alias }, false)).join('') : emptyState('bi-box-seam', 'Nenhum container neste node.');
    body += `</div>`;
    document.getElementById('nde-body').innerHTML = body;
    document.getElementById('nde-actions').innerHTML = `
      <button class="btn btn-ghost" onclick="refreshNode('${esc(id)}')"><i class="bi bi-arrow-clockwise"></i> Atualizar</button>
      <button class="btn btn-warning" onclick="restartNode('${esc(id)}')"><i class="bi bi-arrow-repeat"></i> Reiniciar dispositivo</button>
      <button class="btn btn-danger" onclick="removeNode('${esc(id)}')"><i class="bi bi-trash3"></i> Remover node</button>`;
  } catch (e) { toast('Falha ao carregar node: ' + e.message, 'error'); }
}
async function refreshNode(id) { try { toast('Atualizando node…', 'info'); await api('POST', `/nodes/${encodeURIComponent(id)}/refresh`); toast('Node atualizado', 'success'); loadNodes(); showNodeDetail(id); } catch (e) { toast('Falha: ' + e.message, 'error'); } }
async function restartNode(id) {
  const ok = await confirmDialog('Reiniciar dispositivo', 'Isso reiniciará o dispositivo remoto. Continuar?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(id)}/restart`); toast('Reinício enviado', 'warning'); } catch (e) { toast('Falha: ' + e.message, 'error'); }
}
async function removeNode(id) {
  const ok = await confirmDialog('Remover node', 'Remover este node do cluster?');
  if (!ok) return;
  try { await api('POST', `/nodes/${encodeURIComponent(id)}/delete`); toast('Node removido', 'success'); closeModal('modal-node-detail'); loadNodes(); } catch (e) { toast('Falha: ' + e.message, 'error'); }
}

/* ================= LOGS ================= */
async function loadLogs() {
  const view = document.getElementById('logs-view');
  const nodeId = document.getElementById('logs-node-select').value || 'local';
  try {
    const data = nodeId === 'local' ? await api('GET', '/logs') : await api('GET', `/nodes/${encodeURIComponent(nodeId)}/logs`);
    const text = data.logs || data.output || (Array.isArray(data) ? data.join('\n') : '(sem logs)');
    view.textContent = text;
    view.scrollTop = view.scrollHeight;
  } catch (e) { view.textContent = 'Falha ao carregar logs: ' + e.message; }
}
document.getElementById('btn-refresh-logs').addEventListener('click', loadLogs);
document.getElementById('logs-node-select').addEventListener('change', loadLogs);
function startLogsPoll() { stopLogsPoll(); logsPollTimer = setInterval(loadLogs, 5000); }
function stopLogsPoll() { if (logsPollTimer) clearInterval(logsPollTimer); logsPollTimer = null; }

/* ================= SHELL ================= */
async function populateShellPicker() {
  const sel = document.getElementById('term-shell-picker');
  let containers = [];
  try { containers = await api('GET', '/containers'); } catch (e) {}
  const running = containers.filter(c => c.status === 'running');
  sel.innerHTML = running.length ? running.map(c => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('') : '<option value="">nenhum container rodando</option>';
}
async function initShellTerminal() {
  await populateShellPicker();
  const target = document.getElementById('term-shell-picker').value;
  if (target) connectShell(target);
}
document.getElementById('term-shell-picker').addEventListener('change', (e) => { if (e.target.value) connectShell(e.target.value); });

async function connectShell(containerName) {
  closeShellTerminal();
  const el = document.getElementById('shell-term-body');
  el.innerHTML = '';
  await detectWsProto();
  shellTerm = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: "'JetBrains Mono',monospace", theme: { background: '#05070c', foreground: '#d6deeb', cursor: '#3d8bfd' }, scrollback: 5000 });
  shellTerm.open(el);
  shellTerm.writeln(`\x1b[1;34m  ANK Shell — ${containerName}\x1b[0m`);
  shellTerm.writeln('\x1b[90m  Conectando…\x1b[0m\r\n');
  shellTerm.focus();
  const cols = shellTerm.cols || 80, rows = shellTerm.rows || 24;
  const url = `${wsProto}//${location.host}/api/exec?container=${encodeURIComponent(containerName)}&token=${encodeURIComponent(token)}&cols=${cols}&rows=${rows}`;
  shellWs = new WebSocket(url);
  const dot = document.getElementById('shell-term-dot'), status = document.getElementById('shell-term-status');
  shellWs.onopen = () => { dot.classList.add('live'); status.textContent = 'conectado a ' + containerName; shellTerm.writeln('\x1b[90m  Conectado.\x1b[0m\r\n'); };
  shellWs.onmessage = (ev) => shellTerm.write(ev.data);
  shellWs.onclose = () => { dot.classList.remove('live'); status.textContent = 'desconectado'; shellTerm.writeln('\r\n\x1b[31m[conexão encerrada]\x1b[0m'); };
  shellWs.onerror = () => { status.textContent = 'erro de conexão'; };
  shellTerm.onData(d => { if (shellWs && shellWs.readyState === WebSocket.OPEN) shellWs.send(d); });
  window.addEventListener('resize', () => {
    if (!shellTerm) return;
    const rect = el.getBoundingClientRect();
    const c = Math.floor(rect.width / 8.4), r = Math.floor(rect.height / 18);
    if (c > 0 && r > 0) shellTerm.resize(c, r);
  });
}
function closeShellTerminal() {
  if (shellWs) { try { shellWs.close(); } catch (e) {} shellWs = null; }
  if (shellTerm) { try { shellTerm.dispose(); } catch (e) {} shellTerm = null; }
}

/* ================= SETTINGS ================= */
async function loadSettings() {
  try {
    const cfg = await api('GET', '/config');
    document.getElementById('set-node-name').value = cfg.node_name || '';
    document.getElementById('set-bind').value = cfg.bind_address || '';
    document.getElementById('set-refresh').value = cfg.refresh_interval || refreshSeconds;
    document.getElementById('set-default-pass').value = cfg.default_container_password || '';
    document.getElementById('set-autostart').checked = !!cfg.autostart_on_boot;
    document.getElementById('set-remote-mgmt').checked = !!cfg.enable_remote_management;
    document.getElementById('set-manager-ip').value = cfg.manager_ip || '';
    document.getElementById('set-ssh-enabled').checked = cfg.ssh_enabled !== false;
    document.getElementById('set-ssh-port').value = cfg.ssh_port || 2200;
  } catch (e) {}
}
document.querySelector('.rail-item[data-view="settings"]').addEventListener('click', loadSettings);

document.getElementById('form-settings-server').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('POST', '/config', {
      bind_address: document.getElementById('set-bind').value,
      refresh_interval: parseInt(document.getElementById('set-refresh').value),
      autostart_on_boot: document.getElementById('set-autostart').checked,
      node_name: document.getElementById('set-node-name').value.trim(),
      default_container_password: document.getElementById('set-default-pass').value.trim()
    });
    refreshSeconds = parseInt(document.getElementById('set-refresh').value);
    localStorage.setItem('ank_refresh', refreshSeconds);
    startRefreshTimer();
    toast('Configurações salvas', 'success');
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});

document.getElementById('btn-save-remote').addEventListener('click', async () => {
  try {
    await api('POST', '/config', {
      enable_remote_management: document.getElementById('set-remote-mgmt').checked,
      manager_ip: document.getElementById('set-manager-ip').value.trim(),
      ssh_enabled: document.getElementById('set-ssh-enabled').checked,
      ssh_port: parseInt(document.getElementById('set-ssh-port').value || '2200')
    });
    toast('Configurações remotas salvas', 'success');
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});

document.getElementById('form-change-password').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('POST', '/auth/password', { current_password: document.getElementById('set-current-pass').value, new_password: document.getElementById('set-new-pass').value });
    toast('Senha alterada', 'success');
    document.getElementById('form-change-password').reset();
  } catch (e) { toast('Falha: ' + e.message, 'error'); }
});

document.getElementById('btn-restart-server').addEventListener('click', async () => {
  const ok = await confirmDialog('Reiniciar servidor', 'Isso vai parar todos os containers e reiniciar o servidor ANK. Continuar?');
  if (!ok) return;
  try { await api('POST', '/system/restart-server'); } catch (e) {}
  toast('Servidor reiniciando…', 'warning');
});
document.getElementById('btn-restart-device').addEventListener('click', async () => {
  const ok = await confirmDialog('Reiniciar dispositivo', 'Isso vai reiniciar o dispositivo Android. Mantenha o USB conectado. Continuar?');
  if (!ok) return;
  try { await api('POST', '/system/restart-device'); toast('Dispositivo reiniciando…', 'warning'); } catch (e) { toast('Falha: ' + e.message, 'error'); }
});
document.getElementById('btn-uninstall').addEventListener('click', async () => {
  const ok = await confirmDialog('Desinstalar ANK', 'Isso vai remover o ANK e todos os containers permanentemente. Essa ação é irreversível.');
  if (!ok) return;
  try { await api('POST', '/system/uninstall'); toast('Desinstalação iniciada…', 'warning'); } catch (e) { toast('Falha: ' + e.message, 'error'); }
});
