// ═══════════════════════════════════════════════
//  SETTINGS PAGE (panel-dashboard)
// ═══════════════════════════════════════════════
var SETTINGS_SECTIONS = ['task', 'workflow', 'verification', 'rules', 'git', 'claude', 'system', 'interface'];
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
