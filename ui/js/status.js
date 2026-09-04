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

  renderJokeState(s.joke_state || {});
}

function renderJokeState(js) {
  const cells = [
    ['keyword cooldown', `${js.cooldown_seconds ?? '-'}s window`],
    ['last joke fired', js.seconds_since_last_joke === null ? 'never' : `${js.seconds_since_last_joke}s ago`],
    ['keyword cooldown left', js.keyword_cooldown_remaining > 0 ? `${js.keyword_cooldown_remaining}s remaining` : 'open'],
    ['random joke counter', `${js.random_counter ?? 0} / ${js.random_next_at ?? '-'}`],
  ];
  const grid = $('#joke-state-grid');
  grid.replaceChildren();
  for (const [k, v] of cells) {
    const c = el('div', null, 'cell');
    c.append(el('div', k, 'k'), el('div', v, 'v'));
    grid.append(c);
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
  if (activeTab !== 'status') return;
  let body;
  try { body = await api(`/api/logs?lines=${uiCfg.log_buffer_size || 1000}`); } catch (_) { return; }
  logCache = body.entries || [];
  $('#log-count').textContent = `${body.total} buffered`;
  if (full) { renderLogsFull(); return; }
  const fresh = logCache.filter(e => e.seq > logState.lastSeq);
  appendLogLines(fresh);
  if (fresh.length) logState.lastSeq = fresh[fresh.length - 1].seq;
}

$('#log-view').addEventListener('scroll', e => { logState.atBottom = e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 8; });
$('#btn-log-refresh').addEventListener('click', () => pollLogs(true));
$('#log-level').addEventListener('change', e => { logState.minLevel = e.target.value; renderLogsFull(); });
