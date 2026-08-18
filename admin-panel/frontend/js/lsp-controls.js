// ===============================================
//  LSP CONTROLS (header indicator + profile cards)
// ===============================================

var _lspProfiles = [];
var _lspProjectPath = '';
var _lspPollingTimer = null;

var LSP_POLL_INTERVAL_ACTIVE_MS = 2000;
var LSP_POLL_INTERVAL_IDLE_MS = 10000;

// --- Data loading ---

function loadLspProfiles() {
  var ctx = getWorkspaceContext();
  if (!ctx) return Promise.resolve();

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/profiles';
  return apiGet(url).then(function(data) {
    _lspProfiles = (data && data.profiles) || [];
    _lspProjectPath = (data && data.project_path) || '';
    if (typeof updateLspLanguageMap === 'function') updateLspLanguageMap();
    _renderAllLspUi();

    var hasRunning = _lspProfiles.some(function(p) {
      return p.instance_status === 'running';
    });
    if (hasRunning && !isLspConnected()) {
      connectLsp();
    }
  }).catch(function(e) {
    console.warn('Failed to load LSP profiles:', e.message);
    _lspProfiles = [];
    _lspProjectPath = '';
    if (typeof updateLspLanguageMap === 'function') updateLspLanguageMap();
    renderLspHeaderIndicator();
  });
}

// --- Shared render helpers ---

function _renderAllLspUi() {
  renderLspHeaderIndicator();
  renderLspProfileCards();

  var dropdown = document.getElementById('lspDropdown');
  if (dropdown && dropdown.style.display === 'block') {
    renderLspDropdown();
  }
}

function _lspProfileStatus(p) {
  var status = p.instance_status || 'stopped';
  var validStatuses = ['running', 'stopped', 'starting', 'stopping', 'error'];
  return validStatuses.indexOf(status) === -1 ? 'stopped' : status;
}

function _lspIsTransitioning(status) {
  return status === 'starting' || status === 'stopping';
}

function _lspButtonLabel(status) {
  switch (status) {
    case 'starting': return t('lsp.button.starting');
    case 'stopping': return t('lsp.button.stopping');
    case 'running': return t('lsp.button.stop');
    case 'error': return t('lsp.button.retry');
    default: return t('lsp.button.start');
  }
}

function _lspButtonAction(status) {
  return (status === 'running' || status === 'stopping') ? 'stop' : 'start';
}

function _lspButtonClass(status) {
  return _lspButtonAction(status) === 'stop' ? 'stop' : 'start';
}

function _lspButtonHtml(profileId, status, extraAttrs) {
  var action = _lspButtonAction(status);
  var handler = action === 'stop' ? 'stopLspServer' : 'startLspServer';
  var disabled = _lspIsTransitioning(status);
  return '<button class="lsp-btn ' + _lspButtonClass(status) + '"'
    + (disabled ? ' disabled' : '')
    + ' onclick="' + handler + '(' + profileId + ')' + (extraAttrs || '') + '">'
    + escapeHtml(_lspButtonLabel(status))
    + '</button>';
}

function _lspErrorLineHtml(status, errorMessage) {
  if (status !== 'error' || !errorMessage) return '';
  return '<div class="lsp-dropdown-error lsp-dropdown-error-sticky">'
    + escapeHtml(t('lsp.errorPrefix')) + escapeHtml(errorMessage)
    + '</div>';
}

// --- Header indicator ---

function renderLspHeaderIndicator() {
  var indicator = document.getElementById('lspIndicator');
  if (!indicator) return;
  var wrapper = indicator.closest('.lsp-control');

  if (_lspProfiles.length === 0) {
    indicator.style.display = 'none';
    if (wrapper) wrapper.style.display = 'none';
    return;
  }

  indicator.style.display = '';
  if (wrapper) wrapper.style.display = '';

  var running = 0;
  var errors = 0;
  var starting = 0;
  var stopping = 0;
  var total = _lspProfiles.length;

  _lspProfiles.forEach(function(p) {
    var status = _lspProfileStatus(p);
    if (status === 'running') running++;
    else if (status === 'error') errors++;
    else if (status === 'starting') starting++;
    else if (status === 'stopping') stopping++;
  });

  indicator.className = 'btn btn-sm';

  if (errors > 0) {
    indicator.classList.add('lsp-status-error');
  } else if (starting > 0 || stopping > 0) {
    indicator.classList.add('lsp-status-partial');
  } else if (running === 0) {
    indicator.classList.add('lsp-status-off');
  } else if (running === total) {
    indicator.classList.add('lsp-status-running');
  } else {
    indicator.classList.add('lsp-status-partial');
  }

  if (starting > 0) {
    indicator.textContent = t('lsp.headerIndicator.starting', {running: running, total: total, count: starting});
  } else if (stopping > 0) {
    indicator.textContent = t('lsp.headerIndicator.stopping', {running: running, total: total, count: stopping});
  } else {
    indicator.textContent = t('lsp.headerIndicator.default', {running: running, total: total});
  }
  indicator.title = t('lsp.headerIndicator.title', {running: running, total: total});
}

// --- Dropdown ---

function toggleLspDropdown() {
  var dropdown = document.getElementById('lspDropdown');
  if (!dropdown) return;

  if (dropdown.style.display === 'none' || !dropdown.style.display) {
    renderLspDropdown();
    dropdown.style.display = 'block';
    loadLspProfiles();

    setTimeout(function() {
      document.addEventListener('click', _closeLspDropdownOnOutsideClick);
    }, 10);
  } else {
    dropdown.style.display = 'none';
    document.removeEventListener('click', _closeLspDropdownOnOutsideClick);
  }
}

function _closeLspDropdownOnOutsideClick(e) {
  if (!e.target.closest('.lsp-control')) {
    var dropdown = document.getElementById('lspDropdown');
    if (dropdown) dropdown.style.display = 'none';
    document.removeEventListener('click', _closeLspDropdownOnOutsideClick);
  }
}

function renderLspDropdown() {
  var dropdown = document.getElementById('lspDropdown');
  if (!dropdown) return;

  var html = '<div class="lsp-dropdown-header">' + escapeHtml(t('lsp.dropdownHeader')) + '</div>';

  if (_lspProfiles.length === 0) {
    html += '<div style="padding: 8px; font-size: 12px; color: var(--text-muted);">' + escapeHtml(t('lsp.noProfilesConfigured')) + '</div>';
    dropdown.innerHTML = html;
    return;
  }

  var anyStarting = false;
  var anyStopping = false;

  _lspProfiles.forEach(function(p) {
    var status = _lspProfileStatus(p);
    if (status === 'starting') anyStarting = true;
    if (status === 'stopping') anyStopping = true;

    var safeProfileId = parseInt(p.profile_id, 10);
    if (isNaN(safeProfileId)) return;

    html += '<div class="lsp-dropdown-item">'
      + '<div>'
      + '<span class="lsp-server-name">' + escapeHtml(p.name) + '</span>'
      + ' <span class="lsp-server-lang">' + escapeHtml(p.language) + '</span>'
      + '</div>'
      + '<span class="lsp-server-status ' + status + '">' + escapeHtml(t('lsp.status.' + status)) + '</span>'
      + _lspButtonHtml(safeProfileId, status, '; event.stopPropagation();')
      + '</div>';

    html += _lspErrorLineHtml(status, p.error_message);
  });

  var startAllDisabled = anyStarting;
  var stopAllDisabled = anyStopping;
  var startAllLabel = anyStarting ? t('lsp.button.starting') : t('lsp.button.startAll');
  var stopAllLabel = anyStopping ? t('lsp.button.stopping') : t('lsp.button.stopAll');

  html += '<div class="lsp-dropdown-actions">'
    + '<button class="lsp-btn start"' + (startAllDisabled ? ' disabled' : '')
    + ' onclick="startAllLsp(); event.stopPropagation();">' + escapeHtml(startAllLabel) + '</button>'
    + '<button class="lsp-btn stop"' + (stopAllDisabled ? ' disabled' : '')
    + ' onclick="stopAllLsp(); event.stopPropagation();">' + escapeHtml(stopAllLabel) + '</button>'
    + '</div>';

  dropdown.innerHTML = html;
}

// --- LSP sections in verification profile cards ---

function renderLspProfileCards() {
  if (_lspProfiles.length === 0) return;

  var lspByAssignmentId = {};
  _lspProfiles.forEach(function(p) {
    lspByAssignmentId[p.assignment_id] = p;
  });

  var cards = document.querySelectorAll('.verification-profile-card');
  cards.forEach(function(card) {
    var removeBtn = card.querySelector('.verification-profile-header button');
    if (!removeBtn) return;

    var onclickAttr = removeBtn.getAttribute('onclick') || '';
    var match = onclickAttr.match(/unassignVerificationProfile\((\d+)\)/);
    if (!match) return;

    var assignmentId = parseInt(match[1]);
    var lspProfile = lspByAssignmentId[assignmentId] || null;

    var existing = card.querySelector('.lsp-profile-section');
    if (existing) existing.remove();

    if (!lspProfile) return;

    var status = _lspProfileStatus(lspProfile);
    var safeProfileId = parseInt(lspProfile.profile_id, 10);
    if (isNaN(safeProfileId)) return;

    var section = document.createElement('div');
    section.className = 'lsp-profile-section';

    var toggleChecked = lspProfile.lsp_enabled ? ' checked' : '';

    section.innerHTML = '<div class="lsp-info">'
      + '<div class="lsp-info-left">'
      + '<span class="lsp-server-status ' + status + '">' + escapeHtml(t('lsp.status.' + status)) + '</span>'
      + _lspButtonHtml(safeProfileId, status)
      + '</div>'
      + '<label class="lsp-toggle-label">'
      + '<input type="checkbox"' + toggleChecked + ' onchange="toggleLspProfile(' + safeProfileId + ', this.checked)">'
      + ' ' + escapeHtml(t('lsp.profileToggleLabel'))
      + '</label>'
      + '</div>'
      + '<div class="lsp-command">' + escapeHtml(lspProfile.lsp_command + (lspProfile.lsp_args ? ' ' + lspProfile.lsp_args : '')) + '</div>'
      + _lspErrorLineHtml(status, lspProfile.error_message);

    card.appendChild(section);
  });
}

// --- Server lifecycle ---

function _setOptimisticLspStatus(matchesProfile, status) {
  _lspProfiles.forEach(function(p) {
    if (matchesProfile(p)) p.instance_status = status;
  });
  _renderAllLspUi();
  _rescheduleLspPolling();
}

function startLspServer(profileId) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  _setOptimisticLspStatus(function(p) {
    return parseInt(p.profile_id, 10) === profileId;
  }, 'starting');

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/start';
  apiPost(url, { profile_id: profileId }).catch(function(e) {
    if (typeof showToast === 'function') showToast(t('lsp.toast.startFailed', {message: e.message}));
    loadLspProfiles();
  });
}

function stopLspServer(profileId) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  _setOptimisticLspStatus(function(p) {
    return parseInt(p.profile_id, 10) === profileId;
  }, 'stopping');

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/stop';
  apiPost(url, { profile_id: profileId }).catch(function(e) {
    if (typeof showToast === 'function') showToast(t('lsp.toast.stopFailed', {message: e.message}));
    loadLspProfiles();
  });
}

function startAllLsp() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  _setOptimisticLspStatus(function(p) {
    return !!p.lsp_enabled;
  }, 'starting');

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/start';
  apiPost(url, {}).catch(function(e) {
    if (typeof showToast === 'function') showToast(t('lsp.toast.startAllFailed', {message: e.message}));
    loadLspProfiles();
  });
}

function stopAllLsp() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  _setOptimisticLspStatus(function(p) {
    return p.instance_status === 'running';
  }, 'stopping');

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/stop';
  apiPost(url, {}).then(function() {
    disconnectLsp();
  }).catch(function(e) {
    if (typeof showToast === 'function') showToast(t('lsp.toast.stopAllFailed', {message: e.message}));
    loadLspProfiles();
  });
}

function toggleLspProfile(profileId, enabled) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/profiles/' + profileId + '/toggle';
  apiPut(url, { enabled: enabled }).then(function() {
    loadLspProfiles();
  }).catch(function(e) {
    if (typeof showToast === 'function') showToast(t('lsp.toast.toggleFailed', {message: e.message}));
    loadLspProfiles();
  });
}

// --- Polling ---

function _lspHasTransitioningProfile() {
  return _lspProfiles.some(function(p) {
    return _lspIsTransitioning(_lspProfileStatus(p));
  });
}

function _lspPollIntervalMs() {
  return _lspHasTransitioningProfile() ? LSP_POLL_INTERVAL_ACTIVE_MS : LSP_POLL_INTERVAL_IDLE_MS;
}

function _rescheduleLspPolling() {
  if (!_lspPollingTimer) return;
  clearTimeout(_lspPollingTimer);
  _lspPollingTimer = setTimeout(_pollLspStatusOnce, _lspPollIntervalMs());
}

function _pollLspStatusOnce() {
  var ctx = getWorkspaceContext();
  if (!ctx) {
    _lspPollingTimer = setTimeout(_pollLspStatusOnce, _lspPollIntervalMs());
    return;
  }

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/lsp/status';
  apiGet(url).then(function(statuses) {
    if (!Array.isArray(statuses)) return;

    var statusMap = {};
    statuses.forEach(function(s) {
      statusMap[s.profile_id] = s;
    });

    _lspProfiles.forEach(function(p) {
      var updated = statusMap[p.profile_id];
      if (updated) {
        p.instance_status = updated.status;
        p.error_message = updated.error_message;
        p.pid = updated.pid;
      }
    });

    _renderAllLspUi();
  }).catch(function(e) {
    console.warn('lsp-controls status polling failed:', e && e.message);
  }).then(function() {
    _lspPollingTimer = setTimeout(_pollLspStatusOnce, _lspPollIntervalMs());
  });
}

function startLspPolling() {
  stopLspPolling();
  _lspPollingTimer = setTimeout(_pollLspStatusOnce, _lspPollIntervalMs());
}

function stopLspPolling() {
  if (_lspPollingTimer) {
    clearTimeout(_lspPollingTimer);
    _lspPollingTimer = null;
  }
}
