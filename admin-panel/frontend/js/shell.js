// ═══════════════════════════════════════════════
//  CHECKPOINT APP SHELL
//  Workspace header, phase track, gate bar, phone
//  footer, tab counters and the Overview cards.
// ═══════════════════════════════════════════════

var PHASE_STATIONS = [
  { id: 'prepare', labelKey: 'station.prepare', matches: function(p) { return p === '0' || /^1\./.test(p); } },
  { id: 'plan', labelKey: 'station.plan', matches: function(p) { return /^2(\.|$)/.test(p); } },
  { id: 'build', labelKey: 'station.build', matches: function(p) { return /^3(\.|$)/.test(p); } },
  { id: 'review', labelKey: 'station.review', matches: function(p) { return /^4(\.|$)/.test(p); } },
  { id: 'reflect', labelKey: 'station.reflect', matches: function(p) { return /^5(\.|$)/.test(p); } },
  { id: 'done', labelKey: 'station.done', matches: function(p) { return p === '6'; } }
];

var EXECUTION_STEP_KEYS = ['phase.implementation', 'phase.validation', 'phase.fixes', 'phase.codeReview', 'phase.commit'];
var PHONE_LAYOUT_QUERY = window.matchMedia('(max-width: 600px)');

function stationIndexOf(phase) {
  for (var i = 0; i < PHASE_STATIONS.length; i++) {
    if (PHASE_STATIONS[i].matches(phase)) return i;
  }
  return 0;
}

function stationLabel(phase) {
  return t(PHASE_STATIONS[stationIndexOf(phase)].labelKey);
}

function renderShell() {
  renderWorkspaceHeader();
  renderPhaseTrack();
  renderPhaseSubChips();
  renderPhaseSteps();
  renderGateBar();
  renderTabCounts();
  renderOverview();
  renderPhaseActions();
  renderSidebar();
}

// ═══════════════════════════════════════════════
//  WORKSPACE HEADER
// ═══════════════════════════════════════════════

function renderWorkspaceHeader() {
  var branch = LOCK_DATA.branch || '';
  var context = AppState.context || {};
  var ticketTitle = [context.ticket_id, context.ticket_name].filter(Boolean).join(' ');
  var title = context.ticket_name ? ticketTitle : branch;

  _setText('wsTitle', title);
  var branchEl = document.getElementById('branchName');
  if (branchEl) {
    branchEl.textContent = branch;
    branchEl.hidden = title === branch;
  }
  var metaParts = [];
  if (LOCK_DATA.source_branch) metaParts.push(t('shell.fromBranch', {branch: LOCK_DATA.source_branch}));
  if (/\/worktrees\//.test(LOCK_DATA.working_dir || '')) metaParts.push(t('shell.worktree'));
  var meta = metaParts.join(' · ');
  _setText('wsBranchMeta', meta && title !== branch ? ' · ' + meta : meta);
}

function _setText(id, text) {
  var el = document.getElementById(id);
  if (el) el.textContent = text;
}

// ═══════════════════════════════════════════════
//  PHASE TRACK, SUB-PHASE CHIPS, PHONE STEPPER
// ═══════════════════════════════════════════════

function _stationState(index, currentIndex, phase, gate) {
  if (index < currentIndex || phase === '6') return 'done';
  if (index > currentIndex) return 'todo';
  return gate ? 'now' : 'run';
}

function renderPhaseTrack() {
  var track = document.getElementById('phaseTrack');
  if (!track) return;
  var phase = LOCK_DATA.phase || '0';
  var currentIndex = stationIndexOf(phase);
  var gate = getPendingGate();
  var lastIndex = PHASE_STATIONS.length - 1;

  track.innerHTML = PHASE_STATIONS.map(function(station, i) {
    var stateClass = _stationState(i, currentIndex, phase, gate);
    var line = i < lastIndex ? '<span class="l"></span>' : '';
    return '<div class="st ' + (stateClass === 'done' ? '' : stateClass) + '">' +
      '<div class="r"><span class="n"></span>' + line + '</div>' +
      '<span class="t">' + escapeHtml(t(station.labelKey)) + '</span></div>';
  }).join('');
}

function renderPhaseSubChips() {
  var container = document.getElementById('phaseSubChips');
  if (!container) return;
  var chips = _subChipsForCurrentStation();
  container.innerHTML = chips.map(function(chip) {
    return '<span class="s ' + chip.state + '" title="' + escapeHtml(chip.title || chip.label) + '">' + escapeHtml(chip.label) + '</span>';
  }).join('');
  container.hidden = chips.length === 0;
}

function _subChipsForCurrentStation() {
  var phase = LOCK_DATA.phase || '0';
  var station = PHASE_STATIONS[stationIndexOf(phase)];
  if (station.id === 'done') return [];
  if (station.id === 'build') return _executionChips(phase);

  var sequence = getPhaseSequenceForBar();
  var currentPos = sequence.indexOf(phase);
  return sequence.filter(station.matches).map(function(p) {
    var state = _chipState(sequence.indexOf(p), currentPos);
    return { label: _chipLabel(state, getPhaseName(p)), state: state };
  });
}

function _chipState(position, currentPos) {
  if (position < currentPos) return 'done';
  if (position > currentPos) return '';
  return getPendingGate() ? 'now' : 'run';
}

// The chip the agent is holding at reads as the decision being asked for.
function _chipLabel(state, defaultLabel) {
  var gate = state === 'now' ? getPendingGate() : null;
  return gate ? t(gate.config.nameKey) : defaultLabel;
}

function _executionChips(phase) {
  var execution = (PLAN_DATA && PLAN_DATA.execution) || [];
  var match = phase.match(/^3\.(\d+)\.(\d+)$/);
  var currentSub = match ? Number(match[1]) : 0;
  var chips = [];
  execution.forEach(function(item) {
    var n = Number(item.id.split('.').pop());
    var label = item.id + ' ' + (item.name || '');
    chips.push({ label: _shortSubPhaseLabel(item), title: label, state: n < currentSub ? 'done' : '' });
    if (n === currentSub) chips = chips.concat(_executionStepChips(item.id, phase));
  });
  return chips;
}

function _shortSubPhaseLabel(item) {
  var name = item.name || '';
  var firstWords = name.split(/\s+/).slice(0, 2).join(' ');
  return item.id + (firstWords ? ' ' + firstWords : '');
}

function _executionStepChips(subPhaseId, phase) {
  var sequence = getPhaseSequenceForBar();
  var currentPos = sequence.indexOf(phase);
  return sequence.filter(function(p) { return p.indexOf(subPhaseId + '.') === 0; }).map(function(p) {
    var stepKey = EXECUTION_STEP_KEYS[Number(p.split('.').pop())];
    var state = _chipState(sequence.indexOf(p), currentPos);
    return { label: _chipLabel(state, stepKey ? t(stepKey) : p), title: p, state: state };
  });
}

function renderPhaseSteps() {
  var container = document.getElementById('phaseSteps');
  if (!container) return;
  var items = _phoneStepItems();
  container.innerHTML = items.map(function(item, i) {
    var line = i < items.length - 1 ? '<span class="l"></span>' : '';
    var sub = item.sub ? '<div class="sm dim">' + escapeHtml(item.sub) + '</div>' : '';
    return '<div class="sp ' + item.state + '"><div class="rail"><span class="n"></span>' + line + '</div>' +
      '<div class="c"><div class="sp-title">' + escapeHtml(item.title) + '</div>' + sub + '</div></div>';
  }).join('');
}

// Done stations collapse into one line so the stepper stays short on phones.
function _phoneStepItems() {
  var phase = LOCK_DATA.phase || '0';
  var currentIndex = stationIndexOf(phase);
  var gate = getPendingGate();
  var doneLabels = [];
  var items = [];
  PHASE_STATIONS.forEach(function(station, i) {
    var stateClass = _stationState(i, currentIndex, phase, gate);
    if (stateClass === 'done') { doneLabels.push(t(station.labelKey)); return; }
    var isCurrent = i === currentIndex;
    items.push({
      state: stateClass,
      title: isCurrent ? _currentStationTitle(station, phase) : t(station.labelKey),
      sub: isCurrent ? _currentStationDetail(phase, gate) : ''
    });
  });
  if (doneLabels.length) items.unshift({ state: '', title: doneLabels.join(' · '), sub: '' });
  return items;
}

function _currentStationTitle(station, phase) {
  var execution = (PLAN_DATA && PLAN_DATA.execution) || [];
  var match = phase.match(/^3\.(\d+)\./);
  if (station.id !== 'build' || !match || !execution.length) return t(station.labelKey);
  return t(station.labelKey) + ' · ' + t('steps.subPhaseOf', {id: '3.' + match[1], last: execution[execution.length - 1].id});
}

function _currentStationDetail(phase, gate) {
  if (gate) return t('steps.waitingAt', {name: t(gate.config.nameKey)});
  return phase + ' · ' + getPhaseName(phase);
}

// ═══════════════════════════════════════════════
//  GATE BAR AND PHONE DECISION FOOTER
// ═══════════════════════════════════════════════

function renderGateBar() {
  var bar = document.getElementById('gateBar');
  if (!bar) return;
  var gate = getPendingGate();
  var activeTab = typeof getActiveTabId === 'function' ? getActiveTabId() : 'overview';
  var isDecidingView = activeTab === 'overview' || activeTab === 'terminal' || (gate && activeTab === gate.decidingTab);
  bar.hidden = !gate || isDecidingView;
  if (!bar.hidden) bar.innerHTML = _gateBarHtml(gate);
  renderPhoneGateFoot(gate, activeTab);
  if (typeof renderTerminalGateStrip === 'function') renderTerminalGateStrip(gate);
}

function _gateBarHtml(gate) {
  var label = t('gate.bar', {phase: gate.phase, name: t(gate.config.nameKey), wait: formatWaitDuration(gate.since)});
  return '<span class="dot gate"></span><span class="grow brk">' + escapeHtml(label.replace(/ · $/, '')) + '</span>' +
    '<span class="hs gatebar__actions">' + _gateDecisionButtons(gate, 'xs') + '</span>';
}

function _gateDecisionButtons(gate, size) {
  if (gate.decidingTab !== 'overview') {
    return '<button class="btn pri ' + size + '" onclick="switchTab(\'' + gate.decidingTab + '\')">' + escapeHtml(t('gate.openGate')) + '</button>';
  }
  return '<button class="btn onGate ' + size + '" onclick="requestGateChanges()">' + escapeHtml(t(gate.config.rejectKey)) + '</button>' +
    '<button class="btn pri ' + size + '" onclick="handleApprove()">' + escapeHtml(t(gate.config.approveKey)) + '</button>';
}

var PHONE_DECISION_CALLS = {
  plan: {reject: "setPlanStatus('rejected')", approve: "setPlanStatus('approved')"},
  other: {reject: 'requestGateChanges()', approve: 'handleApprove()'}
};

function renderPhoneGateFoot(gate, activeTab) {
  var foot = document.getElementById('phoneGateFoot');
  if (!foot) return;
  var isDecidingView = !!gate && activeTab === gate.decidingTab;
  foot.hidden = !gate || (activeTab !== 'overview' && !isDecidingView);
  if (foot.hidden) return;
  if (gate.decidingTab !== 'overview' && !isDecidingView) {
    foot.innerHTML = '<span class="grow"></span><button class="btn pri lg" onclick="switchTab(\'' + gate.decidingTab + '\')">' + escapeHtml(t('gate.openGate')) + '</button>';
    return;
  }
  var calls = PHONE_DECISION_CALLS[gate.kind === 'plan' ? 'plan' : 'other'];
  var rejectLabel = isDecidingView && gate.decidingTab !== 'overview' ? t(gate.config.rejectKey) : t('gate.reject');
  var approveLabel = gate.kind === 'plan' ? t(gate.config.approveKey) : t('buttons.approve');
  foot.innerHTML = '<button class="btn lg" onclick="' + calls.reject + '">' + escapeHtml(rejectLabel) + '</button>' +
    '<span class="grow"></span><button class="btn pri lg" onclick="' + calls.approve + '">' + escapeHtml(approveLabel) + '</button>';
}

function requestGateChanges() {
  if (PHONE_LAYOUT_QUERY.matches) {
    openGateFeedbackSheet();
    return;
  }
  switchTab('overview').then(function() {
    var input = document.getElementById('rejectFeedbackInput');
    if (input) input.focus();
  });
}

// On phones the request-changes form is a bottom sheet (phone 05); it writes
// into the gate card's feedback field so handleRejectWithInput stays the
// single submit path.
function openGateFeedbackSheet() {
  var scrim = document.createElement('div');
  scrim.className = 'dlg-scrim sheet-scrim';
  scrim.innerHTML = '<div class="sheet" role="dialog" aria-modal="true">' +
    '<span class="grab"></span>' +
    '<h2>' + escapeHtml(t('gate.requestChangesTitle')) + '</h2>' +
    '<label class="lbl">' + escapeHtml(t('gate.feedbackLabel')) +
      '<textarea class="ta" id="gateSheetFeedback" placeholder="' + escapeHtml(t('gate.feedbackPlaceholder')) + '"></textarea></label>' +
    '<div class="hs"><button class="btn lg" data-sheet-close>' + escapeHtml(t('buttons.close')) + '</button><span class="grow"></span>' +
      '<button class="btn pri lg" data-sheet-submit>' + escapeHtml(t('gate.sendFeedback')) + '</button></div>' +
  '</div>';
  var close = function() { scrim.remove(); };
  scrim.addEventListener('click', function(e) { if (e.target === scrim || e.target.closest('[data-sheet-close]')) close(); });
  scrim.querySelector('[data-sheet-submit]').addEventListener('click', function() {
    var target = document.getElementById('rejectFeedbackInput');
    if (target) target.value = scrim.querySelector('#gateSheetFeedback').value;
    close();
    handleRejectWithInput();
  });
  document.body.appendChild(scrim);
  scrim.querySelector('#gateSheetFeedback').focus();
}

// ═══════════════════════════════════════════════
//  TAB COUNTERS
// ═══════════════════════════════════════════════

function renderTabCounts() {
  var fileCount = (DIFF_DATA.files || []).length;
  ['changesCount', 'phoneChangesCount'].forEach(function(id) { _setCounter(id, fileCount); });
  _setCounter('overviewReviewCount', countOpenReviewIssues());
}

function _setCounter(id, value) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
  el.style.display = value > 0 ? 'inline-flex' : 'none';
}

function countOpenReviewIssues() {
  if (typeof getReviewComments !== 'function') return 0;
  return getReviewComments().filter(function(c) { return !c.parent_id && !c.resolved; }).length;
}

// ═══════════════════════════════════════════════
//  OVERVIEW CARDS
// ═══════════════════════════════════════════════
var OVERVIEW_MAX_FILES = 12;

function renderOverview() {
  renderOverviewChanges();
  renderOverviewSummary();
  renderOverviewTasks();
  renderOpenItems();
}

function renderOverviewChanges() {
  var list = document.getElementById('ovChangesList');
  if (!list) return;
  var files = DIFF_DATA.files || [];
  var inBuild = /^3\./.test(LOCK_DATA.phase || '');
  _setText('ovChangesTitle', t(inBuild ? 'overview.changesInCommit' : 'overview.changes'));
  _setText('ovChangesMeta', files.length ? tn('overview.filesCount', files.length) : '');

  if (!files.length) {
    list.innerHTML = '<div class="empty">' + escapeHtml(t('overview.noChanges')) + '</div>';
    return;
  }
  var rows = files.slice(0, OVERVIEW_MAX_FILES).map(_overviewFileRow);
  if (files.length > OVERVIEW_MAX_FILES) {
    rows.push('<div class="row ov-file"><span class="sm dim">' + escapeHtml(t('overview.moreFiles', {n: files.length - OVERVIEW_MAX_FILES})) + '</span></div>');
  }
  list.innerHTML = rows.join('');
}

function renderOverviewSummary() {
  var files = DIFF_DATA.files || [];
  var totals = summarizeDiffFiles(files);
  var inBuild = /^3\./.test(LOCK_DATA.phase || '');
  _setText('ovSumChangesTitle', t(inBuild ? 'overview.changesInCommit' : 'overview.changes'));
  _setText('ovSumChangesMeta', files.length
    ? tn('overview.filesCount', files.length) + ' · +' + totals.additions + ' -' + totals.deletions
    : t('overview.noChanges'));
  renderOverviewVerificationSummary();
}

function renderOverviewVerificationSummary() {
  var pill = document.getElementById('ovSumVerificationPill');
  if (!pill) return;
  var run = typeof VERIFICATION_RESULTS !== 'undefined' ? VERIFICATION_RESULTS : null;
  if (!run || !run.steps) {
    pill.style.display = 'none';
    _setText('ovSumVerificationMeta', t('verification.noRuns'));
    return;
  }
  var counts = {};
  run.steps.forEach(function(step) { counts[step.status] = (counts[step.status] || 0) + 1; });
  _setText('ovSumVerificationMeta', Object.keys(counts).map(function(status) {
    return counts[status] + ' ' + t('verification.status.' + status);
  }).join(' · '));
  pill.style.display = '';
  pill.className = 'pill ' + (VERIFICATION_STEP_PILLS[run.status] || '');
  pill.textContent = t('verification.status.' + run.status);
}

function toggleOverviewVerification() {
  var card = document.getElementById('ovVerificationCard');
  var row = document.getElementById('ovSumVerificationRow');
  var isOpen = card.classList.toggle('open');
  row.setAttribute('aria-expanded', isOpen);
  if (isOpen) card.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

function _overviewFileRow(file) {
  return '<div class="row ov-file">' +
    '<span class="mono grow brk">' + escapeHtml(file.path) + '</span>' +
    '<span class="mono ov-add">+' + (file.additions || 0) + '</span>' +
    '<span class="mono ov-del">-' + (file.deletions || 0) + '</span></div>';
}

function renderOverviewTasks() {
  var card = document.getElementById('ovTasksCard');
  var list = document.getElementById('ovTasksList');
  if (!card || !list) return;
  var match = (LOCK_DATA.phase || '').match(/^3\.(\d+)\./);
  var subPhase = match && ((PLAN_DATA && PLAN_DATA.execution) || []).find(function(e) { return e.id === '3.' + match[1]; });
  var tasks = (subPhase && subPhase.tasks) || [];
  card.hidden = !tasks.length;
  if (!tasks.length) return;

  var doneCount = tasks.filter(function(task) { return task.status === 'done'; }).length;
  _setText('ovTasksTitle', t('overview.subPhase', {id: subPhase.id}));
  _setText('ovTasksMeta', t('overview.tasksDone', {done: doneCount, total: tasks.length}));
  list.innerHTML = tasks.map(function(task) {
    var stateClass = task.status === 'done' ? 'done' : (task.status === 'in_progress' ? 'run' : '');
    var mark = task.status === 'done' ? cpIcon('check', 12) : '';
    return '<div class="task ' + stateClass + '"><span class="bx">' + mark + '</span><span class="grow brk">' + escapeHtml(task.title || '') + '</span></div>';
  }).join('');
}

function renderOpenItems() {
  var container = document.getElementById('ovOpenItems');
  if (!container) return;
  var reviewOpen = countOpenReviewIssues();
  var commentsOpen = _countOpenComments();
  container.innerHTML = [
    _kvRow(t('overview.plan'), _planStatusPill()),
    _kvRow(t('overview.criteria'), escapeHtml(_criteriaSummary())),
    _kvRow(t('overview.reviewIssues'), reviewOpen ? '<span class="pill warn">' + escapeHtml(t('overview.openCount', {n: reviewOpen})) + '</span>' : escapeHtml(t('overview.none'))),
    _kvRow(t('overview.comments'), escapeHtml(commentsOpen ? t('overview.openCount', {n: commentsOpen}) : t('overview.none'))),
    _kvRow(t('overview.research'), escapeHtml(_researchSummary()))
  ].join('');
}

function _kvRow(label, valueHtml) {
  return '<div class="kv"><span>' + escapeHtml(label) + '</span><span>' + valueHtml + '</span></div>';
}

function _planStatusPill() {
  var hasPlan = !!((PLAN_DATA && PLAN_DATA.execution) || []).length;
  if (!hasPlan) return escapeHtml(t('status.notSet'));
  var status = LOCK_DATA.plan_status;
  if (status === 'approved') return '<span class="pill ok">' + escapeHtml(t('status.approved')) + '</span>';
  if (status === 'rejected') return '<span class="pill bad">' + escapeHtml(t('badges.rejected')) + '</span>';
  return '<span class="pill warn">' + escapeHtml(t('status.pending')) + '</span>';
}

function _criteriaSummary() {
  var criteria = AppState.criteria || [];
  if (!criteria.length) return t('overview.none');
  var accepted = criteria.filter(function(c) { return c.status === 'accepted'; }).length;
  return t('overview.criteriaCount', {accepted: accepted, total: criteria.length});
}

function _researchSummary() {
  var research = AppState.research || [];
  if (!research.length) return t('overview.none');
  var proven = research.filter(function(r) { return !!r.proven; }).length;
  return t('overview.researchCount', {proven: proven, total: research.length});
}

function _countOpenComments() {
  var comments = AppState.comments || {};
  return Object.keys(comments).reduce(function(sum, key) {
    if (key.indexOf('review:') === 0) return sum;
    return sum + comments[key].filter(function(c) { return !c.parent_id && !c.resolved; }).length;
  }, 0);
}

// ═══════════════════════════════════════════════
//  WORKSPACE SIDEBAR
// ═══════════════════════════════════════════════
var SIDEBAR_POLL_MS = 30000;
var SIDEBAR_DONE_VISIBLE = 5;
var _sidebar = { projectId: null, projects: [], workspaces: [], gates: {}, etags: {}, showAllDone: false, timer: null };

// Phases where another workspace may be waiting on a human; only these need
// a /state fetch to learn whether the gate is really pending.
function _mayHoldGate(phase) {
  return phase === '2.0' || isUserGate(phase);
}

async function loadSidebar() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  if (_sidebar.projectId !== ctx.projectId) {
    _sidebar = Object.assign(_sidebar, { projectId: ctx.projectId, workspaces: [], gates: {}, etags: {}, showAllDone: false });
  }
  try {
    var projectsData = await apiListProjects();
    _sidebar.projects = projectsData.projects || [];
    var wsData = await apiListWorkspaces(ctx.projectId);
    _sidebar.workspaces = (wsData.workspaces || []).filter(function(ws) { return ws.status !== 'archived'; });
    await _loadSidebarGates(ctx);
  } catch (e) {
    console.warn('Sidebar refresh failed:', e.message);
  }
  renderSidebar();
}

async function _loadSidebarGates(ctx) {
  var candidates = _sidebar.workspaces.filter(function(ws) { return ws.branch !== ctx.branch && _mayHoldGate(ws.phase); });
  var gates = {};
  await Promise.all(candidates.map(async function(ws) {
    gates[ws.branch] = await _fetchWorkspaceGate(ctx.projectId, ws.branch);
  }));
  _sidebar.gates = gates;
}

async function _fetchWorkspaceGate(projectId, branch) {
  var cacheKey = projectId + '/' + branch;
  try {
    var response = await apiGetState(projectId, branch, _sidebar.etags[cacheKey]);
    if (response.notModified) return _sidebar.gates[branch] || null;
    if (response.etag) _sidebar.etags[cacheKey] = response.etag;
    return describePendingGate(response.data);
  } catch (e) {
    console.warn('Gate lookup failed for ' + branch + ':', e.message);
    return null;
  }
}

function startSidebarPolling() {
  if (_sidebar.timer) clearInterval(_sidebar.timer);
  _sidebar.timer = setInterval(function() {
    loadSidebar();
    renderPhaseActions();
    renderGateBar();
  }, SIDEBAR_POLL_MS);
  loadSidebar();
}

function _sidebarGroups() {
  var ctx = getWorkspaceContext();
  var groups = { needs: [], working: [], done: [] };
  _sidebar.workspaces.forEach(function(ws) {
    var isCurrent = ctx && ws.branch === ctx.branch;
    var gate = isCurrent ? getPendingGate() : _sidebar.gates[ws.branch];
    var phase = isCurrent ? LOCK_DATA.phase : ws.phase;
    var entry = { ws: ws, gate: gate, phase: phase, isCurrent: isCurrent };
    if (gate) groups.needs.push(entry);
    else if (phase === '6') groups.done.push(entry);
    else groups.working.push(entry);
  });
  groups.needs.sort(function(a, b) { return _gateAge(b.gate) - _gateAge(a.gate); });
  return groups;
}

function _gateAge(gate) {
  return gate.since ? Date.now() - gate.since.getTime() : 0;
}

function renderSidebar() {
  _renderSidebarProject();
  var container = document.getElementById('sideGroups');
  if (!container) return;
  var groups = _sidebarGroups();
  _renderSidebarRailGates(groups.needs.length);
  if (!_sidebar.workspaces.length) {
    container.innerHTML = '<div class="empty sm">' + escapeHtml(t('shell.noWorkspaces')) + '</div>';
    return;
  }
  var done = _sidebar.showAllDone ? groups.done : groups.done.slice(0, SIDEBAR_DONE_VISIBLE);
  container.innerHTML =
    _sidebarGroupHtml('shell.needsYou', groups.needs, groups.needs.length, true) +
    _sidebarGroupHtml('shell.agentWorking', groups.working, groups.working.length, false) +
    _sidebarGroupHtml('shell.done', done, groups.done.length, false) +
    _sidebarDoneToggle(groups.done.length);
}

// Folded to a rail, the sidebar still shows how many workspaces wait on a
// human, so gates never go unnoticed.
function _renderSidebarRailGates(waitingCount) {
  var badge = document.getElementById('sideRailGates');
  if (!badge) return;
  badge.hidden = waitingCount === 0;
  var label = tn('shell.workspacesNeedYou', waitingCount);
  _setText('sideRailGatesCount', waitingCount);
  badge.title = label;
  badge.setAttribute('aria-label', label);
}

function _sidebarGroupHtml(labelKey, entries, total, isGateGroup) {
  if (!total) return '';
  var countHtml = isGateGroup ? '<span class="cnt gate">' + total + '</span>' : '<span>' + total + '</span>';
  return '<div class="grp"><span>' + escapeHtml(t(labelKey)) + '</span>' + countHtml + '</div>' +
    entries.map(_sidebarItemHtml).join('');
}

function _sidebarItemHtml(entry) {
  var branch = entry.ws.branch;
  var name = escapeHtml(branch);
  var title = entry.gate ? '<b class="trunc">' + name + '</b>' : '<span class="trunc">' + name + '</span>';
  return '<button class="ws' + (entry.isCurrent ? ' on' : '') + '" title="' + name + '" data-branch="' + name + '" onclick="openSidebarWorkspace(this.dataset.branch)">' +
    title + '<small class="trunc' + (entry.gate ? ' g' : '') + '">' + escapeHtml(_sidebarSubLabel(entry)) + '</small></button>';
}

function _sidebarSubLabel(entry) {
  if (entry.gate) {
    var wait = formatWaitDuration(entry.gate.since);
    return t(entry.gate.config.nameKey) + (wait ? ' · ' + wait : '');
  }
  if (entry.phase === '6') return entry.ws.created ? t('shell.createdAgo', {when: formatRelativeDate(entry.ws.created)}) : t('station.done');
  return stationLabel(entry.phase) + ' · ' + entry.phase;
}

function _sidebarDoneToggle(doneCount) {
  if (doneCount <= SIDEBAR_DONE_VISIBLE) return '';
  var label = _sidebar.showAllDone ? t('shell.showLessDone') : t('shell.showAllDone', {count: doneCount});
  return '<button class="btn ghost xs side-more" onclick="toggleSidebarDone()">' + escapeHtml(label) + '</button>';
}

function toggleSidebarDone() {
  _sidebar.showAllDone = !_sidebar.showAllDone;
  renderSidebar();
}

function _renderSidebarProject() {
  var project = _sidebar.projects.find(function(p) { return p.id === _sidebar.projectId; });
  _setText('sideProjectName', project ? project.name : (_sidebar.projectId || ''));
}

function openSidebarWorkspace(branch) {
  closeMobileSidebar();
  var ctx = getWorkspaceContext();
  if (!ctx || ctx.branch === branch) return;
  openWorkspace(ctx.projectId, branch);
}

function toggleSidebarProjectMenu() {
  var menu = document.getElementById('sideProjectMenu');
  if (!menu) return;
  var willOpen = menu.style.display === 'none';
  menu.style.display = willOpen ? 'flex' : 'none';
  if (willOpen) menu.innerHTML = _sidebarProjectMenuHtml();
}

function _sidebarProjectMenuHtml() {
  var items = _sidebar.projects.map(function(p) {
    var current = p.id === _sidebar.projectId ? ' aria-current="true"' : '';
    return '<button class="btn-dropdown-item"' + current + ' data-project-id="' + escapeHtml(p.id) + '" onclick="openSidebarProject(this.dataset.projectId)">' + escapeHtml(p.name) + '</button>';
  });
  items.push('<hr class="sep">');
  items.push('<button class="btn-dropdown-item" onclick="showProjectSelector()">' + escapeHtml(t('shell.allProjects')) + '</button>');
  return items.join('');
}

function openSidebarProject(projectId) {
  showProjectSelector();
  openProject(projectId);
}

function openNewWorkspace() {
  var ctx = getWorkspaceContext();
  showProjectSelector();
  if (ctx) openProject(ctx.projectId);
}

// The sidebar is needed rarely, so it starts folded to an icon rail.
var SIDEBAR_PANEL = {
  storageKey: 'ui_sidebar_collapsed',
  collapsedByDefault: true,
  hostId: 'app-content',
  hostClass: 'side-collapsed',
  toggleId: 'sideCollapseToggle',
  expandKey: 'shell.expandSidebar',
  collapseKey: 'shell.collapseSidebar',
  onSettled: refitVisibleTerminals
};

function toggleSidebarCollapsed() {
  togglePanelCollapsed(SIDEBAR_PANEL);
}

initCollapsiblePanel(SIDEBAR_PANEL);

document.addEventListener('click', function(e) {
  var menu = document.getElementById('sideProjectMenu');
  if (menu && menu.style.display !== 'none' && !e.target.closest('.side-picker')) menu.style.display = 'none';
});

// ═══════════════════════════════════════════════
//  EVENT WIRING
// ═══════════════════════════════════════════════

EventBus.on('state:refreshed', renderShell);
EventBus.on('approval:changed', renderShell);
EventBus.on('comments:changed', function() {
  renderTabCounts();
  renderOpenItems();
});
EventBus.on('diff:refreshed', function() {
  renderTabCounts();
  renderOverviewChanges();
  renderPhaseActions();
});
EventBus.on('criteria:changed', renderOpenItems);
EventBus.on('context:refreshed', renderWorkspaceHeader);
PHONE_LAYOUT_QUERY.addEventListener('change', renderGateBar);
