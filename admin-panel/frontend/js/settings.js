// ═══════════════════════════════════════════════
//  SETTINGS PAGE (panel-dashboard)
// ═══════════════════════════════════════════════
var SETTINGS_SECTIONS = ['task', 'workflow', 'phases', 'review', 'verification', 'rules', 'git', 'claude', 'system', 'interface'];
var SETTINGS_DEFAULT_SECTION = 'task';

function _currentSettingsSection() {
  var parts = location.hash.slice(1).split('/');
  var section = parts[0] === 'dashboard' ? parts[1] : null;
  return (section && SETTINGS_SECTIONS.indexOf(section) !== -1) ? section : SETTINGS_DEFAULT_SECTION;
}

function switchSettingsSection(section) {
  if (SETTINGS_SECTIONS.indexOf(section) === -1) return;
  history.replaceState(null, '', '#dashboard/' + section);
  settingsOnActivate();
}

function _loadSettingsSectionData(section) {
  if (section === 'task') {
    if (typeof renderContext === 'function') renderContext();
  } else if (section === 'workflow') {
    if (typeof renderWorkflowModeCard === 'function') renderWorkflowModeCard();
    _syncYoloCheckboxes();
    loadWorkflowProjectSettings();
  } else if (section === 'phases') {
    loadPhasesSection();
  } else if (section === 'review') {
    loadReviewSection();
  } else if (section === 'verification') {
    if (typeof loadVerificationData === 'function') loadVerificationData();
  } else if (section === 'rules') {
    if (typeof loadRules === 'function') loadRules();
    if (typeof loadGitRules === 'function') loadGitRules();
  } else if (section === 'git') {
    if (typeof loadGitConfig === 'function') loadGitConfig();
  } else if (section === 'claude') {
    if (typeof loadClaudeCommand === 'function') loadClaudeCommand();
  } else if (section === 'system') {
    if (typeof loadModulesCard === 'function') loadModulesCard();
    if (typeof renderNetworkMode === 'function') renderNetworkMode();
  } else if (section === 'interface') {
    if (typeof renderLspShortcutsConfig === 'function') renderLspShortcutsConfig();
  }
}

// Refreshes the active settings section's data and syncs the nav/section
// highlight from the URL hash. Called both when the Settings tab is
// activated and whenever the section changes.
function settingsOnActivate() {
  var section = _currentSettingsSection();

  document.querySelectorAll('.settings-nav-item').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.section === section);
  });
  document.querySelectorAll('.settings-section').forEach(function(el) {
    el.classList.toggle('active', el.dataset.section === section);
  });

  _loadSettingsSectionData(section);
}

function initSettingsNav() {
  document.querySelectorAll('.settings-nav-item').forEach(function(btn) {
    btn.addEventListener('click', function() { switchSettingsSection(btn.dataset.section); });
  });
}

document.addEventListener('DOMContentLoaded', initSettingsNav);

// ═══════════════════════════════════════════════
//  YOLO checkbox mirroring (header + settings)
// ═══════════════════════════════════════════════
function onYoloCheckboxChange(checked, sourceId) {
  ['yoloCheck', 'settingsYoloCheck'].forEach(function(id) {
    if (id === sourceId) return;
    var el = document.getElementById(id);
    if (el) el.checked = checked;
  });
  toggleYoloMode(checked);
}

function _syncYoloCheckboxes() {
  var settingsCheck = document.getElementById('settingsYoloCheck');
  var headerCheck = document.getElementById('yoloCheck');
  if (settingsCheck && headerCheck) settingsCheck.checked = headerCheck.checked;
}

EventBus.on('state:refreshed', _syncYoloCheckboxes);

// ═══════════════════════════════════════════════
//  INLINE SAVE FLASH
// ═══════════════════════════════════════════════
function _flashSettingsInline(elementId) {
  var el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = t('settings.saved');
  el.classList.add('settings-inline-flash--visible');
  clearTimeout(el._settingsFlashTimer);
  el._settingsFlashTimer = setTimeout(function() {
    el.classList.remove('settings-inline-flash--visible');
  }, 1500);
}

// ═══════════════════════════════════════════════
//  PROJECT SETTINGS CACHE (simple_planning, fast_mode_default, review_mode_default)
// ═══════════════════════════════════════════════
// The PUT /api/projects/<id>/settings endpoint requires simple_planning on
// every call, so any single-field toggle here must merge against the last
// known full settings object rather than sending a partial payload.
var _settingsProjectCache = null;

document.addEventListener('workspace-reset', function() { _settingsProjectCache = null; });

async function _fetchSettingsProjectCache(projectId) {
  try {
    _settingsProjectCache = await apiGet('/api/projects/' + encodeURIComponent(projectId) + '/settings');
  } catch (e) {
    _settingsProjectCache = null;
  }
  return _settingsProjectCache;
}

async function _putSettingsProjectCache(projectId, patch) {
  var current = _settingsProjectCache || await _fetchSettingsProjectCache(projectId) || {};
  var payload = {
    simple_planning: !!current.simple_planning,
    fast_mode_default: !!current.fast_mode_default,
    review_mode_default: current.review_mode_default || 'files_integration'
  };
  Object.assign(payload, patch);

  var result = await apiPut('/api/projects/' + encodeURIComponent(projectId) + '/settings', payload);
  _settingsProjectCache = Object.assign({}, current, patch);
  return result;
}

// ═══════════════════════════════════════════════
//  WORKFLOW SECTION — project defaults + advance modes
// ═══════════════════════════════════════════════
function loadWorkflowProjectSettings() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  _fetchSettingsProjectCache(ctx.projectId).then(function(settings) {
    if (!settings) return;
    var simpleCheck = document.getElementById('settingsSimplePlanningCheck');
    var fastCheck = document.getElementById('settingsFastModeDefaultCheck');
    if (simpleCheck) simpleCheck.checked = !!settings.simple_planning;
    if (fastCheck) fastCheck.checked = !!settings.fast_mode_default;
  });

  var advanceModesBody = document.getElementById('advanceModesSettingsBody');
  if (advanceModesBody && typeof renderAdvanceModeSection === 'function') {
    renderAdvanceModeSection(advanceModesBody, ctx.projectId);
  }
}

async function onSettingsSimplePlanningChange(checkbox) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var previous = !checkbox.checked;
  checkbox.disabled = true;
  try {
    await _putSettingsProjectCache(ctx.projectId, { simple_planning: checkbox.checked });
    _flashSettingsInline('settingsSimplePlanningFlash');
  } catch (e) {
    checkbox.checked = previous;
    showToast(t('messages.phaseSettingsSaveFailed').replace('{error}', e.message));
  } finally {
    checkbox.disabled = false;
  }
}

async function onSettingsFastModeDefaultChange(checkbox) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var previous = !checkbox.checked;
  checkbox.disabled = true;
  try {
    await _putSettingsProjectCache(ctx.projectId, { fast_mode_default: checkbox.checked });
    _flashSettingsInline('settingsFastModeDefaultFlash');
  } catch (e) {
    checkbox.checked = previous;
    showToast(t('messages.phaseSettingsSaveFailed').replace('{error}', e.message));
  } finally {
    checkbox.disabled = false;
  }
}

// ═══════════════════════════════════════════════
//  PHASES SECTION — device defaults + project toggles
// ═══════════════════════════════════════════════
function loadPhasesSection() {
  var deviceBody = document.getElementById('phaseSettingsDeviceBody');
  if (deviceBody && typeof renderPhaseToggleCard === 'function') {
    renderPhaseToggleCard(deviceBody, 'device', '/api/phase-settings/device');
  }

  var ctx = getWorkspaceContext();
  var projectBody = document.getElementById('phaseSettingsSectionProjectBody');
  if (projectBody && ctx && typeof renderPhaseToggleCard === 'function') {
    renderPhaseToggleCard(
      projectBody,
      'project',
      '/api/projects/' + encodeURIComponent(ctx.projectId) + '/phase-settings',
      { batchSave: true }
    );
  }
}

// ═══════════════════════════════════════════════
//  REVIEW SECTION — workspace review mode + project default
// ═══════════════════════════════════════════════
var REVIEW_MODES = [
  { value: 'manual', labelKey: 'reviewMode.manual.label', descKey: 'reviewMode.manual.desc' },
  { value: 'integration', labelKey: 'reviewMode.integration.label', descKey: 'reviewMode.integration.desc' },
  { value: 'files_integration', labelKey: 'reviewMode.filesIntegration.label', descKey: 'reviewMode.filesIntegration.desc' },
  { value: 'full', labelKey: 'reviewMode.full.label', descKey: 'reviewMode.full.desc' }
];

function _reviewModeCardsHtml(selectedValue) {
  return REVIEW_MODES.map(function(mode) {
    var isSelected = mode.value === selectedValue;
    return '<button type="button" class="settings-radio-card' + (isSelected ? ' settings-radio-card--selected' : '') + '"'
      + ' data-mode="' + mode.value + '" onclick="onWorkspaceReviewModeClick(this)">'
      + '<div class="settings-radio-card-title">' + escapeHtml(t(mode.labelKey)) + '</div>'
      + '<div class="settings-radio-card-desc">' + escapeHtml(t(mode.descKey)) + '</div>'
      + '</button>';
  }).join('');
}

function _reviewModeSelectOptionsHtml(selectedValue) {
  return REVIEW_MODES.map(function(mode) {
    var selected = mode.value === selectedValue ? ' selected' : '';
    return '<option value="' + mode.value + '"' + selected + '>' + escapeHtml(t(mode.labelKey)) + '</option>';
  }).join('');
}

function renderWorkspaceReviewModeGroup() {
  var container = document.getElementById('reviewModeWorkspaceGroup');
  if (!container) return;
  container.innerHTML = _reviewModeCardsHtml(LOCK_DATA.review_mode || 'files_integration');
}

async function onWorkspaceReviewModeClick(btn) {
  var mode = btn.getAttribute('data-mode');
  var ctx = getWorkspaceContext();
  if (!ctx || mode === LOCK_DATA.review_mode) return;

  var previous = LOCK_DATA.review_mode;
  LOCK_DATA.review_mode = mode;
  renderWorkspaceReviewModeGroup();

  try {
    await apiSetReviewMode(ctx.projectId, ctx.branch, mode);
    _flashSettingsInline('reviewModeFlash');
  } catch (e) {
    LOCK_DATA.review_mode = previous;
    renderWorkspaceReviewModeGroup();
    showToast(t('messages.failedToUpdate', { error: e.message }));
  }
}

async function loadReviewModeProjectDefault() {
  var select = document.getElementById('reviewModeProjectDefaultSelect');
  var ctx = getWorkspaceContext();
  if (!select || !ctx) return;

  var settings = await _fetchSettingsProjectCache(ctx.projectId);
  select.innerHTML = _reviewModeSelectOptionsHtml(settings ? settings.review_mode_default : 'files_integration');
}

async function onReviewModeProjectDefaultChange(select) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var newValue = select.value;
  select.disabled = true;
  try {
    await _putSettingsProjectCache(ctx.projectId, { review_mode_default: newValue });
    _flashSettingsInline('reviewModeProjectDefaultFlash');
  } catch (e) {
    await loadReviewModeProjectDefault();
    showToast(t('messages.failedToUpdate', { error: e.message }));
  } finally {
    select.disabled = false;
  }
}

function loadReviewSection() {
  renderWorkspaceReviewModeGroup();
  loadReviewModeProjectDefault();
}

EventBus.on('state:refreshed', function() {
  if (_currentSettingsSection() === 'review') renderWorkspaceReviewModeGroup();
});
