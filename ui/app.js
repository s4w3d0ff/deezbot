const $ = (sel) => document.querySelector(sel);

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

let lastStatus = {};
async function refreshStatus() {
  let s;
  try { s = await api('/api/status'); } catch (_) { return; }
  lastStatus = s;
  $('#ws-dot').className = `dot ${s.ws_connected ? 'on' : 'off'}`;

  const grid = $('#status-grid');
  grid.replaceChildren();
  const cells = [
    ['bot', s.authenticated ? 'authenticated' : 'not authenticated'],
    ['user_id', s.user_id || '-'],
    ['token expiry', tokenLabel(s.token_expires_time)],
    ['ws session', s.ws_connected ? 'connected' : 'disconnected'],
    ['channels', Object.keys(s.channels).length],
  ];
  for (const [k, v] of cells) {
    const c = el('div');
    c.append(el('div', k, 'k'), el('div', v, 'v'));
    grid.append(c);
  }

  const tbody = $('#channels-table tbody');
  tbody.replaceChildren();
  for (const [uid, row] of Object.entries(s.channels)) {
    const tr = el('tr');
    tr.append(el('td', uid), el('td', row.jemote));
    tbody.append(tr);
  }
}

function tokenLabel(expiresTime) {
  if (!expiresTime) return '-';
  const secs = Math.floor(expiresTime - Date.now() / 1000);
  if (secs <= 0) return 'expired';
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
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

let dbState = { tables: [], current: null, writable: false };

async function refreshTableList() {
  const r = await api('/api/db/tables');
  dbState.tables = r.tables;
  const ul = $('#table-list');
  ul.replaceChildren();
  for (const t of dbState.tables) {
    const li = el('li', `${t.name}${t.writable ? '' : ' ro'}`);
    if (dbState.current === t.name) li.classList.add('active');
    const cnt = el('span', String(t.row_count), 'cnt');
    li.append(cnt);
    li.addEventListener('click', () => selectTable(t));
    ul.append(li);
  }
}

async function selectTable(t) {
  dbState.current = t.name;
  dbState.writable = t.writable;
  $('#db-title').textContent = `${t.name}${t.writable ? '' : ' (read-only)'}`;
  for (const li of $('#table-list').children) li.classList.toggle('active', li.textContent.includes(t.name));
  await loadRows();
}

async function loadRows() {
  const t = dbState.tables.find(x => x.name === dbState.current);
  if (!t) return;
  const r = await api(`/api/db/table/${encodeURIComponent(dbState.current)}?limit=200`);
  const rows = r.rows || [];
  const cols = collectCols(rows);
  const table = $('#rows-table');
  table.replaceChildren();
  if (!cols.length) {
    table.append(el('tr').append(el('td', 'no rows')));
    $('#btn-new-row').hidden = true;
    return;
  }
  const thead = el('thead');
  const htr = el('tr');
  for (const c of cols) htr.append(el('th', c));
  if (dbState.writable) { htr.append(el('th')); $('#btn-new-row').hidden = false; } else $('#btn-new-row').hidden = true;
  thead.append(htr);
  const tbody = el('tbody');
  rows.forEach((row, i) => {
    const tr = el('tr');
    for (const c of cols) {
      const td = el('td', row[c] ?? '');
      if (dbState.writable) makeEditable(td, row, c);
      tr.append(td);
    }
    if (dbState.writable) {
      const tdBtn = el('td');
      const b = el('button', 'del');
      b.addEventListener('click', () => deleteRow(row, cols[0]));
      tdBtn.append(b);
      tr.append(tdBtn);
    }
    tbody.append(tr);
  });
  table.append(thead, tbody);
}

function collectCols(rows) {
  const seen = new Set();
  for (const row of rows) for (const k of Object.keys(row)) if (!seen.has(k)) { seen.add(k); }
  return [...seen];
}

function makeEditable(td, row, col) {
  td.addEventListener('click', () => {
    if (td.querySelector('input')) return;
    const input = el('input');
    input.className = 'cell-input';
    input.value = row[col] ?? '';
    td.replaceChildren(input);
    input.focus();
    input.select();
    const save = async () => {
      const v = input.value;
      if (v !== String(row[col] ?? '')) {
        row[col] = v;
        try { await post(`/api/db/table/${encodeURIComponent(dbState.current)}`, row); await loadRows(); } catch (_) {}
      } else {
        td.textContent = row[col] ?? '';
      }
    };
    input.addEventListener('blur', save, { once: true });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') input.blur();
      if (e.key === 'Escape') { input.removeEventListener('blur', save); td.textContent = row[col] ?? ''; }
    });
  });
}

async function deleteRow(row, pkCol) {
  const val = String(row[pkCol] ?? '');
  if (!confirm(`delete this ${dbState.current} row?\n${pkCol} = ${val}`)) return;
  try {
    await del(`/api/db/table/${encodeURIComponent(dbState.current)}`, { where: `${pkCol} = ?`, params: [val] });
    await loadRows();
    refreshTableList().catch(() => {});
  } catch (_) {}
}

$('#btn-new-row').addEventListener('click', () => {
  const form = $('#new-row-form');
  if (!form.classList.contains('hidden')) { form.classList.add('hidden'); return; }
  form.replaceChildren();
  api(`/api/db/table/${encodeURIComponent(dbState.current)}?limit=1`).then(r => {
    const cols = collectCols(r.rows || []);
    if (!cols.length) return toast('table has no rows, add columns via chat commands first');
    for (const c of cols) {
      const label = el('label', c);
      const input = el('input');
      input.name = c;
      label.append(input);
      form.append(label);
    }
    form.classList.remove('hidden');
  }).catch(() => {});
});

$('#new-row-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = {};
  for (const input of $('#new-row-form').querySelectorAll('input')) data[input.name] = input.value;
  try {
    await post(`/api/db/table/${encodeURIComponent(dbState.current)}`, data);
    $('#new-row-form').classList.add('hidden');
    await loadRows();
    refreshTableList().catch(() => {});
  } catch (_) {}
});

document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b === btn));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === `tab-${btn.dataset.tab}`));
}));

setInterval(refreshStatus, 5000);
refreshStatus();
refreshTableList().catch(() => {});
