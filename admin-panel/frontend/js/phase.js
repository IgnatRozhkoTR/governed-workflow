// ═══════════════════════════════════════════════
//  PHASE HISTORY LOG
// ═══════════════════════════════════════════════
var PHASE_HISTORY_VISIBLE = 8;

function renderPhaseHistory() {
  var container = document.getElementById('phaseHistoryLog');
  if (!container) return;

  var history = AppState.phaseHistory || [];
  if (history.length === 0) {
    container.innerHTML = '<span>' + escapeHtml(t('phase.noChangesRecorded')) + '</span>';
    return;
  }

  container.innerHTML = history
    .slice(-PHASE_HISTORY_VISIBLE)
    .reverse()
    .map(function(entry) {
      return '<span title="' + escapeHtml(entry.time) + '">' + escapeHtml(t('overview.historyEntry', {
        from: entry.from, to: entry.to, when: formatRelativeDate(entry.time)
      })) + '</span>';
    })
    .join('');
}

// ═══════════════════════════════════════════════
//  PHASE SEQUENCE
// ═══════════════════════════════════════════════

function getPhaseSequenceForBar() {
  var enabledPhases = LOCK_DATA.enabled_phases;
  if (enabledPhases && enabledPhases.length > 0) {
    return enabledPhases.slice();
  }

  var fixedBefore = ['0', '1.0', '1.1', '1.2', '1.3', '1.4', '2.0', '2.1'];
  var fixedAfter = ['4.0', '4.1', '4.2', '5'];

  var plan = LOCK_DATA.plan;
  var execPhases = [];
  if (plan && plan.execution && plan.execution.length > 0) {
    plan.execution.forEach(function(item) {
      var n = item.id.split('.').pop();
      for (var k = 0; k <= 4; k++) {
        execPhases.push('3.' + n + '.' + k);
      }
    });
  } else {
    execPhases = ['3.N'];
  }

  return fixedBefore.concat(execPhases).concat(fixedAfter);
}

// ═══════════════════════════════════════════════
//  MANUAL PHASE OVERRIDE
// ═══════════════════════════════════════════════
function manualSetPhase() {
  var current = LOCK_DATA.phase || '0';
  var rows = getPhaseSequenceForBar().map(function(phase) {
    return '<label class="row phase-pick-row">' +
      '<input type="radio" name="setPhaseChoice" value="' + escapeHtml(phase) + '"' + (phase === current ? ' checked' : '') + '>' +
      '<span class="mono phase-pick-id">' + escapeHtml(phase) + '</span>' +
      '<span class="grow">' + escapeHtml(getPhaseName(phase)) + '</span>' +
      (isUserGate(phase) ? '<span class="pill gate">' + escapeHtml(t('phase.gateTag')) + '</span>' : '') +
    '</label>';
  }).join('');

  var modal = _ensureSetPhaseModal();
  modal.querySelector('.file-preview-body').innerHTML =
    '<div class="note warn-note"><div class="k">' + cpIcon('flag', 14) + escapeHtml(t('dialog.setPhaseWarning')) + '</div></div>' +
    '<div class="card phase-pick-list"><div class="cb flush">' + rows + '</div></div>' +
    '<div class="hs"><span class="sm dim grow">' + escapeHtml(t('dialog.setPhaseCurrent', {phase: current})) + '</span>' +
      '<button class="btn" onclick="closeSetPhaseDialog()">' + escapeHtml(t('buttons.cancel')) + '</button>' +
      '<button class="btn pri" onclick="submitSetPhase()">' + escapeHtml(t('buttons.setPhase')) + '</button></div>';
  modal.classList.add('open');
  var picked = modal.querySelector('input:checked');
  if (picked) picked.closest('.row').scrollIntoView({ block: 'center' });
}

function _ensureSetPhaseModal() {
  var modal = document.getElementById('setPhaseModal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'setPhaseModal';
  modal.className = 'file-preview-modal';
  modal.onclick = function(e) { if (e.target === modal) closeSetPhaseDialog(); };
  modal.innerHTML = '<div class="file-preview-content" role="dialog" aria-modal="true">' +
    '<div class="file-preview-header"><h3 class="grow">' + escapeHtml(t('buttons.setPhase')) + '</h3>' +
    '<button class="btn ic xs" onclick="closeSetPhaseDialog()" aria-label="' + escapeHtml(t('buttons.close')) + '">' + cpIcon('x', 14) + '</button></div>' +
    '<div class="file-preview-body vs g12"></div></div>';
  document.body.appendChild(modal);
  return modal;
}

function closeSetPhaseDialog() {
  var modal = document.getElementById('setPhaseModal');
  if (modal) modal.classList.remove('open');
}

async function submitSetPhase() {
  var picked = document.querySelector('#setPhaseModal input[name="setPhaseChoice"]:checked');
  var ctx = getWorkspaceContext();
  if (!picked || !ctx) return;
  try {
    await apiSetPhase(ctx.projectId, ctx.branch, picked.value);
    closeSetPhaseDialog();
    await refreshState();
  } catch (err) {
    showToast(t('errors.failedToSetPhase', {error: err.message}));
  }
}

// ═══════════════════════════════════════════════
//  PENDING GATE MODEL
//  A gate is either a phase the backend marks as a user gate
//  (pending_gate) or the plan sitting at 2.0 awaiting approval.
// ═══════════════════════════════════════════════

var _PHASE_GATE_CONFIGS = [
  {
    matches: function(p) { return p === '1.4'; },
    nameKey: 'gate.name.preplanning',
    questionKey: 'gate.question.preplanning',
    descKey: 'phaseAction.preplanningReviewDesc',
    approveKey: 'preplanning.approvePreplanning',
    rejectKey: 'preplanning.rejectPreplanning',
    decidingTab: 'preplanning'
  },
  {
    matches: function(p) { return p === '2.0' || p === '2.1'; },
    nameKey: 'gate.name.plan',
    questionKey: 'gate.question.plan',
    descKey: 'phaseAction.planReviewDesc',
    approveKey: 'buttons.approvePlan',
    rejectKey: 'buttons.requestChanges',
    decidingTab: 'plan'
  },
  {
    matches: function(p) { return /^3\.\d+\.3$/.test(p); },
    nameKey: 'gate.name.commit',
    questionKey: 'gate.question.commit',
    descKey: 'phaseAction.codeReviewDesc',
    approveKey: 'buttons.approveChanges',
    rejectKey: 'buttons.requestChanges',
    decidingTab: 'overview'
  },
  {
    matches: function(p) { return p === '4.2'; },
    nameKey: 'gate.name.final',
    questionKey: 'gate.question.final',
    descKey: 'phaseAction.finalApprovalDesc',
    approveKey: 'buttons.approveFinish',
    rejectKey: 'buttons.requestChanges',
    decidingTab: 'overview'
  }
];

var _GENERIC_GATE_CONFIG = {
  nameKey: 'gate.name.generic',
  questionKey: 'gate.question.generic',
  descKey: null,
  approveKey: 'buttons.approve',
  rejectKey: 'buttons.requestChanges',
  decidingTab: 'overview'
};

function findGateConfig(phase) {
  for (var i = 0; i < _PHASE_GATE_CONFIGS.length; i++) {
    if (_PHASE_GATE_CONFIGS[i].matches(phase)) return _PHASE_GATE_CONFIGS[i];
  }
  return _GENERIC_GATE_CONFIG;
}

function isPlanAwaitingApproval(stateData) {
  var execution = stateData.plan && stateData.plan.execution;
  return stateData.phase === '2.0' && stateData.plan_status === 'pending' && !!(execution && execution.length);
}

// Builds the gate descriptor from a raw /state payload, so the sidebar can
// evaluate other workspaces with the same rules as the open one.
function describePendingGate(stateData) {
  var history = stateData.phaseHistory || [];
  if (stateData.pending_gate) {
    return _gateDescriptor(stateData.pending_gate.phase, 'phase', !!stateData.pending_gate.accepts_commit_message, history);
  }
  if (isPlanAwaitingApproval(stateData)) return _gateDescriptor('2.0', 'plan', false, history);
  return null;
}

function _gateDescriptor(phase, kind, acceptsCommitMessage, history) {
  var config = findGateConfig(phase);
  return {
    phase: phase,
    kind: kind,
    acceptsCommitMessage: acceptsCommitMessage,
    config: config,
    decidingTab: config.decidingTab,
    since: _phaseEnteredAt(phase, history)
  };
}

function getPendingGate() {
  return describePendingGate({
    phase: LOCK_DATA.phase,
    pending_gate: LOCK_DATA.pending_gate,
    plan_status: LOCK_DATA.plan_status,
    plan: LOCK_DATA.plan,
    phaseHistory: AppState.phaseHistory
  });
}

function _phaseEnteredAt(phase, history) {
  for (var i = history.length - 1; i >= 0; i--) {
    if (history[i].to === phase) {
      var entered = new Date(history[i].time);
      return isNaN(entered.getTime()) ? null : entered;
    }
  }
  return null;
}

function formatWaitDuration(since) {
  if (!since) return '';
  var minutes = Math.max(0, Math.floor((Date.now() - since.getTime()) / 60000));
  if (minutes < 60) return t('time.waitMin', {n: minutes});
  var hours = Math.floor(minutes / 60);
  if (hours < 24) return t('time.waitHours', {n: hours});
  return t('time.waitDays', {n: Math.floor(hours / 24)});
}

function describeGateHold(gate) {
  return gate.since
    ? t('gate.holding', {phase: gate.phase, wait: formatWaitDuration(gate.since)})
    : t('gate.holdingNoWait', {phase: gate.phase});
}

// ═══════════════════════════════════════════════
//  GATE CARD (Overview)
// ═══════════════════════════════════════════════

function renderPhaseActions() {
  var container = document.getElementById('phaseActions');
  if (!container) return;

  var gate = getPendingGate();
  if (!gate) {
    container.innerHTML = '';
    container.dataset.gateKey = '';
    return;
  }

  // Rebuild only when the gate itself changes, so a state refresh never wipes
  // a commit message or feedback the user is typing.
  var gateKey = gate.kind + ':' + gate.phase;
  if (container.dataset.gateKey !== gateKey) {
    container.dataset.gateKey = gateKey;
    container.innerHTML = gate.kind === 'plan' ? _renderPlanGateCard(gate) : _renderPhaseGateCard(gate);
    var feedbackInput = container.querySelector('#rejectFeedbackInput');
    if (feedbackInput) attachSubmitKey(feedbackInput, handleRejectWithInput);
  }
  _refreshGateCardFacts(container, gate);
}

function _renderGateCardHead(gate) {
  return '<span class="gateico">' + cpGateIcon(20) + '</span>' +
    '<div class="grow gatecard__head">' +
      '<div class="k" data-gate-hold></div>' +
      '<h2>' + escapeHtml(t(gate.config.questionKey)) + '</h2>' +
      '<div class="d brk" data-gate-facts></div>' +
    '</div>';
}

function buildGateCardHtml(gate, actionsHtml, inputsHtml) {
  return '<section class="gatecard" aria-label="' + escapeHtml(t('gate.pending')) + '">' +
    _renderGateCardHead(gate) +
    '<div class="hs wrap gatecard__actions">' + actionsHtml + '</div>' +
    (inputsHtml ? '<div class="cols gatecard__inputs">' + inputsHtml + '</div>' : '') +
  '</section>';
}

function _renderPhaseGateCard(gate) {
  var commitField = gate.acceptsCommitMessage
    ? '<div class="narrow"><label class="lbl">' + escapeHtml(t('gate.commitMessageLabel')) +
        '<input class="inp" type="text" id="commitMessageInput" placeholder="' + escapeHtml(t('placeholders.commitMessage')) + '"></label></div>'
    : '';
  return buildGateCardHtml(gate,
    '<button class="btn onGate lg" onclick="handleRejectWithInput()">' + escapeHtml(t(gate.config.rejectKey)) + '</button>' +
    '<button class="btn pri lg" onclick="handleApprove()">' + cpIcon('check') + escapeHtml(t(gate.config.approveKey)) + '</button>',
    commitField +
      '<div class="wide"><label class="lbl">' + escapeHtml(t('gate.feedbackLabel')) +
        '<input class="inp" type="text" id="rejectFeedbackInput" placeholder="' + escapeHtml(t('gate.feedbackPlaceholder')) + '"></label></div>');
}

function _renderPlanGateCard(gate) {
  return buildGateCardHtml(gate,
    '<button class="btn pri lg" onclick="switchTab(\'plan\')">' + escapeHtml(t('gate.reviewPlan')) + '</button>', '');
}

function _refreshGateCardFacts(container, gate) {
  var hold = container.querySelector('[data-gate-hold]');
  var facts = container.querySelector('[data-gate-facts]');
  if (hold) hold.textContent = describeGateHold(gate);
  if (facts) facts.textContent = describeGateFacts(gate);
}

function describeGateFacts(gate) {
  if (gate.kind === 'plan') return _describePlanFacts();
  if (gate.phase === '1.4') return _describePreplanningFacts();
  if (/^3\.\d+\.3$/.test(gate.phase)) return _describeCommitFacts(gate.phase);
  return gate.config.descKey ? t(gate.config.descKey) : '';
}

function _describePlanFacts() {
  var execution = (PLAN_DATA && PLAN_DATA.execution) || [];
  var taskCount = execution.reduce(function(sum, item) { return sum + ((item.tasks || []).length); }, 0);
  var facts = [t('gate.facts.plan', {subPhases: execution.length, tasks: taskCount})];
  var proposed = (AppState.criteria || []).filter(function(c) { return c.status === 'proposed'; }).length;
  if (proposed) facts.push(t('gate.facts.proposedCriteria', {n: proposed}));
  var openComments = _countOpenComments();
  if (openComments) facts.push(t('gate.facts.openComments', {n: openComments}));
  return facts.join(' · ');
}

function _describePreplanningFacts() {
  var facts = [t('gate.facts.researchTopics', {n: (RESEARCH_DATA || []).length})];
  if (AppState.impactAnalysis) facts.push(t('gate.facts.impactRecorded'));
  var openDiscussions = ((CONTEXT_DATA && CONTEXT_DATA.discussions) || []).filter(function(d) { return d.status === 'open'; }).length;
  facts.push(t('gate.facts.openDiscussions', {n: openDiscussions}));
  return facts.join(' · ');
}

function _describeCommitFacts(phase) {
  var subPhaseId = phase.split('.').slice(0, 2).join('.');
  var subPhase = ((PLAN_DATA && PLAN_DATA.execution) || []).find(function(e) { return e.id === subPhaseId; });
  var totals = summarizeDiffFiles(DIFF_DATA.files || []);
  return t('gate.facts.commit', {
    id: subPhaseId,
    name: subPhase ? subPhase.name : '',
    files: totals.files,
    additions: totals.additions,
    deletions: totals.deletions
  });
}

function summarizeDiffFiles(files) {
  return files.reduce(function(sum, f) {
    sum.additions += f.additions || 0;
    sum.deletions += f.deletions || 0;
    return sum;
  }, { files: files.length, additions: 0, deletions: 0 });
}

EventBus.on('state:refreshed', function() {
  renderPhaseActions();
  renderPhaseHistory();
});
