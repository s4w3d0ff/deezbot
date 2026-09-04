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

let uiCfg = {};
function loadConfig() {
  return api('/api/config').then(body => { if (body && body.status) uiCfg = body; }).catch(() => {});
}
function uiOpt(key, fallback) {
  const v = (uiCfg.ui || {})[key];
  return Number.isFinite(v) && v > 0 ? v : fallback;
}

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
