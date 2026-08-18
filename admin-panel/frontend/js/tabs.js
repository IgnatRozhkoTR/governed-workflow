// ═══════════════════════════════════════════════
//  TABS
// ═══════════════════════════════════════════════
var _explorerLoaded = false;
var _initialLoad = true;

document.addEventListener('workspace-reset', function() {
  _explorerLoaded = false;
});

async function refreshTabData() {
  if (_initialLoad) return;
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var response = await apiGetState(ctx.projectId, ctx.branch);
    var stateData = response.data;
    applyStateData(stateData);
    LOCK_DATA.session_id = stateData.session_id || null;
    LOCK_DATA.working_dir = stateData.working_dir || null;
    LOCK_DATA.sessions = stateData.sessions || [];
    EventBus.emit('state:refreshed', stateData);
  } catch(e) { console.warn('Refresh state failed:', e.message); }
  try {
    if (typeof loadDiffRepos === 'function') await loadDiffRepos();
    if (typeof loadDiffBases === 'function') await loadDiffBases();
    var diffData = await apiGetDiff(ctx.projectId, ctx.branch, state.diffSource, null, state.diffRepo, state.diffBase);
    if (diffData && diffData.files) { AppState.diff = diffData; DIFF_DATA = AppState.diff; }
  } catch(e) { console.warn('Refresh diff failed:', e.message); }
  try {
    var contextData = await apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context');
    if (contextData) { AppState.context = contextData; CONTEXT_DATA = AppState.context; }
  } catch(e) { console.warn('Refresh context failed:', e.message); }
}

async function switchTab(tabId) {
  var mainEl = document.querySelector('.main');
  if (mainEl) {
    if (tabId === 'terminal') {
      mainEl.classList.add('terminal-active');
    } else {
      mainEl.classList.remove('terminal-active');
      if (typeof stopSessionListPolling === 'function') stopSessionListPolling();
    }
  }

  var splitMain = document.getElementById('splitMain');
  if (splitMain) {
    if (tabId === 'files' || tabId === 'changes' || tabId === 'terminal') {
      splitMain.classList.add('no-padding');
    } else {
      splitMain.classList.remove('no-padding');
    }
  }

  // Deactivate all top tab buttons
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
  // Deactivate all sidebar buttons (skip buttons without data-tab, e.g. split terminal)
  document.querySelectorAll('.sidebar-btn[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
  // Show the correct panel
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tabId));
  // The dashboard panel encodes its active settings section as a hash
  // suffix ('#dashboard/<section>'); preserve it instead of clobbering it.
  var newHash = '#' + tabId;
  if (tabId === 'dashboard') {
    var currentParts = location.hash.slice(1).split('/');
    if (currentParts[0] === 'dashboard' && currentParts[1]) newHash += '/' + currentParts[1];
  }
  history.replaceState(null, '', newHash);

  await refreshTabData();

  _activateTabHooks(tabId);
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
  } else if (tabId === 'phases') {
    if (typeof renderPhaseBar === 'function') renderPhaseBar('phaseBarControl', 'phaseLabelsControl');
    if (typeof renderPhaseHistory === 'function') renderPhaseHistory();
    if (typeof renderPhaseActions === 'function') renderPhaseActions();
    if (typeof renderApprovalStatus === 'function') renderApprovalStatus();
    if (typeof loadVerificationResults === 'function') loadVerificationResults();
  } else if (tabId === 'changes') {
    if (typeof renderFileList === 'function') renderFileList();
  } else if (tabId === 'review') {
    if (typeof loadReviewComments === 'function') loadReviewComments();
  } else if (tabId === 'reflection') {
    if (typeof loadProposals === 'function') loadProposals();
  } else if (tabId === 'files') {
    if (!_explorerLoaded && typeof loadExplorerFiles === 'function') {
      _explorerLoaded = true;
      loadExplorerFiles();
    }
  } else if (tabId === 'terminal') {
    if (typeof onTerminalTabActivated === 'function') onTerminalTabActivated();
  }
}

// Top tab bar buttons
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// Sidebar buttons (skip buttons without data-tab, e.g. split terminal)
document.querySelectorAll('.sidebar-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// Restore tab from URL hash on load: sync the active classes immediately
// (no full refreshTabData(), since state hasn't loaded yet), then run the
// same per-tab activation hooks switchTab() would run for a click. The
// hooks are deferred to DOMContentLoaded because most tab modules
// (plan.js, file-explorer.js, etc.) load AFTER tabs.js and aren't defined
// yet at parse time of this IIFE.
(function() {
  var hash = location.hash.slice(1).split('/')[0];
  if (hash && document.getElementById('panel-' + hash)) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === hash));
    document.querySelectorAll('.sidebar-btn[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === hash));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + hash));

    var mainEl = document.querySelector('.main');
    if (mainEl && hash === 'terminal') mainEl.classList.add('terminal-active');

    var splitMain = document.getElementById('splitMain');
    if (splitMain && (hash === 'files' || hash === 'changes' || hash === 'terminal')) {
      splitMain.classList.add('no-padding');
    }

    document.addEventListener('DOMContentLoaded', function() {
      _activateTabHooks(hash);
    });
  }
})();
