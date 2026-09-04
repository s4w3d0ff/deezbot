const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let toastTimer = null;
function toast(msg, ms = 4000) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}

async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    let body = null;
    try { body = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error((body && (body.error || JSON.stringify(body))) || `HTTP ${r.status}`);
    return body;
  } catch (e) {
    toast(`${path}: ${e.message}`);
    throw e;
  }
}

const post = (path, data) => api(path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
const del = (path, data) => api(path, { method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data || {}) });

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined && text !== null) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}

function fmtUptime(secs) {
  if (!secs && secs !== 0) return '-';
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${Math.floor(secs % 60)}s`;
}

function tokenLabel(expiresTime) {
  if (!expiresTime) return '-';
  const secs = Math.floor(expiresTime - Date.now() / 1000);
  if (secs <= 0) return 'expired';
  return fmtUptime(secs);
}

async function refreshStatus() {
  let s;
  try { s = await api('/api/status'); } catch (_) { return; }

  $('#ws-dot').className = `dot ${s.ws_connected ? 'on' : 'off'}`;
  $('#hdr-user').textContent = s.username ? `@${s.username}` : '';

  const kpis = [
    ['bot', s.authenticated ? (s.username ? `@${s.username}` : 'authenticated') : 'not authenticated'],
    ['uptime', fmtUptime(s.uptime_seconds)],
    ['token expiry', tokenLabel(s.token_expires_time)],
    ['websocket', s.ws_connected ? 'connected' : 'disconnected'],
    ['channels', `${s.channels_total} connected`],
    ['live now', String(s.channels_live)],
    ['ignored users', String(s.ignores_total)],
    ['jokes loaded', String(s.jokes_total)],
  ];
  const grid = $('#kpi-grid');
  grid.replaceChildren();
  for (const [k, v] of kpis) {
    const c = el('div', null, 'cell');
    c.append(el('div', k, 'k'), el('div', v, 'v'));
    grid.append(c);
  }
  await refreshChannels();
}

async function refreshChannels() {
  let body;
  try { body = await api('/api/channels'); } catch (_) { return; }
  const rows = body.channels || [];
  $('#chan-count').textContent = `${body.total} connected · ${body.live} live`;
  const tbody = $('#channels-table tbody');
  tbody.replaceChildren();
  for (const c of rows) {
    const tr = el('tr');
    const dotTd = el('td');
    dotTd.append(el('span', null, `live-dot ${c.is_live ? 'on' : 'off'}`));
    tr.append(dotTd);
    tr.append(
      el('td', c.login || '-', c.is_live ? '' : 'muted'),
      el('td', c.display_name || '-'),
      el('td', c.user_id, 'muted'),
      el('td', c.jemote),
      el('td', c.is_live ? String(c.viewers) : '-', c.is_live ? '' : 'muted'),
    );
    const titleTd = el('td', c.title || '-', (c.is_live && c.title) ? '' : 'muted');
    if (c.title) titleTd.title = c.title;
    tr.append(titleTd);
    tbody.append(tr);
  }
}

async function loadCommands() {
  let body;
  try { body = await api('/api/commands'); } catch (_) { return; }
  const rows = body.commands || [];
  $('#cmd-count').textContent = `${rows.length} commands`;
  const tbody = $('#commands-table tbody');
  tbody.replaceChildren();
  for (const c of rows) {
    const tr = el('tr');
    tr.append(
      el('td', c.name),
      el('td', c.aliases.join(', ') || '-', c.aliases.length ? '' : 'muted'),
      el('td', c.help || '-'),
    );
    tbody.append(tr);
  }
}

$('#btn-joke').addEventListener('click', async () => {
  const message = $('#joke-input').value.trim();
  if (!message) return toast('type a message to test');
  $('#btn-joke').disabled = true;
  try {
    const r = await post('/api/test/joke', { message });
    $('#joke-out').textContent = r.reply ? `reply: ${r.reply}${r.matched_keyword ? ` [keyword: ${r.matched_keyword}]` : ''}` : 'no joke produced';
  } catch (_) {}
  $('#btn-joke').disabled = false;
});

$('#btn-chat').addEventListener('click', async () => {
  const message = $('#chat-input').value.trim();
  if (!message) return toast('type a message to send');
  if (!confirm(`send this real chat message in your own channel?\n\n${message}`)) return;
  $('#btn-chat').disabled = true;
  try {
    const r = await post('/api/test/chat', { message });
    $('#chat-out').textContent = `sent ${r.sent_chunks} chunk(s)`;
    $('#chat-input').value = '';
  } catch (_) {}
  $('#btn-chat').disabled = false;
});

function tdInput(origValue, onSave) {
  const td = el('td', String(origValue ?? ''), 'cell-edit');
  let editing = false;
  td.addEventListener('click', () => {
    if (editing) return;
    editing = true;
    const input = el('input', null, 'cell-input');
    input.value = String(origValue ?? '');
    td.replaceChildren(input);
    input.focus();
    input.select();
    let done = false;
    const finish = async (commit) => {
      if (done) return;
      done = true;
      editing = false;
      const v = commit ? String(input.value).trim() : null;
      if (!commit || v === '') {
        td.textContent = String(origValue ?? '');
        return;
      }
      try {
        await onSave(v);
      } catch (_) {
        td.textContent = String(origValue ?? '');
      }
    };
    input.addEventListener('blur', () => finish(true), { once: true });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') input.blur();
      if (e.key === 'Escape') { done = true; editing = false; td.textContent = String(origValue ?? ''); }
    });
  });
  return td;
}

async function loadJokes() {
  let body;
  try { body = await api('/api/db/table/joke?limit=500'); } catch (_) { return; }
  const rows = body.rows || [];
  $('#joke-count').textContent = `${rows.length} keywords`;
  const tbody = $('#jokes-table tbody');
  tbody.replaceChildren();
  for (const row of rows) {
    const tr = el('tr');
    const kwTd = tdInput(row.keyword, async v => { await post('/api/db/table/joke', { ...row, keyword: v }); loadJokes(); refreshStatus(); });
    const jokeTd = tdInput(row.joke, async v => { if (!v) return; await post('/api/db/table/joke', { ...row, joke: v }); });
    const delTd = el('td');
    const b = el('button', 'del');
    b.addEventListener('click', async () => {
      if (!confirm(`delete joke keyword "${row.keyword}"?`)) return;
      try { await del('/api/db/table/joke', { where: 'keyword = ?', params: [String(row.keyword)] }); loadJokes(); refreshStatus(); } catch (_) {}
    });
    delTd.append(b);
    tr.append(kwTd, jokeTd, delTd);
    tbody.append(tr);
  }
}

$('#new-joke-form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target;
  const keyword = form.keyword.value.trim();
  const joke = form.joke.value.trim();
  if (!keyword || !joke) return toast('keyword and joke both required');
  try {
    await post('/api/db/table/joke', { keyword, joke });
    form.reset();
    loadJokes();
    refreshStatus();
  } catch (_) {}
});

async function loadIgnores() {
  let body;
  try { body = await api('/api/ignores'); } catch (_) { return; }
  const rows = body.users || [];
  $('#ignore-count').textContent = `${rows.length} users`;
  const tbody = $('#ignores-table tbody');
  tbody.replaceChildren();
  for (const u of rows) {
    const tr = el('tr');
    tr.append(el('td', u.user_id, 'muted'), el('td', u.login || '-'), el('td', u.display_name || '-'));
    const actTd = el('td');
    if (u.ignored) {
      const b = el('button', 'unignore');
      b.addEventListener('click', async () => { try { await post('/api/db/table/ignore', { user_id: String(u.user_id), ignore: 'False' }); loadIgnores(); } catch (_) {} });
      actTd.append(b);
    } else {
      const b = el('button', 'remove');
      b.addEventListener('click', async () => {
        if (!confirm(`remove ${u.login || u.user_id} from ignore list?`)) return;
        try { await del('/api/db/table/ignore', { where: 'user_id = ?', params: [String(u.user_id)] }); loadIgnores(); } catch (_) {}
      });
      actTd.append(b);
    }
    tr.append(actTd);
    tbody.append(tr);
  }
}

async function loadDataChannels() {
  let body;
  try { body = await api('/api/channels'); } catch (_) { return; }
  const rows = body.channels || [];
  $('#data-chan-count').textContent = `${rows.length} channels`;
  const tbody = $('#chans-table tbody');
  tbody.replaceChildren();
  for (const c of rows) {
    const tr = el('tr');
    tr.append(el('td', c.user_id, 'muted'));
    const loginTd = el('td');
    if (c.is_live) loginTd.append(el('span', null, 'live-dot on'));
    loginTd.append(c.login || '-');
    tr.append(loginTd);
    const jemoteTd = tdInput(c.jemote, async v => { if (!v) return; await post('/api/db/table/channels', { user_id: String(c.user_id), jemote: v }); loadDataChannels(); });
    tr.append(jemoteTd);
    const actTd = el('td');
    const b = el('button', 'leave');
    b.title = `stop watching channel ${c.login || c.user_id}`;
    b.addEventListener('click', async () => {
      if (!confirm(`stop watching channel ${c.login || c.user_id}?`)) return;
      try { await del('/api/db/table/channels', { where: 'user_id = ?', params: [String(c.user_id)] }); loadDataChannels(); refreshStatus(); } catch (_) {}
    });
    actTd.append(b);
    tr.append(actTd);
    tbody.append(tr);
  }
}

let rawState = { current: null, writable: false };

async function loadRawTables() {
  let body;
  try { body = await api('/api/db/tables'); } catch (_) { return; }
  const ul = $('#raw-table-list');
  ul.replaceChildren();
  for (const t of body.tables) {
    const li = el('li', null, rawState.current === t.name ? 'active' : '');
    li.append(el('span', `${t.name}${t.writable ? '' : ' ro'}`), el('span', String(t.row_count), 'cnt'));
    li.addEventListener('click', () => selectRawTable(t));
    ul.append(li);
  }
}

async function selectRawTable(t) {
  rawState.current = t.name;
  rawState.writable = t.writable;
  $('#raw-title').textContent = `${t.name}${t.writable ? '' : ' (read-only)'}`;
  const nf = $('#new-row-form');
  nf.classList.add('hidden');
  let btn = document.getElementById('btn-new-raw-row');
  if (!t.writable) {
    if (btn) btn.remove();
  } else {
    if (!btn) {
      btn = el('button', 'New row', null);
      btn.id = 'btn-new-raw-row';
      btn.addEventListener('click', async () => {
        const form = $('#new-row-form');
        if (!form.classList.contains('hidden')) { form.classList.add('hidden'); return; }
        let body;
        try { body = await api(`/api/db/table/${encodeURIComponent(rawState.current)}?limit=1`); } catch (_) {}
        const cols = collectCols(body && body.rows ? body.rows : []);
        if (!cols.length) return toast('table has no rows, add columns via chat commands first');
        form.replaceChildren();
        for (const c of cols) {
          const label = el('label', c);
          const input = el('input');
          input.name = c;
          label.append(input);
          form.append(label);
        }
        form.classList.remove('hidden');
      });
      $('#raw-title').parentNode.insertBefore(btn, $('#raw-title').nextSibling);
    }
  }
  for (const li of $$('#raw-table-list li')) {
    li.classList.toggle('active', li.querySelector('span').textContent.startsWith(t.name));
  }
  await loadRawRows();
}

async function loadRawRows() {
  if (!rawState.current) return;
  let body;
  try { body = await api(`/api/db/table/${encodeURIComponent(rawState.current)}?limit=200`); } catch (_) { return; }
  const rows = body.rows || [];
  const cols = collectCols(rows);
  const table = $('#rows-table');
  table.replaceChildren();
  if (!cols.length) {
    table.append(el('tr').append(el('td', 'no rows')));
    return;
  }
  const thead = el('thead');
  const htr = el('tr');
  for (const c of cols) htr.append(el('th', c));
  if (rawState.writable) htr.append(el('th'));
  thead.append(htr);
  const tbody = el('tbody');
  rows.forEach((row, i) => {
    const tr = el('tr');
    for (const c of cols) {
      if (rawState.writable && i === 0) {
        tr.append(tdInput(row[c] ?? '', async v => {
          const updated = { ...row, [c]: v };
          await post(`/api/db/table/${encodeURIComponent(rawState.current)}`, updated);
          loadRawRows();
        }));
      } else {
        tr.append(el('td', String(row[c] ?? '')));
      }
    }
    if (rawState.writable && i === 0) {
      const tdBtn = el('td');
      const b = el('button', 'del');
      b.addEventListener('click', async () => await deleteRawRow(row, cols[0]));
      tdBtn.append(b);
      tr.append(tdBtn);
    }
    tbody.append(tr);
  });
  table.append(thead, tbody);
}

async function deleteRawRow(row, pkCol) {
  const val = String(row[pkCol] ?? '');
  if (!confirm(`delete this ${rawState.current} row?\n${pkCol} = ${val}`)) return;
  try {
    await del(`/api/db/table/${encodeURIComponent(rawState.current)}`, { where: `${pkCol} = ?`, params: [val] });
    loadRawRows();
    loadRawTables();
  } catch (_) {}
}

function collectCols(rows) {
  const seen = new Set();
  for (const row of rows) for (const k of Object.keys(row)) if (!seen.has(k)) seen.add(k);
  return [...seen];
}

$('#new-row-form').addEventListener('submit', async e => {
  e.preventDefault();
  const data = {};
  for (const input of $$('#new-row-form input')) data[input.name] = input.value;
  try {
    await post(`/api/db/table/${encodeURIComponent(rawState.current)}`, data);
    $('#new-row-form').classList.add('hidden');
    loadRawRows();
    loadRawTables();
  } catch (_) {}
});

let activeTab = 'status';
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
let logCache = [];
let logState = { minLevel: '', lastSeq: 0, atBottom: true };

function levelPass(entry) {
  if (!logState.minLevel) return true;
  return LOG_LEVELS.indexOf(entry.level) >= LOG_LEVELS.indexOf(logState.minLevel);
}

function logLineText(e) {
  return `${e.ts} ${e.level.padEnd(7)} [${e.name}] ${e.msg}`;
}

function appendLogLines(entries) {
  const view = $('#log-view');
  for (const e of entries) {
    if (!levelPass(e)) continue;
    view.append(el('span', logLineText(e), `log-line log-${e.level.toLowerCase()}`), '\n');
  }
  if (logState.atBottom) view.scrollTop = view.scrollHeight;
}

function renderLogsFull() {
  const view = $('#log-view');
  view.replaceChildren();
  appendLogLines(logCache);
  logState.lastSeq = logCache.length ? logCache[logCache.length - 1].seq : 0;
}

async function pollLogs(full) {
  if (activeTab !== 'log') return;
  let body;
  try { body = await api('/api/logs?lines=1000'); } catch (_) { return; }
  logCache = body.entries || [];
  $('#log-count').textContent = `${body.total} buffered`;
  if (full) { renderLogsFull(); return; }
  const fresh = logCache.filter(e => e.seq > logState.lastSeq);
  appendLogLines(fresh);
  if (fresh.length) logState.lastSeq = fresh[fresh.length - 1].seq;
}

$('#log-view').addEventListener('scroll', e => { logState.atBottom = e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 8; });
setInterval(() => pollLogs(false), 2000);
$('#btn-log-refresh').addEventListener('click', () => pollLogs(true));
$('#log-level').addEventListener('change', e => { logState.minLevel = e.target.value; renderLogsFull(); });

function loadActiveTab() {
  if (activeTab === 'data') {
    loadJokes();
    loadIgnores();
    loadDataChannels();
    loadRawTables();
  } else if (activeTab === 'log') {
    pollLogs(true);
  }
}

$$('.tab').forEach(btn => btn.addEventListener('click', () => {
  activeTab = btn.dataset.tab;
  $$('.tab').forEach(b => b.classList.toggle('active', b === btn));
  $$('.pane').forEach(p => p.classList.toggle('active', p.id === `tab-${activeTab}`));
  loadActiveTab();
}));

setInterval(refreshStatus, 5000);
refreshStatus();
loadCommands();
loadIgnores();
loadJokes();
loadDataChannels();
loadRawTables();
