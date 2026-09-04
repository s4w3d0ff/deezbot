let activeTab = 'status';
function loadActiveTab() {
  if (activeTab === 'channels') {
    refreshChannels();
  } else if (activeTab === 'ignores') {
    loadIgnores();
  } else if (activeTab === 'jokes') {
    loadJokes();
  } else if (activeTab === 'status') {
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
  setInterval(refreshStatus, uiOpt('status_poll_ms', 5000));
  setInterval(() => pollLogs(false), uiOpt('log_poll_ms', 2000));
  refreshStatus();
  loadCommands();
  loadIgnores();
  loadJokes();
  pollLogs(true);
  loadRawTables();
}

boot();
