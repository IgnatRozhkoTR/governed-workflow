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
async function manualSetPhase() {
  var newPhase = prompt(t('dialog.setPhase'), LOCK_DATA.phase || '0');
  if (newPhase === null || newPhase.trim() === '') return;
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    await apiSetPhase(ctx.projectId, ctx.branch, newPhase.trim());
    await refreshState();
  } catch (err) {
    alert(t('errors.failedToSetPhase', {error: err.message}));
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

function _renderPhaseGateCard(gate) {
  var commitField = gate.acceptsCommitMessage
    ? '<div class="narrow"><label class="lbl">' + escapeHtml(t('gate.commitMessageLabel')) +
        '<input class="inp" type="text" id="commitMessageInput" placeholder="' + escapeHtml(t('placeholders.commitMessage')) + '"></label></div>'
    : '';
  return '<section class="gatecard" aria-label="' + escapeHtml(t('gate.pending')) + '">' +
    _renderGateCardHead(gate) +
    '<div class="hs wrap gatecard__actions">' +
      '<button class="btn onGate lg" onclick="handleRejectWithInput()">' + escapeHtml(t(gate.config.rejectKey)) + '</button>' +
      '<button class="btn pri lg" onclick="handleApprove()">' + cpIcon('check') + escapeHtml(t(gate.config.approveKey)) + '</button>' +
    '</div>' +
    '<div class="cols gatecard__inputs">' + commitField +
      '<div class="wide"><label class="lbl">' + escapeHtml(t('gate.feedbackLabel')) +
        '<input class="inp" type="text" id="rejectFeedbackInput" placeholder="' + escapeHtml(t('gate.feedbackPlaceholder')) + '"></label></div>' +
    '</div>' +
  '</section>';
}

function _renderPlanGateCard(gate) {
  return '<section class="gatecard" aria-label="' + escapeHtml(t('gate.pending')) + '">' +
    _renderGateCardHead(gate) +
    '<div class="hs wrap gatecard__actions">' +
      '<button class="btn pri lg" onclick="switchTab(\'plan\')">' + escapeHtml(t('gate.reviewPlan')) + '</button>' +
    '</div>' +
  '</section>';
}

function _refreshGateCardFacts(container, gate) {
  var hold = container.querySelector('[data-gate-hold]');
  var facts = container.querySelector('[data-gate-facts]');
  if (hold) hold.textContent = describeGateHold(gate);
  if (facts) facts.textContent = describeGateFacts(gate);
}

function describeGateFacts(gate) {
  if (gate.kind === 'plan') {
    var execution = (PLAN_DATA && PLAN_DATA.execution) || [];
    var taskCount = execution.reduce(function(sum, item) { return sum + ((item.tasks || []).length); }, 0);
    return t('gate.facts.plan', {subPhases: execution.length, tasks: taskCount});
  }
  if (/^3\.\d+\.3$/.test(gate.phase)) return _describeCommitFacts(gate.phase);
  return gate.config.descKey ? t(gate.config.descKey) : '';
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
