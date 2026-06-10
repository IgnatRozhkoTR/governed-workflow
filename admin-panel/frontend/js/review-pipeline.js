// ═══════════════════════════════════════════════
//  REVIEW PIPELINE STATUS CARD
// ═══════════════════════════════════════════════

var _rpPollingTimers = {};

var _RP_ACTIVE_STATES = new Set(['queued', 'filtering', 'file_stage', 'integration_stage']);

function _rpStateBadgeClass(state) {
  switch (state) {
    case 'done':               return 'rp-badge--done';
    case 'failed':             return 'rp-badge--failed';
    case 'queued':             return 'rp-badge--queued';
    case 'filtering':          return 'rp-badge--filtering';
    case 'file_stage':         return 'rp-badge--file-stage';
    case 'integration_stage':  return 'rp-badge--integration-stage';
    default:                   return 'rp-badge--queued';
  }
}

function _rpStateLabel(state) {
  return t('reviewPipeline.state.' + state) || state;
}

function _rpFileStatusIcon(status) {
  switch (status) {
    case 'done':    return '<span class="rp-status-icon rp-status-icon--done">&#10003;</span>';
    case 'failed':  return '<span class="rp-status-icon rp-status-icon--failed">&#10007;</span>';
    case 'running': return '<span class="rp-status-icon rp-status-icon--running">&#9679;</span>';
    default:        return '<span class="rp-status-icon rp-status-icon--pending">&#9675;</span>';
  }
}

function _rpReviewerStatusIcon(status) {
  return _rpFileStatusIcon(status);
}

function _rpElapsed(startedAt, finishedAt) {
  if (!startedAt) return '';
  var endTs = finishedAt || (Date.now() / 1000);
  var seconds = Math.max(0, Math.round(endTs - startedAt));
  return t('reviewPipeline.elapsed').replace('{seconds}', seconds);
}

function _rpFilesHtml(files) {
  if (!files || Object.keys(files).length === 0) return '';

  var entries = Object.values(files);
  var total = entries.length;
  var done = entries.filter(function(f) { return f.status === 'done' || f.status === 'failed'; }).length;
  var progressLabel = t('reviewPipeline.filesProgress')
    .replace('{done}', done)
    .replace('{total}', total);

  var rows = entries.map(function(f) {
    var findingsHtml = (f.status === 'done' && f.findings_count != null)
      ? ' <span class="rp-findings-count">(' + escapeHtml(f.findings_count) + ')</span>'
      : '';
    var errorHtml = f.error
      ? '<div class="rp-file-error">' + escapeHtml(f.error) + '</div>'
      : '';
    return '<div class="rp-file-row">'
      + _rpFileStatusIcon(f.status)
      + '<span class="rp-file-path">' + escapeHtml(f.file) + '</span>'
      + findingsHtml
      + errorHtml
      + '</div>';
  }).join('');

  return '<div class="rp-section">'
    + '<div class="rp-section-header">'
    + '<span class="rp-section-label">' + t('reviewPipeline.filesSection') + '</span>'
    + '<span class="rp-progress-label">' + escapeHtml(progressLabel) + '</span>'
    + '</div>'
    + '<div class="rp-files-list">' + rows + '</div>'
    + '</div>';
}

function _rpIntegrationHtml(integration) {
  if (!integration || Object.keys(integration).length === 0) return '';

  var rows = Object.entries(integration).map(function(entry) {
    var reviewer = entry[0];
    var status = entry[1];
    var statusLabel = t('reviewPipeline.fileStatus.' + status) || status;
    return '<div class="rp-integration-row">'
      + _rpReviewerStatusIcon(status)
      + '<span class="rp-reviewer-name">' + escapeHtml(reviewer) + '</span>'
      + '<span class="rp-reviewer-status">' + escapeHtml(statusLabel) + '</span>'
      + '</div>';
  }).join('');

  return '<div class="rp-section">'
    + '<div class="rp-section-header">'
    + '<span class="rp-section-label">' + t('reviewPipeline.integrationSection') + '</span>'
    + '</div>'
    + '<div class="rp-integration-list">' + rows + '</div>'
    + '</div>';
}

function _rpRenderStatus(container, data) {
  var elapsedHtml = data.started_at
    ? '<div class="rp-elapsed">' + escapeHtml(_rpElapsed(data.started_at, data.finished_at)) + '</div>'
    : '';

  var errorHtml = data.error
    ? '<div class="rp-pipeline-error">' + escapeHtml(data.error) + '</div>'
    : '';

  container.innerHTML = '<div class="rp-card-body">'
    + '<div class="rp-state-row">'
    + '<span class="rp-badge ' + _rpStateBadgeClass(data.state) + '">'
    + escapeHtml(_rpStateLabel(data.state))
    + '</span>'
    + elapsedHtml
    + '</div>'
    + errorHtml
    + _rpFilesHtml(data.files)
    + _rpIntegrationHtml(data.integration)
    + '</div>';

  _rpRenderRunButton(container, data.state);
}

function _rpRenderEmpty(container) {
  container.innerHTML = '<div class="rp-empty">' + t('reviewPipeline.empty') + '</div>';
  _rpRenderRunButton(container, null);
}

function _rpRenderError(container) {
  container.innerHTML = '<div class="rp-fetch-error">' + t('reviewPipeline.error') + '</div>';
  _rpRenderRunButton(container, null);
}

function _rpCanRun(state) {
  if (state === null || state === undefined) return true;
  return state === 'done' || state === 'failed';
}

function _rpRenderRunButton(container, state) {
  var phase = container.dataset.workspacePhase || '';
  var workspaceId = container.dataset.workspaceId;
  if (!workspaceId) return;
  if (phase !== '4.0') return;
  if (!_rpCanRun(state)) return;

  var actions = document.createElement('div');
  actions.className = 'rp-actions';

  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-sm';
  btn.id = 'reviewPipelineRunBtn';
  btn.textContent = t('reviewPipeline.runButton');
  btn.onclick = function() { _rpHandleRunClick(container, workspaceId); };

  actions.appendChild(btn);
  container.appendChild(actions);
}

async function _rpHandleRunClick(container, workspaceId) {
  var confirmed = window.confirm(t('reviewPipeline.runConfirm'));
  if (!confirmed) return;
  var btn = container.querySelector('#reviewPipelineRunBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = t('reviewPipeline.runStarting');
  }
  try {
    await apiStartReviewPipeline(workspaceId);
    if (typeof showToast === 'function') {
      showToast(t('reviewPipeline.runStarted'));
    }
    _rpFetchAndRender(container, workspaceId);
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast(t('reviewPipeline.runFailed', { error: err.message }));
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = t('reviewPipeline.runButton');
    }
  }
}

function _rpStopPolling(workspaceId) {
  var timer = _rpPollingTimers[workspaceId];
  if (timer) {
    clearTimeout(timer);
    delete _rpPollingTimers[workspaceId];
  }
}

async function _rpFetchAndRender(container, workspaceId) {
  var url = '/api/workspaces/' + encodeURIComponent(workspaceId) + '/review-pipeline-status';
  var res;
  try {
    res = await fetch(url, { headers: _authHeaders ? _authHeaders() : {} });
  } catch (_err) {
    _rpRenderError(container);
    return;
  }

  if (res.status === 404) {
    _rpRenderEmpty(container);
    return;
  }

  if (!res.ok) {
    _rpRenderError(container);
    return;
  }

  var data;
  try {
    data = await res.json();
  } catch (_err) {
    _rpRenderError(container);
    return;
  }

  if (!data) {
    _rpRenderEmpty(container);
    return;
  }

  _rpRenderStatus(container, data);

  if (_RP_ACTIVE_STATES.has(data.state)) {
    _rpPollingTimers[workspaceId] = setTimeout(function() {
      _rpFetchAndRender(container, workspaceId);
    }, 2000);
  }
}

function renderReviewPipelineCard(container, workspaceId, options) {
  if (!container || !workspaceId) return;
  _rpStopPolling(workspaceId);
  container.dataset.workspaceId = String(workspaceId);
  container.dataset.workspacePhase = (options && options.phase) || '';
  container.innerHTML = '<div class="rp-loading">' + t('research.loading') + '</div>';
  _rpFetchAndRender(container, workspaceId);
}
