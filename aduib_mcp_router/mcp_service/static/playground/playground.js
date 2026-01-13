// MCP Router Playground JavaScript

// State
const state = {
  theme: 'light',
  data: { servers: [], tools: [], resources: [], prompts: [] },
  healthInfo: {},
  activeTab: 'tools',
  selectedServerId: null,
  selectedItem: null,
  searchQuery: '',
  searchResults: null,
  history: [],
  lastResponse: null,
  pagination: { page: 1, pageSize: 20 }
};

// API
const BASE_URL = (() => {
  const url = new URL(window.location.href);
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url;
})();

const api = {
  // fast=1: use cached data for quick initial load
  // refresh=1: force reload all data from servers
  getData: (options = {}) => {
    const u = new URL('data', BASE_URL);
    if (options.fast) u.searchParams.set('fast', '1');
    if (options.refresh) u.searchParams.set('refresh', '1');
    return fetch(u).then(r => r.json());
  },
  getServerStatus: () => fetch(new URL('server-status', BASE_URL)).then(r => r.json()),
  getHealthInfo: () => fetch(new URL('health-info', BASE_URL)).then(r => r.json()),
  listServers: () => fetch(new URL('list-servers', BASE_URL)).then(r => r.json()),
  callTool: (name, args) => fetch(new URL('call-tool', BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool_name: name, arguments: args })
  }).then(r => r.json()),
  search: (q, type = 'all', limit = 20) => {
    const u = new URL('search', BASE_URL);
    u.searchParams.set('q', q);
    u.searchParams.set('type', type);
    u.searchParams.set('limit', limit);
    return fetch(u).then(r => r.json());
  },
  forceReconnect: (serverId) => fetch(new URL('force-reconnect', BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId })
  }).then(r => r.json()),
  // Server lifecycle control APIs
  startServer: (serverId) => fetch(new URL('start-server', BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId })
  }).then(r => r.json()),
  stopServer: (serverId) => fetch(new URL('stop-server', BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId })
  }).then(r => r.json()),
  restartServer: (serverId) => fetch(new URL('restart-server', BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_id: serverId })
  }).then(r => r.json())
};

// Utilities
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function toast(msg, detail = '', ms = 3000) {
  const el = document.getElementById('toast');
  el.querySelector('.message').textContent = msg;
  el.querySelector('.detail').textContent = detail;
  el.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove('show'), ms);
}

// Clipboard helper with fallback for non-secure contexts
async function copyToClipboard(text) {
  // Try modern clipboard API first (requires HTTPS or localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn('Clipboard API failed:', err);
    }
  }

  // Fallback: use textarea method
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '-9999px';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    const success = document.execCommand('copy');
    document.body.removeChild(textarea);
    return success;
  } catch (err) {
    document.body.removeChild(textarea);
    console.error('Fallback copy failed:', err);
    return false;
  }
}

function highlightJSON(obj) {
  let text;
  try { text = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2); }
  catch { text = String(obj); }
  const escaped = esc(text);
  return '<pre class="json" style="margin:0;white-space:pre-wrap;"><code>' +
    escaped.replace(
      /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"\s*:)|("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")|\b(true|false)\b|\b(null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
      m => {
        if (/^".*":$/.test(m)) return `<span class="key">${m}</span>`;
        if (/^"/.test(m)) return `<span class="string">${m}</span>`;
        if (/true|false/.test(m)) return `<span class="boolean">${m}</span>`;
        if (/null/.test(m)) return `<span class="null">${m}</span>`;
        return `<span class="number">${m}</span>`;
      }
    ) + '</code></pre>';
}

function statusToClass(status) {
  const map = { healthy: 'healthy', degraded: 'degraded', unhealthy: 'unhealthy', connecting: 'connecting', disconnected: 'disconnected' };
  return map[status] || 'disconnected';
}

// Theme
function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  document.getElementById('themeBtn').textContent = theme === 'dark' ? 'Light' : 'Dark';
  try { localStorage.setItem('mcp_theme', theme); } catch {}
}

function initTheme() {
  let theme = 'light';
  try { theme = localStorage.getItem('mcp_theme') || 'light'; } catch {}
  setTheme(theme === 'dark' ? 'dark' : 'light');
}

// Render functions
function updateStats() {
  const d = state.data;
  document.getElementById('statServers').textContent = d.servers.length;
  document.getElementById('statTools').textContent = d.tools.length;
  document.getElementById('statResources').textContent = d.resources.length;
  document.getElementById('statPrompts').textContent = d.prompts.length;

  const healthy = d.servers.filter(s => s.health?.status === 'healthy').length;
  document.getElementById('statServersHealth').textContent = `${healthy} healthy`;

  const successCount = state.history.filter(h => h.success).length;
  document.getElementById('statExecs').textContent = state.history.length;
  document.getElementById('statExecsSuccess').textContent = state.history.length ? `${successCount} success` : '-';
}

function renderServerList() {
  const el = document.getElementById('serverList');
  el.innerHTML = '';
  for (const server of state.data.servers) {
    const health = server.health || {};
    const statusClass = statusToClass(health.status);
    const isRunning = health.status === 'healthy' || health.status === 'degraded' || health.status === 'connecting';
    // Only stdio servers support start/stop control
    const isStdio = (server.type || '').toLowerCase() === 'stdio' || !server.type;
    const item = document.createElement('div');
    item.className = `server-item${state.selectedServerId === server.id ? ' active' : ''}`;
    item.innerHTML = `
      <div class="status-dot ${statusClass}" title="${esc(health.status || 'unknown')}"></div>
      <div class="server-info">
        <div class="name">${esc(server.name)}</div>
        <div class="meta">
          <span>${esc(server.type || 'stdio')}</span>
          <span>${health.latency_ms ? health.latency_ms.toFixed(0) + 'ms' : '-'}</span>
        </div>
      </div>
      ${isStdio ? `<div class="server-actions">
        ${isRunning
          ? `<button class="btn-icon-sm btn-stop" data-server-id="${esc(server.id)}" title="Stop Server">
               <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
             </button>`
          : `<button class="btn-icon-sm btn-start" data-server-id="${esc(server.id)}" title="Start Server">
               <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="8,5 19,12 8,19"/></svg>
             </button>`
        }
      </div>` : ''}
    `;
    // Click on server info to select
    item.querySelector('.server-info').addEventListener('click', () => selectServer(server.id));
    item.querySelector('.status-dot').addEventListener('click', () => selectServer(server.id));
    item.addEventListener('dblclick', (e) => {
      if (!e.target.closest('.server-actions')) openServerModal(server.id);
    });
    // Start/Stop button handlers (only for stdio servers)
    if (isStdio) {
      const startBtn = item.querySelector('.btn-start');
      const stopBtn = item.querySelector('.btn-stop');
      if (startBtn) startBtn.addEventListener('click', (e) => { e.stopPropagation(); startServer(server.id); });
      if (stopBtn) stopBtn.addEventListener('click', (e) => { e.stopPropagation(); stopServer(server.id); });
    }
    el.appendChild(item);
  }
}

function renderTabs() {
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === state.activeTab);
  });
}

function getFilteredItems() {
  const tab = state.activeTab;
  let items = state.searchResults ? state.searchResults[tab] : state.data[tab];
  items = items || [];
  if (state.selectedServerId) {
    items = items.filter(i => (i.server?.id || i.server_id) === state.selectedServerId);
  }
  return items;
}

function renderItemList() {
  const items = getFilteredItems();
  const { page, pageSize } = state.pagination;
  const start = (page - 1) * pageSize;
  const end = start + pageSize;
  const pageItems = items.slice(start, end);

  document.getElementById('itemCount').textContent = items.length;

  const el = document.getElementById('itemList');
  el.innerHTML = '';

  for (const item of pageItems) {
    const card = document.createElement('div');
    const itemId = item.name + '::' + (item.server?.id || item.server_id || '');
    card.className = `item-card${state.selectedItem?.id === itemId ? ' active' : ''}`;
    card.innerHTML = `
      <div class="top">
        <div class="name">${esc(item.name)}</div>
        <div class="badge">${esc(item.server?.name || '')}</div>
      </div>
      <div class="desc">${esc(item.description || '')}</div>
    `;
    card.addEventListener('click', () => selectItem(item));
    el.appendChild(card);
  }

  renderPagination(items.length);
}

function renderPagination(total) {
  const el = document.getElementById('pagination');
  const { page, pageSize } = state.pagination;
  const totalPages = Math.ceil(total / pageSize) || 1;

  el.innerHTML = `
    <button class="btn btn-sm" ${page <= 1 ? 'disabled' : ''} data-action="prev">&lt;</button>
    <span class="info">${page} / ${totalPages}</span>
    <button class="btn btn-sm" ${page >= totalPages ? 'disabled' : ''} data-action="next">&gt;</button>
  `;

  el.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.action === 'prev' && page > 1) state.pagination.page--;
      if (btn.dataset.action === 'next' && page < totalPages) state.pagination.page++;
      renderItemList();
    });
  });
}

function selectServer(serverId) {
  state.selectedServerId = state.selectedServerId === serverId ? null : serverId;
  state.selectedItem = null;
  state.pagination.page = 1;
  renderAll();
}

function selectItem(item) {
  const itemId = item.name + '::' + (item.server?.id || item.server_id || '');
  state.selectedItem = { ...item, id: itemId, kind: state.activeTab.slice(0, -1) };
  renderDetail();
  renderServerList();
  renderItemList();
}

function renderDetail() {
  const title = document.getElementById('detailTitle');
  const subtitle = document.getElementById('detailSubtitle');
  const kv = document.getElementById('detailKv');
  const copyBtn = document.getElementById('copyBtn');
  const healthPanel = document.getElementById('healthPanel');
  const executorEmpty = document.getElementById('executorEmpty');
  const toolForm = document.getElementById('toolForm');

  // Reset
  healthPanel.style.display = 'none';

  if (!state.selectedItem && !state.selectedServerId) {
    title.textContent = 'Select an item';
    subtitle.textContent = 'Choose a server or item from the sidebar.';
    kv.innerHTML = '<div class="key">Tip</div><div class="value">Use Ctrl+K for quick search.</div>';
    copyBtn.disabled = true;
    executorEmpty.style.display = 'block';
    toolForm.style.display = 'none';
    return;
  }

  // Server selected (show health info)
  if (state.selectedServerId && !state.selectedItem) {
    const server = state.data.servers.find(s => s.id === state.selectedServerId);
    if (!server) return;

    title.textContent = server.name;
    subtitle.textContent = `SERVER - ${server.type || 'stdio'}`;
    copyBtn.disabled = false;

    const health = server.health || {};
    kv.innerHTML = `
      <div class="key">ID</div><div class="value">${esc(server.id)}</div>
      <div class="key">Type</div><div class="value">${esc(server.type || 'stdio')}</div>
      <div class="key">Details</div><div class="value">${esc(server.details || '-')}</div>
      <div class="key">Tools</div><div class="value">${server.tool_count || 0}</div>
      <div class="key">Resources</div><div class="value">${server.resource_count || 0}</div>
      <div class="key">Prompts</div><div class="value">${server.prompt_count || 0}</div>
    `;

    healthPanel.style.display = 'block';
    renderHealthGrid(health, server.id);

    executorEmpty.style.display = 'block';
    toolForm.style.display = 'none';
    return;
  }

  // Item selected
  const item = state.selectedItem;
  title.textContent = item.name;
  subtitle.textContent = `${item.kind.toUpperCase()} - ${item.server?.name || ''}`;
  copyBtn.disabled = false;

  const rows = [];
  if (item.kind === 'tool') {
    rows.push(['Name', item.name]);
    rows.push(['Server', item.server?.name || '']);
    rows.push(['Description', item.description || '']);
    if (item.inputSchema) rows.push(['Schema', 'Has inputSchema']);
  } else if (item.kind === 'resource') {
    rows.push(['Name', item.name]);
    rows.push(['URI', item.uri || '']);
    rows.push(['MIME Type', item.mime_type || item.mimeType || '']);
    rows.push(['Description', item.description || '']);
  } else {
    rows.push(['Name', item.name]);
    rows.push(['Description', item.description || '']);
    if (item.arguments?.length) rows.push(['Arguments', JSON.stringify(item.arguments)]);
  }

  kv.innerHTML = rows.map(([k, v]) => `<div class="key">${esc(k)}</div><div class="value">${esc(v)}</div>`).join('');

  // Tool executor
  if (item.kind === 'tool') {
    executorEmpty.style.display = 'none';
    toolForm.style.display = 'block';
    generateForm(item.inputSchema || item.input_schema || {});
    toolForm.dataset.toolName = item.name;
    document.getElementById('execHint').textContent = item.inputSchema ? 'Form generated from inputSchema' : 'No schema - provide JSON';
  } else {
    executorEmpty.style.display = 'block';
    toolForm.style.display = 'none';
  }
}

function renderHealthGrid(health, serverId) {
  const el = document.getElementById('healthGrid');
  const status = health.status || 'disconnected';
  const statusClass = status === 'healthy' ? 'success' : (status === 'degraded' ? 'warning' : 'error');
  const isRunning = status === 'healthy' || status === 'degraded' || status === 'connecting';

  // Check if server is stdio type
  const server = state.data.servers.find(s => s.id === serverId);
  const isStdio = server && ((server.type || '').toLowerCase() === 'stdio' || !server.type);

  el.innerHTML = `
    <div class="health-item">
      <div class="label">Status</div>
      <div class="value ${statusClass}">${esc(status)}</div>
    </div>
    <div class="health-item">
      <div class="label">Latency</div>
      <div class="value">${health.latency_ms ? health.latency_ms.toFixed(1) + 'ms' : '-'}</div>
    </div>
    <div class="health-item">
      <div class="label">Failures</div>
      <div class="value ${health.consecutive_failures > 0 ? 'warning' : ''}">${health.consecutive_failures || 0}</div>
    </div>
    <div class="health-item">
      <div class="label">Uptime</div>
      <div class="value">${health.uptime_seconds ? formatUptime(health.uptime_seconds) : '-'}</div>
    </div>
  `;

  // Update action buttons in health panel (only for stdio servers)
  const actionBtns = document.getElementById('healthActionBtns');
  if (actionBtns && serverId) {
    if (isStdio) {
      actionBtns.innerHTML = isRunning
        ? `<button class="btn btn-sm btn-warning" id="stopServerBtn">Stop</button>
           <button class="btn btn-sm btn-primary" id="restartServerBtn">Restart</button>
           <button class="btn btn-sm btn-danger" id="reconnectBtn">Force Reconnect</button>`
        : `<button class="btn btn-sm btn-success" id="startServerBtn">Start</button>`;

      const startBtn = actionBtns.querySelector('#startServerBtn');
      const stopBtn = actionBtns.querySelector('#stopServerBtn');
      const restartBtn = actionBtns.querySelector('#restartServerBtn');
      const reconnectBtn = actionBtns.querySelector('#reconnectBtn');

      if (startBtn) startBtn.addEventListener('click', () => startServer(serverId));
      if (stopBtn) stopBtn.addEventListener('click', () => stopServer(serverId));
      if (restartBtn) restartBtn.addEventListener('click', () => restartServer(serverId));
      if (reconnectBtn) reconnectBtn.addEventListener('click', () => forceReconnect(serverId));
    } else {
      // Non-stdio servers only show reconnect
      actionBtns.innerHTML = isRunning
        ? `<button class="btn btn-sm btn-danger" id="reconnectBtn">Force Reconnect</button>`
        : '';
      const reconnectBtn = actionBtns.querySelector('#reconnectBtn');
      if (reconnectBtn) reconnectBtn.addEventListener('click', () => forceReconnect(serverId));
    }
  }
}

function formatUptime(seconds) {
  if (seconds < 60) return Math.floor(seconds) + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
  return Math.floor(seconds / 86400) + 'd';
}

function generateForm(schema) {
  const container = document.getElementById('formContainer');
  container.innerHTML = '';

  if (!schema || !schema.properties) {
    const field = document.createElement('div');
    field.className = 'field full';
    field.innerHTML = `
      <label>Arguments <span class="req">*</span></label>
      <textarea data-path="__root__" placeholder="{}"></textarea>
      <div class="hint">Enter tool arguments as JSON</div>
    `;
    container.appendChild(field);
    return;
  }

  const required = new Set(schema.required || []);
  for (const [name, prop] of Object.entries(schema.properties)) {
    container.appendChild(createField(name, prop, required.has(name)));
  }
}

function createField(name, schema, isRequired) {
  const field = document.createElement('div');
  field.className = 'field';

  const type = Array.isArray(schema.type) ? schema.type[0] : (schema.type || 'string');
  const title = schema.title || name;
  const desc = schema.description || '';

  field.innerHTML = `<label>${esc(title)}${isRequired ? ' <span class="req">*</span>' : ''}</label>`;

  let input;
  if (type === 'boolean') {
    input = document.createElement('select');
    input.innerHTML = '<option value="">(default)</option><option value="true">true</option><option value="false">false</option>';
  } else if (type === 'number' || type === 'integer') {
    input = document.createElement('input');
    input.type = 'number';
    input.step = type === 'integer' ? '1' : 'any';
  } else if (type === 'array' || type === 'object') {
    input = document.createElement('textarea');
    input.placeholder = type === 'array' ? '[]' : '{}';
    field.className = 'field full';
  } else {
    input = document.createElement('input');
    input.type = 'text';
  }

  input.dataset.path = name;
  input.dataset.type = type;
  if (schema.default !== undefined) {
    input.value = typeof schema.default === 'object' ? JSON.stringify(schema.default) : String(schema.default);
  }

  field.appendChild(input);
  if (desc) {
    const hint = document.createElement('div');
    hint.className = 'hint';
    hint.textContent = desc;
    field.appendChild(hint);
  }

  return field;
}

function collectFormArgs() {
  const container = document.getElementById('formContainer');
  const args = {};

  for (const el of container.querySelectorAll('[data-path]')) {
    const path = el.dataset.path;
    const type = el.dataset.type;
    let value = el.value;

    if (path === '__root__') {
      if (!value.trim()) return {};
      try { return JSON.parse(value); }
      catch (e) { throw new Error('Invalid JSON: ' + e.message); }
    }

    if (value === '' || value === null) continue;

    if (type === 'boolean' && (value === 'true' || value === 'false')) {
      value = value === 'true';
    } else if (type === 'number' || type === 'integer') {
      value = Number(value);
    } else if (type === 'array' || type === 'object') {
      try { value = JSON.parse(value); } catch {}
    }

    args[path] = value;
  }

  return args;
}

function renderHistory() {
  const el = document.getElementById('historyList');
  if (!state.history.length) {
    el.innerHTML = '<p style="color:var(--text-secondary);font-size:13px;">No executions yet.</p>';
    return;
  }

  el.innerHTML = state.history.slice().reverse().map(h => `
    <div class="history-item">
      <div class="header">
        <span class="title">${esc(h.tool_name)}</span>
        <span class="time">${esc(h.at)}</span>
      </div>
      <div class="status ${h.success ? 'success' : 'error'}">${h.success ? 'Success' : 'Error: ' + esc(h.error)}</div>
    </div>
  `).join('');
}

function renderResponse(data) {
  state.lastResponse = data;
  document.getElementById('responseBox').innerHTML = highlightJSON(data);
  document.getElementById('copyResponseBtn').disabled = false;
}

function renderAll() {
  updateStats();
  renderServerList();
  renderTabs();
  renderItemList();
  renderDetail();
  renderHistory();
}

// Server Modal
function openServerModal(serverId) {
  const server = state.data.servers.find(s => s.id === serverId);
  if (!server) return;

  // Check if server is stdio type
  const isStdio = (server.type || '').toLowerCase() === 'stdio' || !server.type;

  document.getElementById('modalServerName').textContent = server.name;

  const details = document.getElementById('modalServerDetails');
  details.innerHTML = `
    <div class="key">ID</div><div class="value">${esc(server.id)}</div>
    <div class="key">Name</div><div class="value">${esc(server.name)}</div>
    <div class="key">Type</div><div class="value">${esc(server.type || 'stdio')}</div>
    <div class="key">Details</div><div class="value">${esc(server.details || '-')}</div>
    <div class="key">Tools</div><div class="value">${server.tool_count || 0}</div>
    <div class="key">Resources</div><div class="value">${server.resource_count || 0}</div>
    <div class="key">Prompts</div><div class="value">${server.prompt_count || 0}</div>
  `;

  const health = server.health || {};
  const healthGrid = document.getElementById('modalHealthGrid');
  const status = health.status || 'disconnected';
  const statusClass = status === 'healthy' ? 'success' : (status === 'degraded' ? 'warning' : 'error');
  const isRunning = status === 'healthy' || status === 'degraded' || status === 'connecting';

  healthGrid.innerHTML = `
    <div class="health-item">
      <div class="label">Status</div>
      <div class="value ${statusClass}">${esc(status)}</div>
    </div>
    <div class="health-item">
      <div class="label">Latency</div>
      <div class="value">${health.latency_ms ? health.latency_ms.toFixed(1) + 'ms' : '-'}</div>
    </div>
    <div class="health-item">
      <div class="label">Consecutive Failures</div>
      <div class="value">${health.consecutive_failures || 0}</div>
    </div>
    <div class="health-item">
      <div class="label">Total Failures</div>
      <div class="value">${health.total_failures || 0}</div>
    </div>
  `;

  // Update modal footer buttons based on server state and type
  const modalFooter = document.querySelector('#serverModal .modal-footer');
  if (isStdio) {
    modalFooter.innerHTML = isRunning
      ? `<button class="btn btn-warning" id="modalStopBtn">Stop</button>
         <button class="btn btn-primary" id="modalRestartBtn">Restart</button>
         <button class="btn btn-danger" id="modalReconnectBtn">Force Reconnect</button>
         <button class="btn" id="modalCloseBtn">Close</button>`
      : `<button class="btn btn-success" id="modalStartBtn">Start</button>
         <button class="btn" id="modalCloseBtn">Close</button>`;
  } else {
    // Non-stdio servers only show reconnect option
    modalFooter.innerHTML = isRunning
      ? `<button class="btn btn-danger" id="modalReconnectBtn">Force Reconnect</button>
         <button class="btn" id="modalCloseBtn">Close</button>`
      : `<button class="btn" id="modalCloseBtn">Close</button>`;
  }

  // Bind event handlers
  const startBtn = modalFooter.querySelector('#modalStartBtn');
  const stopBtn = modalFooter.querySelector('#modalStopBtn');
  const restartBtn = modalFooter.querySelector('#modalRestartBtn');
  const reconnectBtn = modalFooter.querySelector('#modalReconnectBtn');
  const closeBtn = modalFooter.querySelector('#modalCloseBtn');

  if (startBtn) startBtn.addEventListener('click', () => { startServer(serverId); closeServerModal(); });
  if (stopBtn) stopBtn.addEventListener('click', () => { stopServer(serverId); closeServerModal(); });
  if (restartBtn) restartBtn.addEventListener('click', () => { restartServer(serverId); closeServerModal(); });
  if (reconnectBtn) reconnectBtn.addEventListener('click', () => { forceReconnect(serverId); closeServerModal(); });
  if (closeBtn) closeBtn.addEventListener('click', closeServerModal);

  document.getElementById('serverModal').classList.add('show');
}

function closeServerModal() {
  document.getElementById('serverModal').classList.remove('show');
}

// Export Modal
function openExportModal() {
  document.getElementById('exportModal').classList.add('show');
}

function closeExportModal() {
  document.getElementById('exportModal').classList.remove('show');
}

function exportJSON() {
  const data = JSON.stringify(state.history, null, 2);
  downloadFile(data, 'mcp-history.json', 'application/json');
  closeExportModal();
  toast('Exported', 'History saved as JSON');
}

function exportCSV() {
  const headers = ['timestamp', 'tool_name', 'server_name', 'success', 'arguments', 'result', 'error'];
  const rows = state.history.map(h => [
    h.at,
    h.tool_name,
    h.server_name || '',
    h.success,
    JSON.stringify(h.arguments),
    JSON.stringify(h.result),
    h.error || ''
  ]);

  const csv = [headers.join(','), ...rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))].join('\n');
  downloadFile(csv, 'mcp-history.csv', 'text/csv');
  closeExportModal();
  toast('Exported', 'History saved as CSV');
}

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Actions
async function refreshData(options = {}) {
  const { fast = false, refresh = false, silent = false } = options;
  try {
    const [data, health] = await Promise.all([
      api.getData({ fast, refresh }),
      api.getHealthInfo().catch(() => ({ servers: [] }))
    ]);

    // Merge health info into servers
    const healthMap = new Map((health.servers || []).map(s => [s.server_id, s]));
    data.servers = data.servers.map(s => ({
      ...s,
      health: healthMap.get(s.id) || s.status || {}
    }));

    state.data = data;
    state.searchResults = null;
    renderAll();
    if (!silent) {
      toast('Refreshed', refresh ? 'Data reloaded from servers' : 'Data loaded successfully');
    }
  } catch (e) {
    toast('Error', 'Failed to load data: ' + e.message, 5000);
  }
}

// Quick refresh using cached data only
async function quickRefresh() {
  await refreshData({ fast: true, silent: true });
}

// Full refresh forcing reload from all servers
async function forceRefresh() {
  toast('Refreshing...', 'Reloading data from all servers');
  await refreshData({ refresh: true });
}

async function forceReconnect(serverId) {
  try {
    await api.forceReconnect(serverId);
    toast('Reconnecting', 'Force reconnect initiated');
    setTimeout(refreshData, 2000);
  } catch (e) {
    toast('Error', 'Reconnect failed: ' + e.message);
  }
}

async function startServer(serverId) {
  const server = state.data.servers.find(s => s.id === serverId);
  const serverName = server?.name || serverId;
  toast('Starting...', serverName);
  try {
    const result = await api.startServer(serverId);
    if (result.success) {
      toast('Started', result.message || `${serverName} started successfully`);
    } else {
      toast('Failed', result.message || 'Failed to start server');
    }
    setTimeout(refreshData, 1000);
  } catch (e) {
    toast('Error', 'Start failed: ' + e.message);
  }
}

async function stopServer(serverId) {
  const server = state.data.servers.find(s => s.id === serverId);
  const serverName = server?.name || serverId;
  toast('Stopping...', serverName);
  try {
    const result = await api.stopServer(serverId);
    if (result.success) {
      toast('Stopped', result.message || `${serverName} stopped successfully`);
    } else {
      toast('Failed', result.message || 'Failed to stop server');
    }
    setTimeout(refreshData, 1000);
  } catch (e) {
    toast('Error', 'Stop failed: ' + e.message);
  }
}

async function restartServer(serverId) {
  const server = state.data.servers.find(s => s.id === serverId);
  const serverName = server?.name || serverId;
  toast('Restarting...', serverName);
  try {
    const result = await api.restartServer(serverId);
    if (result.success) {
      toast('Restarted', result.message || `${serverName} restarted successfully`);
    } else {
      toast('Failed', result.message || 'Failed to restart server');
    }
    setTimeout(refreshData, 1500);
  } catch (e) {
    toast('Error', 'Restart failed: ' + e.message);
  }
}

const debounce = (fn, ms) => {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
};

const doSearch = debounce(async () => {
  const q = state.searchQuery.trim();
  if (!q) {
    state.searchResults = null;
    renderAll();
    return;
  }
  try {
    state.searchResults = await api.search(q, 'all', 50);
    state.pagination.page = 1;
    renderAll();
  } catch (e) {
    toast('Search failed', e.message);
  }
}, 300);

// Event bindings
function bindEvents() {
  // Theme
  document.getElementById('themeBtn').addEventListener('click', () => {
    setTheme(state.theme === 'dark' ? 'light' : 'dark');
  });

  // Refresh - force reload on button click
  document.getElementById('refreshBtn').addEventListener('click', () => forceRefresh());

  // Search
  document.getElementById('searchInput').addEventListener('input', e => {
    state.searchQuery = e.target.value;
    doSearch();
  });

  // Keyboard shortcut
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      document.getElementById('searchInput').focus();
    }
  });

  // Clear server filter
  document.getElementById('clearServerBtn').addEventListener('click', () => {
    state.selectedServerId = null;
    state.selectedItem = null;
    renderAll();
  });

  // Tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      state.activeTab = tab.dataset.tab;
      state.selectedItem = null;
      state.pagination.page = 1;
      renderAll();
    });
  });

  // Tool form submit
  document.getElementById('toolForm').addEventListener('submit', async e => {
    e.preventDefault();
    const toolName = e.target.dataset.toolName;
    if (!toolName) return;

    let args;
    try { args = collectFormArgs(); }
    catch (err) { toast('Invalid input', err.message); return; }

    document.getElementById('executeBtn').disabled = true;
    toast('Executing...', toolName);

    try {
      const resp = await api.callTool(toolName, args);
      const entry = {
        at: new Date().toLocaleString(),
        tool_name: toolName,
        server_name: state.selectedItem?.server?.name || '',
        arguments: args,
        success: !!resp.success,
        result: resp.result,
        error: resp.error
      };
      state.history.push(entry);
      renderResponse(resp);
      renderHistory();
      updateStats();
      toast(resp.success ? 'Success' : 'Failed', resp.success ? 'Tool executed' : resp.error);
    } catch (err) {
      toast('Error', err.message);
    } finally {
      document.getElementById('executeBtn').disabled = false;
    }
  });

  // Copy buttons - using fallback helper
  document.getElementById('copyBtn').addEventListener('click', async () => {
    const item = state.selectedItem || (state.selectedServerId && state.data.servers.find(s => s.id === state.selectedServerId));
    if (item) {
      const success = await copyToClipboard(JSON.stringify(item, null, 2));
      toast(success ? 'Copied' : 'Copy failed', success ? 'JSON copied to clipboard' : 'Could not copy to clipboard');
    }
  });

  document.getElementById('copyResponseBtn').addEventListener('click', async () => {
    if (state.lastResponse) {
      const success = await copyToClipboard(JSON.stringify(state.lastResponse, null, 2));
      toast(success ? 'Copied' : 'Copy failed', success ? 'Response copied to clipboard' : 'Could not copy to clipboard');
    }
  });

  // Clear history
  document.getElementById('clearHistoryBtn').addEventListener('click', () => {
    state.history = [];
    renderHistory();
    updateStats();
    toast('Cleared', 'History cleared');
  });

  // Reconnect button
  document.getElementById('reconnectBtn').addEventListener('click', () => {
    if (state.selectedServerId) forceReconnect(state.selectedServerId);
  });

  // Export
  document.getElementById('exportBtn').addEventListener('click', openExportModal);
  document.getElementById('exportJsonBtn').addEventListener('click', exportJSON);
  document.getElementById('exportCsvBtn').addEventListener('click', exportCSV);
  document.getElementById('cancelExportBtn').addEventListener('click', closeExportModal);
  document.getElementById('closeExportModalBtn').addEventListener('click', closeExportModal);

  // Server modal
  document.getElementById('closeModalBtn').addEventListener('click', closeServerModal);
  document.getElementById('modalCloseBtn').addEventListener('click', closeServerModal);
  document.getElementById('serverModal').addEventListener('click', e => {
    if (e.target.id === 'serverModal') closeServerModal();
  });
  document.getElementById('exportModal').addEventListener('click', e => {
    if (e.target.id === 'exportModal') closeExportModal();
  });
}

// Auto refresh
function startAutoRefresh() {
  setInterval(async () => {
    try {
      const health = await api.getHealthInfo();
      const healthMap = new Map((health.servers || []).map(s => [s.server_id, s]));
      state.data.servers = state.data.servers.map(s => ({
        ...s,
        health: healthMap.get(s.id) || s.health || {}
      }));
      renderServerList();
      if (state.selectedServerId && !state.selectedItem) {
        renderDetail();
      }
      updateStats();
    } catch {}
  }, 30000);
}

// Init
async function init() {
  console.log('[MCP Playground] Initializing...');
  initTheme();
  bindEvents();

  // Always load data on page load (no fast mode on first load)
  console.log('[MCP Playground] Loading data...');
  await refreshData({ silent: false });

  startAutoRefresh();
  console.log('[MCP Playground] Init complete');
}

// Run init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
