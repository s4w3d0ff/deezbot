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
        try { await del('/api/db/table/ignore', { user_id: String(u.user_id) }); loadIgnores(); } catch (_) {}
      });
      actTd.append(b);
    }
    tr.append(actTd);
    tbody.append(tr);
  }
}

$('#add-ignore-form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target;
  const login = form.login.value.trim();
  if (!login) return toast('username required');
  try {
    await post('/api/ignores', { login });
    form.reset();
    loadIgnores();
    refreshStatus();
  } catch (_) {}
});
