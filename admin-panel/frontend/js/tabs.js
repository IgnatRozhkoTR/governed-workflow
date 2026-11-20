// ═══════════════════════════════════════════════
//  TABS
// ═══════════════════════════════════════════════
var _explorerLoaded = false;
var _initialLoad = true;

document.addEventListener('workspace-reset', function() {
  _explorerLoaded = false;
});

function applyLockSessionFields(stateData) {
  LOCK_DATA.session_id = stateData.session_id || null;
  LOCK_DATA.working_dir = stateData.working_dir || null;
  LOCK_DATA.sessions = stateData.sessions || [];
  LOCK_DATA.source_branch = stateData.source_branch || null;
  LOCK_DATA.project_type = stateData.project_type || null;
}

async function refreshTabData() {
  if (_initialLoad) return;
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var response = await apiGetState(ctx.projectId, ctx.branch);
    var stateData = response.data;
    applyStateData(stateData);
    applyLockSessionFields(stateData);
    EventBus.emit('state:refreshed', stateData);
  } catch(e) { console.warn('Refresh state failed:', e.message); }
  try {
    if (typeof loadDiffRepos === 'function') await loadDiffRepos();
    if (typeof loadDiffBases === 'function') await loadDiffBases();
    var diffData = await apiGetDiff(ctx.projectId, ctx.branch, state.diffSource, null, state.diffRepo, state.diffBase);
    if (diffData && diffData.files) {
      AppState.diff = diffData;
      DIFF_DATA = AppState.diff;
      EventBus.emit('diff:refreshed', diffData);
    }
  } catch(e) { console.warn('Refresh diff failed:', e.message); }
  try {
    var contextData = await apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context');
    if (contextData) {
      AppState.context = contextData;
      CONTEXT_DATA = AppState.context;
      EventBus.emit('context:refreshed', contextData);
    }
  } catch(e) { console.warn('Refresh context failed:', e.message); }
}

// Tabs that were merged into others by the Checkpoint layout. Old links,
// stored "last tab" values and callers keep working through these aliases.
var TAB_ALIASES = { phases: 'overview', scratchpads: 'files' };
var FULL_BLEED_TABS = ['files', 'changes', 'terminal'];
var DEFAULT_TAB = 'overview';
var _lastNonTerminalTabId = null;

function resolveTabId(tabId) {
  if (tabId === 'scratchpads') setFilesView('scratchpads', { activate: false });
  return TAB_ALIASES[tabId] || tabId;
}

function isKnownTab(tabId) {
  return !!(tabId && document.getElementById('panel-' + (TAB_ALIASES[tabId] || tabId)));
}

function getActiveTabId() {
  var active = document.querySelector('.tab-panel.active');
  return active ? active.id.replace(/^panel-/, '') : DEFAULT_TAB;
}

// Where leaving the full-screen terminal returns to.
function getTabBeforeTerminal() {
  return _lastNonTerminalTabId || DEFAULT_TAB;
}

function _syncTabChrome(tabId) {
  document.querySelectorAll('#wsTabs .tab, .bnav button[data-tab]').forEach(function(b) {
    b.classList.toggle('active', b.dataset.tab === tabId);
    b.classList.toggle('on', b.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.toggle('active', p.id === 'panel-' + tabId); });

  var mainEl = document.querySelector('.main');
  if (mainEl) mainEl.classList.toggle('terminal-active', tabId === 'terminal');

  var splitMain = document.getElementById('splitMain');
  if (splitMain) splitMain.classList.toggle('no-padding', FULL_BLEED_TABS.indexOf(tabId) !== -1);

  var activeTabBtn = document.querySelector('#wsTabs .tab.active');
  if (activeTabBtn) activeTabBtn.scrollIntoView({ block: 'nearest', inline: 'center' });

  if (tabId !== 'terminal') _lastNonTerminalTabId = tabId;
  syncTerminalPanelForTab(tabId);
  if (typeof renderGateBar === 'function') renderGateBar();
}

async function switchTab(requestedTabId) {
  var tabId = resolveTabId(requestedTabId);
  if (tabId !== 'terminal' && typeof stopSessionListPolling === 'function') stopSessionListPolling();

  _syncTabChrome(tabId);
  // The dashboard panel encodes its active settings section as a hash
  // suffix ('#dashboard/<section>'); preserve it instead of clobbering it.
  var newHash = '#' + tabId;
  if (tabId === 'dashboard') {
    var currentParts = location.hash.slice(1).split('/');
    if (currentParts[0] === 'dashboard' && currentParts[1]) newHash += '/' + currentParts[1];
  }
  history.replaceState(null, '', newHash);
  _storeLastTab(tabId);

  await refreshTabData();

  _activateTabHooks(tabId);
}

// ─── Files tab: project files / scratchpads switch ──────────────────────
var FILES_VIEW_KEY = 'ui_files_view';

function getFilesView() {
  try { return localStorage.getItem(FILES_VIEW_KEY) === 'scratchpads' ? 'scratchpads' : 'project'; } catch (e) { return 'project'; }
}

function setFilesView(view, options) {
  var resolved = view === 'scratchpads' ? 'scratchpads' : 'project';
  try { localStorage.setItem(FILES_VIEW_KEY, resolved); } catch (e) {}
  _syncFilesViewChrome(resolved);
  if (!options || options.activate !== false) _activateFilesView(resolved);
}

function _syncFilesViewChrome(view) {
  document.querySelectorAll('#filesViewSwitch [data-files-view]').forEach(function(b) {
    b.classList.toggle('on', b.dataset.filesView === view);
  });
  var projectView = document.getElementById('filesProjectView');
  var scratchView = document.getElementById('filesScratchpadsView');
  if (projectView) projectView.hidden = view !== 'project';
  if (scratchView) scratchView.hidden = view !== 'scratchpads';
}

function _activateFilesView(view) {
  if (view === 'scratchpads') {
    if (typeof loadScratchpads === 'function') loadScratchpads();
    return;
  }
  if (!_explorerLoaded && typeof loadExplorerFiles === 'function') {
    _explorerLoaded = true;
    loadExplorerFiles();
  }
}

// ─── Per-workspace "last tab" persistence ───────────────────────────────
function _tabStorageKey(ctx) {
  return 'ui_last_tab:' + ctx.projectId + '/' + ctx.branch;
}

function _storeLastTab(tabId) {
  var ctx = typeof getWorkspaceContext === 'function' ? getWorkspaceContext() : null;
  if (!ctx) return;
  try { localStorage.setItem(_tabStorageKey(ctx), tabId); } catch (e) {}
}

function _loadLastTab(ctx) {
  if (!ctx) return null;
  try { return localStorage.getItem(_tabStorageKey(ctx)); } catch (e) { return null; }
}

// Reads the last settings section stored for this workspace, without
// depending on settings.js (which loads after this file and defines the
// canonical SETTINGS_SECTIONS list). Loose format validation only; the
// section is re-validated against SETTINGS_SECTIONS once settings.js runs.
function _loadLastSettingsSectionRaw(ctx) {
  if (!ctx) return null;
  var stored;
  try { stored = localStorage.getItem('ui_last_settings_section:' + ctx.projectId + '/' + ctx.branch); } catch (e) { return null; }
  return (stored && /^[a-z0-9_-]+$/i.test(stored)) ? stored : null;
}

// Per-tab activation hooks, shared by switchTab (click path) and the
// hash-restore path on page load, so the two can never drift apart.
function _activateTabHooks(tabId) {
  if (tabId === 'dashboard') {
    if (typeof settingsOnActivate === 'function') settingsOnActivate();
  } else if (tabId === 'plan') {
    if (typeof renderPlan === 'function') renderPlan();
    if (typeof renderScope === 'function') renderScope();
    if (typeof renderPhaseActions === 'function') renderPhaseActions();
    if (typeof updatePlanApprovalUI === 'function') updatePlanApprovalUI(LOCK_DATA.plan_status || 'pending');
    if (typeof loadCriteria === 'function') loadCriteria();
  } else if (tabId === 'preplanning') {
    if (typeof renderPreplanning === 'function') renderPreplanning();
  } else if (tabId === 'research') {
    if (typeof renderResearch === 'function') renderResearch();
  } else if (tabId === 'overview') {
    if (typeof renderOverview === 'function') renderOverview();
    if (typeof renderPhaseHistory === 'function') renderPhaseHistory();
    if (typeof renderPhaseActions === 'function') renderPhaseActions();
    if (typeof loadVerificationResults === 'function') loadVerificationResults();
    if (typeof loadCriteria === 'function') loadCriteria();
  } else if (tabId === 'changes') {
    if (typeof renderFileList === 'function') renderFileList();
  } else if (tabId === 'review') {
    if (typeof loadReviewComments === 'function') loadReviewComments();
    if (typeof refreshReviewPipeline === 'function') refreshReviewPipeline(true);
  } else if (tabId === 'reflection') {
    if (typeof loadProposals === 'function') loadProposals();
  } else if (tabId === 'files') {
    var filesView = getFilesView();
    _syncFilesViewChrome(filesView);
    _activateFilesView(filesView);
  } else if (tabId === 'terminal') {
    if (typeof onTerminalTabActivated === 'function') onTerminalTabActivated();
  }
}

document.querySelectorAll('#wsTabs .tab').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

window.addEventListener('hashchange', function() {
  var hashTab = location.hash.slice(1).split('/')[0];
  if (!isKnownTab(hashTab)) return;
  var tabId = resolveTabId(hashTab);
  if (tabId !== hashTab) history.replaceState(null, '', '#' + tabId);
  if (tabId !== getActiveTabId()) switchTab(tabId);
});

// Resolves which panel a given workspace context should show (last tab used
// in that workspace, or Overview on first ever visit) and applies it:
// writes the resolved hash first (so a stale hash from a previously active
// context never leaks into hash-reading code like _currentSettingsSection()),
// then syncs the active classes and .main/splitMain state exactly as
// switchTab() does. Does NOT call _storeLastTab — restoring isn't a user
// choice. Does NOT call _activateTabHooks — callers invoke that themselves,
// since the page-load path needs it deferred to DOMContentLoaded (most tab
// modules load after tabs.js and aren't defined yet at parse time) while a
// SPA workspace switch can call it immediately (all modules are already
// loaded by then).
function applyStoredTabForContext(ctx) {
  var lastTab = _loadLastTab(ctx);
  var tabId = isKnownTab(lastTab) ? resolveTabId(lastTab) : DEFAULT_TAB;

  var newHash = '#' + tabId;
  if (tabId === 'dashboard') {
    newHash += '/' + (_loadLastSettingsSectionRaw(ctx) || 'task');
  }
  history.replaceState(null, '', newHash);
  _syncTabChrome(tabId);
  return tabId;
}

// Restore tab on load: sync the active classes immediately (no full
// refreshTabData(), since state hasn't loaded yet), then run the same
// per-tab activation hooks switchTab() would run for a click. The hooks
// are deferred to DOMContentLoaded because most tab modules (plan.js,
// file-explorer.js, etc.) load AFTER tabs.js and aren't defined yet at
// parse time of this IIFE.
//
// Resolution order: (a) a URL hash naming a valid panel always wins; (b)
// else the last tab used in this workspace, if any; (c) else — first ever
// visit to this workspace — Overview. With no workspace context
// (project-selector view) and no hash, nothing is restored: the
// statically-active panel in the HTML stands.
(function() {
  var ctx = typeof getWorkspaceContext === 'function' ? getWorkspaceContext() : null;
  var hashTab = location.hash.slice(1).split('/')[0];

  var tabId;
  if (isKnownTab(hashTab)) {
    tabId = resolveTabId(hashTab);
    if (tabId !== hashTab) history.replaceState(null, '', '#' + tabId);
    _syncTabChrome(tabId);
  } else {
    if (!isKnownTab(_loadLastTab(ctx)) && !ctx) return; // no hash, no workspace: keep the static default panel
    tabId = applyStoredTabForContext(ctx);
  }

  document.addEventListener('DOMContentLoaded', function() {
    _activateTabHooks(tabId);
  });
})();
