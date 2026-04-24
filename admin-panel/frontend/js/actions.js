// ═══════════════════════════════════════════════
//  USER GATE ACTIONS
// ═══════════════════════════════════════════════

async function handleApprove() {
  var ctx = getWorkspaceContext();
  if (!ctx) { showToast(t('errors.workspaceNotSelected')); return; }

  if (!isUserGate(state.phase)) { showToast(t('errors.noApprovalGateActive')); return; }

  var commitMessage = '';
  var input = document.getElementById('commitMessageInput');
  if (input) commitMessage = input.value.trim();

  try {
    var result = await apiApprove(ctx.projectId, ctx.branch, commitMessage);
    showToast(t('messages.approved', {phase: result.phase}));
    await refreshState();
  } catch (e) {
    showToast(t('messages.approveFailed', {error: e.message}));
  }
}

async function handleReject(feedback) {
  var ctx = getWorkspaceContext();
  if (!ctx) { showToast(t('errors.workspaceNotSelected')); return; }

  if (!isUserGate(state.phase)) { showToast(t('errors.noApprovalGateActive')); return; }

  var comments = feedback || '';

  try {
    var result = await apiReject(ctx.projectId, ctx.branch, comments);
    showToast(t('messages.rejected', {phase: result.phase}));
    await refreshState();
  } catch (e) {
    showToast(t('messages.rejectFailed', {error: e.message}));
  }
}

async function handleRejectWithInput() {
  var input = document.getElementById('rejectFeedbackInput');
  var feedback = input ? input.value.trim() : '';
  await handleReject(feedback);
}

function _updateApprovalUI(badgeId, approveBtnId, rejectBtnId, setStatus, status) {
  var badge = document.getElementById(badgeId);
  var approveBtn = document.getElementById(approveBtnId);
  var rejectBtn = document.getElementById(rejectBtnId);
  if (!badge || !approveBtn || !rejectBtn) return;

  approveBtn.style.display = '';
  rejectBtn.style.display = '';

  if (status === 'approved') {
    badge.textContent = t('badges.approved');
    badge.className = 'badge badge-success';
    approveBtn.textContent = t('buttons.revokeApproval');
    approveBtn.className = 'btn btn-sm btn-outline';
    approveBtn.onclick = function() { setStatus('pending'); };
    rejectBtn.textContent = t('buttons.reject');
    rejectBtn.className = 'btn btn-sm btn-danger-outline';
    rejectBtn.onclick = function() { setStatus('rejected'); };
  } else if (status === 'rejected') {
    badge.textContent = t('badges.rejected');
    badge.className = 'badge badge-danger';
    approveBtn.textContent = t('buttons.approve');
    approveBtn.className = 'btn btn-sm btn-primary';
    approveBtn.onclick = function() { setStatus('approved'); };
    rejectBtn.textContent = t('buttons.revokeRejection');
    rejectBtn.className = 'btn btn-sm btn-outline';
    rejectBtn.onclick = function() { setStatus('pending'); };
  } else {
    badge.textContent = t('badges.pending');
    badge.className = 'badge badge-warning';
    approveBtn.textContent = t('buttons.approve');
    approveBtn.className = 'btn btn-sm btn-primary';
    approveBtn.onclick = function() { setStatus('approved'); };
    rejectBtn.textContent = t('buttons.reject');
    rejectBtn.className = 'btn btn-sm btn-danger-outline';
    rejectBtn.onclick = function() { setStatus('rejected'); };
  }
}

function updateScopeStatusUI(status) {
  _updateApprovalUI('scopeStatusBadge', 'scopeApproveBtn', 'scopeRejectBtn', setScopeStatus, status);
}

async function setScopeStatus(status) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  try {
    await apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/scope-status', {status: status});
    LOCK_DATA.scope_status = status;
    EventBus.emit('approval:changed');
    if (status === 'approved') {
      updateScopeStatusUI(status);
      await tryAutoAdvanceGate();
    } else {
      updateScopeStatusUI(status);
    }
  } catch (e) {
    console.error('Failed to set scope status:', e);
  }
}

function updatePlanApprovalUI(status) {
  _updateApprovalUI('planStatusBadge', 'planApproveBtn', 'planRejectBtn', setPlanStatus, status);
}

async function setPlanStatus(status) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  try {
    await apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/plan-status', {status: status});
    LOCK_DATA.plan_status = status;
    EventBus.emit('approval:changed');
    if (status === 'approved') {
      updatePlanApprovalUI(status);
      await tryAutoAdvanceGate();
    } else {
      updatePlanApprovalUI(status);
    }
  } catch (e) {
    console.error('Failed to set plan status:', e);
  }
}

async function tryAutoAdvanceGate() {
  if (state.phase !== '2.1') return;
  if (LOCK_DATA.plan_status !== 'approved' || LOCK_DATA.scope_status !== 'approved') return;

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  try {
    var result = await apiApprove(ctx.projectId, ctx.branch, '');
    showToast(t('messages.approved', {phase: result.phase}));
    await refreshState();
  } catch (e) {
    console.log('Auto-advance failed, use Phase Control:', e.message);
  }
}

var _lastStateEtag = null;

function resetStateEtag() {
  _lastStateEtag = null;
}

document.addEventListener('workspace-reset', resetStateEtag);

async function refreshState() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var refreshBtn = document.querySelector('.header-refresh-btn');
  if (refreshBtn) refreshBtn.classList.add('refreshing');

  try {
    var response = await apiGetState(ctx.projectId, ctx.branch, _lastStateEtag);

    if (response.notModified) {
      if (response.etag) _lastStateEtag = response.etag;
      return;
    }

    var stateData = response.data;
    if (response.etag) _lastStateEtag = response.etag;

    applyStateData(stateData);

    document.getElementById('phaseLabel').textContent = t('phase.label', {phase: state.phase, name: getPhaseName(state.phase)});

    var yoloCheck = document.getElementById('yoloCheck');
    if (yoloCheck) yoloCheck.checked = !!LOCK_DATA.yolo_mode;

    updateScopeStatusUI(LOCK_DATA.scope_status || 'pending');
    updatePlanApprovalUI(LOCK_DATA.plan_status || 'pending');

    EventBus.emit('state:refreshed', stateData);
  } catch (e) {
    console.warn('Failed to refresh state:', e.message);
  } finally {
    if (refreshBtn) refreshBtn.classList.remove('refreshing');
  }
}

