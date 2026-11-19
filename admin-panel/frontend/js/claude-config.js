// ═══════════════════════════════════════════════
//  CLAUDE COMMAND CONFIG
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
  body.innerHTML =
    '<div class="settings-row">' +
      '<div>' +
        '<div class="settings-row-label">' + escapeHtml(t('config.workflowModeLabel')) + '</div>' +
        '<div class="settings-row-desc">' + escapeHtml(t('config.workflowModeHint')) + '</div>' +
      '</div>' +
      '<div class="settings-row-control"><div class="seg" id="workflowModeSeg">' +
        _workflowModeOption('standard', t('header.modeStandard'), !isFast) +
        _workflowModeOption('fast', t('header.modeFast'), isFast) +
      '</div></div>' +
    '</div>';

  if (headerBadge) {
    headerBadge.textContent = isFast ? t('header.modeFast') : t('header.modeStandard');
    headerBadge.className = isFast ? 'pill warn' : 'pill line';
  }
}

function _workflowModeOption(mode, label, isActive) {
  return '<button type="button"' + (isActive ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') +
    ' onclick="onWorkflowModeOptionClick(\'' + mode + '\')">' + escapeHtml(label) + '</button>';
}

async function onWorkflowModeOptionClick(nextMode) {
  var ctx = getWorkspaceContext();
  var currentMode = LOCK_DATA.workflow_mode === 'fast' ? 'fast' : 'standard';
  if (!ctx || nextMode === currentMode) return;

  var confirmMessage = nextMode === 'fast' ? t('config.fastModeConfirm') : t('config.standardModeConfirm');
  if (!confirm(confirmMessage)) return;

  var seg = document.getElementById('workflowModeSeg');
  if (seg) seg.querySelectorAll('button').forEach(function(b) { b.disabled = true; });

  try {
    await apiSetWorkflowMode(ctx.projectId, ctx.branch, nextMode);
    await refreshState();
    showToast(t(nextMode === 'fast' ? 'messages.fastModeEnabled' : 'messages.fastModeDisabled'));
  } catch (e) {
    showToast(t('messages.failedToUpdate', {error: e.message}));
  } finally {
    renderWorkflowModeCard();
  }
}

EventBus.on('state:refreshed', renderWorkflowModeCard);

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
      return '<div class="inline-check inline-check--module">'
        + '<input type="checkbox" id="module-' + escapeHtml(mod.id) + '" data-module-id="' + escapeHtml(mod.id) + '" ' + checked + ' onchange="saveModuleToggle()">'
        + '<label for="module-' + escapeHtml(mod.id) + '">' + escapeHtml(mod.name) + '</label>'
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
  } catch (e) {
    if (typeof showToast === 'function') showToast('Failed to save: ' + e.message);
  }
}
