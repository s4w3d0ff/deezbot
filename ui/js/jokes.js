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

async function loadJokes() {
  let body;
  try { body = await api(`/api/db/table/joke?limit=${uiOpt('joke_list_limit', 500)}`); } catch (_) { return; }
  const rows = body.rows || [];
  // collision check assumes this fetch returned every row; do not shrink joke_list_limit below the table size without rethinking it
  const existingKeywords = new Set(rows.map(r => String(r.keyword ?? '').trim().toLowerCase()));
  $('#joke-count').textContent = `${rows.length} keywords`;
  const tbody = $('#jokes-table tbody');
  tbody.replaceChildren();
  for (const row of rows) {
    const tr = el('tr');
    // poolguy upsert only touches the target key: posting a new keyword inserts it and leaves the old-key row orphaned, so a rename is post-new plus delete-old
    const kwTd = tdInput(row.keyword, async v => {
      if (!v) return;
      const key = v.trim().toLowerCase();
      if (existingKeywords.has(key) && String(row.keyword ?? '').trim().toLowerCase() !== key) {
        toast(`keyword "${v}" already exists`);
        loadJokes();
        return;
      }
      await post('/api/db/table/joke', { ...row, keyword: v });
      if (String(row.keyword) !== v) await del('/api/db/table/joke', { keyword: String(row.keyword) });
      loadJokes();
      refreshStatus();
    });
    const jokeTd = tdInput(row.joke, async v => { if (!v) return; await post('/api/db/table/joke', { ...row, joke: v }); });
    const delTd = el('td');
    const b = el('button', 'del');
    b.addEventListener('click', async () => {
      if (!confirm(`delete joke keyword "${row.keyword}"?`)) return;
      try { await del('/api/db/table/joke', { keyword: String(row.keyword) }); loadJokes(); refreshStatus(); } catch (_) {}
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
