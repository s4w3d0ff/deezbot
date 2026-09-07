let rawState = { current: null, writable: false, pkCol: null };

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
  rawState.pkCol = null;
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
        rawState.pkCol = cols[0];
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
  try { body = await api(`/api/db/table/${encodeURIComponent(rawState.current)}?limit=${uiOpt('page_size', 200)}`); } catch (_) { return; }
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
    await del(`/api/db/table/${encodeURIComponent(rawState.current)}`, { [pkCol]: val });
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
  let overwrote = false;
  if (rawState.pkCol) {
    const pkVal = String(data[rawState.pkCol] ?? '').trim();
    let body;
    try { body = await api(`/api/db/table/${encodeURIComponent(rawState.current)}?limit=${uiOpt('page_size', 200)}`); } catch (_) {}
    if (body && body.rows.some(r => String(r[rawState.pkCol] ?? '').trim() === pkVal)) {
      overwrote = true;
      if (!confirm(`row with ${rawState.pkCol}="${pkVal}" already exists. Submitting will overwrite that row. Continue?`)) return;
    }
  }
  try {
    await post(`/api/db/table/${encodeURIComponent(rawState.current)}`, data);
    $('#new-row-form').classList.add('hidden');
    loadRawRows();
    loadRawTables();
    if (overwrote) toast('overwrote existing row');
  } catch (_) {}
});
