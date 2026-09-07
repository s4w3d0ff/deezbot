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
    );
    const jemoteTd = tdInput(c.jemote, async v => { if (!v) return; await post('/api/db/table/channels', { user_id: String(c.user_id), jemote: v }); refreshChannels(); });
    tr.append(jemoteTd);
    tr.append(
      el('td', c.is_live ? String(c.viewers) : '-', c.is_live ? '' : 'muted'),
    );
    const titleTd = el('td', c.title || '-', (c.is_live && c.title) ? '' : 'muted');
    if (c.title) titleTd.title = c.title;
    tr.append(titleTd);
    const actTd = el('td');
    const b = el('button', 'remove');
    b.title = `stop watching channel ${c.login || c.user_id}`;
    b.addEventListener('click', async () => {
      if (!confirm(`stop watching channel ${c.login || c.user_id}?`)) return;
      try { await del('/api/db/table/channels', { user_id: String(c.user_id) }); refreshChannels(); refreshStatus(); } catch (_) {}
    });
    actTd.append(b);
    tr.append(actTd);
    tbody.append(tr);
  }
}

$('#add-channel-form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target;
  const login = form.login.value.trim();
  if (!login) return toast('username required');
  try {
    await post('/api/channels', { login, jemote: form.jemote.value.trim() || undefined });
    form.reset();
    refreshChannels();
    refreshStatus();
  } catch (_) {}
});
