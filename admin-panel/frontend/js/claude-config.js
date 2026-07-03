// ═══════════════════════════════════════════════
//  CLAUDE COMMAND & CHANNELS CONFIG
// ═══════════════════════════════════════════════

function loadClaudeCommand() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/command')
    .then(function(data) {
      var input = document.getElementById('claudeCommandInput');
      var checkbox = document.getElementById('skipPermissionsCheck');
      if (input) input.value = data.claude_command || 'claude';
      if (checkbox) checkbox.checked = data.skip_permissions !== false;
      if (data.restrict_to_workspace !== undefined) {
        var restrictCheckbox = document.getElementById('restrictToWorkspaceCheck');
        if (restrictCheckbox) restrictCheckbox.checked = data.restrict_to_workspace;
      }
      var pathsInput = document.getElementById('allowedExternalPathsInput');
      if (pathsInput) pathsInput.value = data.allowed_external_paths || '/tmp/';
      var envInput = document.getElementById('envVarsInput');
      if (envInput) envInput.value = data.env_vars || '';
    })
    .catch(function(e) { console.warn('claude-config loadClaudeCommand failed:', e && e.message); });
}

function saveClaudeCommand() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var input = document.getElementById('claudeCommandInput');
  var checkbox = document.getElementById('skipPermissionsCheck');
  var restrictCheck = document.getElementById('restrictToWorkspaceCheck');
  var pathsInput = document.getElementById('allowedExternalPathsInput');
  var envInput = document.getElementById('envVarsInput');

  var cmd = input ? input.value.trim() : 'claude';
  var skip = checkbox ? checkbox.checked : true;

  apiPut('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/command', {
    claude_command: cmd,
    skip_permissions: skip,
    restrict_to_workspace: restrictCheck ? restrictCheck.checked : true,
    allowed_external_paths: pathsInput ? pathsInput.value.trim() : '/tmp/',
    env_vars: envInput ? envInput.value : ''
  })
  .then(function(data) {
    if (data.ok) {
      var btn = document.querySelector('[onclick="saveClaudeCommand()"]');
      if (btn) {
        var original = btn.textContent;
        btn.textContent = t('actions.copied') || 'Saved!';
        setTimeout(function() { btn.textContent = original; }, 1500);
      }
    }
  })
  .catch(function(e) {
    showToast('Save failed: ' + e.message);
  });
}

// ═══════════════════════════════════════════════
//  WORKFLOW MODE (dashboard)
// ═══════════════════════════════════════════════

function renderWorkflowModeCard() {
  var body = document.getElementById('workflowModeCardBody');
  var headerBadge = document.getElementById('headerWorkflowModeBadge');
  if (!body) return;

  var isFast = LOCK_DATA.workflow_mode === 'fast';
  var badgeHtml = isFast
    ? '<span class="badge badge-warning">' + escapeHtml(t('badges.fastMode')) + '</span>'
    : '<span class="badge" style="background:var(--bg-raised);color:var(--text-secondary);">' + escapeHtml(t('badges.standardMode')) + '</span>';
  var toggleLabel = isFast ? t('buttons.switchToStandard') : t('buttons.switchToFast');

  body.innerHTML =
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">' + badgeHtml + '</div>' +
    '<p style="margin:0 0 10px;color:var(--text-muted);font-size:0.78rem;">' + escapeHtml(t('config.workflowModeHint')) + '</p>' +
    '<div style="display:flex;justify-content:flex-end;">' +
      '<button class="btn btn-sm" id="workflowModeToggleBtn" onclick="onWorkflowModeToggleClick()">' + escapeHtml(toggleLabel) + '</button>' +
    '</div>';

  if (headerBadge) {
    if (isFast) {
      headerBadge.textContent = t('badges.fastMode');
      headerBadge.style.display = '';
    } else {
      headerBadge.style.display = 'none';
    }
  }
}

async function onWorkflowModeToggleClick() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var nextMode = LOCK_DATA.workflow_mode === 'fast' ? 'standard' : 'fast';
  var confirmMessage = nextMode === 'fast' ? t('config.fastModeConfirm') : t('config.standardModeConfirm');
  if (!confirm(confirmMessage)) return;

  var btn = document.getElementById('workflowModeToggleBtn');
  if (btn) btn.disabled = true;

  try {
    await apiSetWorkflowMode(ctx.projectId, ctx.branch, nextMode);
    await refreshState();
    renderWorkflowModeCard();
    showToast(t(nextMode === 'fast' ? 'messages.fastModeEnabled' : 'messages.fastModeDisabled'));
  } catch (e) {
    showToast(t('messages.failedToUpdate', {error: e.message}));
  } finally {
    if (btn) btn.disabled = false;
  }
}

EventBus.on('state:refreshed', renderWorkflowModeCard);

function loadChannelsPreference() {
  var defaultValue = 'plugin:telegram@claude-plugins-official';
  var enabled = localStorage.getItem('channels_enabled') === 'true';
  var value = localStorage.getItem('channels_value') || defaultValue;
  localStorage.setItem('channels_enabled', enabled ? 'true' : 'false');
  localStorage.setItem('channels_value', value);
}

// ═══════════════════════════════════════════════
//  MODULES CARD (dashboard)
// ═══════════════════════════════════════════════

async function loadModulesCard() {
  var card = document.getElementById('modulesCard');
  var body = document.getElementById('modulesCardBody');
  if (!card || !body) return;

  try {
    var modulesData = await apiGet('/api/modules');
    var enabledData = await apiGet('/api/modules/enabled');
    var modules = modulesData.modules || [];
    var enabledIds = enabledData.modules || [];

    if (modules.length === 0) {
      card.style.display = 'none';
      return;
    }

    card.style.display = '';
    var enabledSet = {};
    enabledIds.forEach(function(id) { enabledSet[id] = true; });

    var html = modules.map(function(mod) {
      var checked = enabledSet[mod.id] ? 'checked' : '';
      return '<div style="display: flex; align-items: center; gap: 8px; padding: 4px 0;">'
        + '<input type="checkbox" id="module-' + escapeHtml(mod.id) + '" data-module-id="' + escapeHtml(mod.id) + '" ' + checked + ' onchange="saveModuleToggle()">'
        + '<label for="module-' + escapeHtml(mod.id) + '" style="font-size: 0.82rem; color: var(--text-primary); cursor: pointer;">' + escapeHtml(mod.name) + '</label>'
        + '</div>';
    }).join('');

    body.innerHTML = html;
  } catch (e) {
    console.warn('Failed to load modules card:', e.message);
    card.style.display = 'none';
  }
}

async function saveModuleToggle() {
  var checkboxes = document.querySelectorAll('#modulesCardBody input[type="checkbox"]');
  var enabled = [];
  checkboxes.forEach(function(cb) {
    if (cb.checked) enabled.push(cb.getAttribute('data-module-id'));
  });

  try {
    await apiPost('/api/modules/enabled', { modules: enabled });

    // Update channels preference for backward compatibility
    var telegramEnabled = enabled.indexOf('telegram') !== -1;
    localStorage.setItem('channels_enabled', telegramEnabled ? 'true' : 'false');
    if (telegramEnabled) {
      localStorage.setItem('channels_value', 'plugin:telegram@claude-plugins-official');
    }
  } catch (e) {
    if (typeof showToast === 'function') showToast('Failed to save: ' + e.message);
  }
}
