let activeTab = 'status';
function loadActiveTab() {
  if (activeTab === 'channels') {
    refreshChannels();
  } else if (activeTab === 'ignores') {
    loadIgnores();
  } else if (activeTab === 'jokes') {
    loadJokes();
  } else if (activeTab === 'status') {
    refreshStatus();
    pollLogs(true);
    loadRawTables();
  }
}

$$('.tab').forEach(btn => btn.addEventListener('click', () => {
  activeTab = btn.dataset.tab;
  $$('.tab').forEach(b => b.classList.toggle('active', b === btn));
  $$('.pane').forEach(p => p.classList.toggle('active', p.id === `tab-${activeTab}`));
  loadActiveTab();
}));

async function boot() {
  await loadConfig();
  // periodic fetches skip work off-tab or on a hidden window; manual refreshStatus and pollLogs(true) callers are exempt by design
  setInterval(() => { if (statusPollAllowed()) refreshStatus(); }, uiOpt('status_poll_ms', 5000));
  setInterval(() => { if (statusPollAllowed()) pollLogs(false); }, uiOpt('log_poll_ms', 2000));
  refreshStatus();
  loadCommands();
  loadIgnores();
  loadJokes();
  pollLogs(true);
  loadRawTables();
}

boot();
