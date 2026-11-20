// ═══════════════════════════════════════════════
//  SETTINGS — KEYBOARD SHORTCUTS SECTION
// ═══════════════════════════════════════════════
var _recordingShortcutActionId = null;
var _shortcutRowErrors = {};

function renderShortcutsSettings() {
  var list = document.getElementById('shortcutsSettingsList');
  if (!list) return;
  var bindings = _currentShortcutBindings();
  list.innerHTML = SHORTCUT_ACTIONS.map(function(action) {
    return _shortcutRowHtml(action, bindings);
  }).join('');
}

function _currentShortcutBindings() {
  var bindings = {};
  SHORTCUT_ACTIONS.forEach(function(action) { bindings[action.id] = getShortcutCombo(action.id); });
  return bindings;
}

function _shortcutRowHtml(action, bindings) {
  var combo = bindings[action.id];
  var isRecording = _recordingShortcutActionId === action.id;
  return '<div class="settings-row shortcut-row' + (isRecording ? ' shortcut-row--recording' : '') + '" data-action="' + action.id + '">'
    + '<div class="shortcut-row-text">'
    + '<div class="settings-row-label">' + escapeHtml(t(action.labelKey)) + '</div>'
    + '<div class="settings-row-desc">' + escapeHtml(t('shortcuts.default', { combo: formatShortcutCombo(action.defaultCombo) })) + '</div>'
    + _shortcutRowMessageHtml(action, bindings)
    + '</div>'
    + '<div class="settings-row-control shortcut-row-control">'
    + '<kbd class="shortcut-combo' + (combo ? '' : ' shortcut-combo--unset') + '">' + escapeHtml(_shortcutComboText(combo, isRecording)) + '</kbd>'
    + '<button type="button" class="btn xs" data-shortcut-op="record">' + escapeHtml(t(isRecording ? 'buttons.cancel' : 'shortcuts.record')) + '</button>'
    + '<button type="button" class="btn xs" data-shortcut-op="clear"' + (combo ? '' : ' disabled') + '>' + escapeHtml(t('shortcuts.clear')) + '</button>'
    + '<button type="button" class="btn xs" data-shortcut-op="reset"' + (combo === action.defaultCombo ? ' disabled' : '') + '>' + escapeHtml(t('shortcuts.reset')) + '</button>'
    + '</div>'
    + '</div>';
}

function _shortcutComboText(combo, isRecording) {
  if (isRecording) return t('shortcuts.recording');
  return combo ? formatShortcutCombo(combo) : t('shortcuts.unbound');
}

function _shortcutRowMessageHtml(action, bindings) {
  var error = _shortcutRowErrors[action.id];
  if (error) return '<div class="shortcut-row-msg shortcut-row-msg--error" role="alert">' + escapeHtml(error) + '</div>';
  var sharing = _actionsSharingCombo(action.id, bindings);
  if (!sharing.length) return '';
  var labels = sharing.map(function(other) { return t(other.labelKey); }).join(', ');
  return '<div class="shortcut-row-msg shortcut-row-msg--warn" role="status">' + escapeHtml(t('shortcuts.duplicate', { actions: labels })) + '</div>';
}

function _actionsSharingCombo(actionId, bindings) {
  var combo = bindings[actionId];
  if (!combo) return [];
  return SHORTCUT_ACTIONS.filter(function(other) { return other.id !== actionId && bindings[other.id] === combo; });
}

function _onShortcutsListClick(e) {
  var button = e.target.closest('[data-shortcut-op]');
  if (!button) return;
  var actionId = button.closest('.shortcut-row').dataset.action;
  var op = button.dataset.shortcutOp;
  delete _shortcutRowErrors[actionId];
  if (op === 'record') {
    _toggleShortcutRecording(actionId);
    return;
  }
  _stopShortcutRecording();
  if (op === 'clear') setShortcutCombo(actionId, '');
  if (op === 'reset') resetShortcutCombo(actionId);
  renderShortcutsSettings();
}

function _toggleShortcutRecording(actionId) {
  var wasRecordingThisRow = _recordingShortcutActionId === actionId;
  _stopShortcutRecording();
  if (!wasRecordingThisRow) {
    _recordingShortcutActionId = actionId;
    setShortcutRecording(true);
    window.addEventListener('keydown', _onShortcutRecordKeydown, true);
    window.addEventListener('mousedown', _onShortcutRecordMousedown, true);
  }
  renderShortcutsSettings();
}

function _stopShortcutRecording() {
  if (!_recordingShortcutActionId) return;
  _recordingShortcutActionId = null;
  setShortcutRecording(false);
  window.removeEventListener('keydown', _onShortcutRecordKeydown, true);
  window.removeEventListener('mousedown', _onShortcutRecordMousedown, true);
}

function _onShortcutRecordKeydown(e) {
  e.preventDefault();
  e.stopPropagation();
  var actionId = _recordingShortcutActionId;
  var isPlainEscape = e.code === 'Escape' && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey;
  if (isPlainEscape) {
    delete _shortcutRowErrors[actionId];
    _stopShortcutRecording();
    renderShortcutsSettings();
    return;
  }
  var combo = shortcutComboFromEvent(e);
  if (!combo) return;
  var errorKey = shortcutComboError(combo);
  if (errorKey) {
    _shortcutRowErrors[actionId] = t(errorKey, { combo: formatShortcutCombo(combo) });
  } else {
    delete _shortcutRowErrors[actionId];
    setShortcutCombo(actionId, combo);
    _stopShortcutRecording();
  }
  renderShortcutsSettings();
}

// Clicking anywhere outside the shortcuts list abandons the recording, so keys
// are never silently swallowed after the user has moved on. Clicks inside the
// list are left to its own buttons.
function _onShortcutRecordMousedown(e) {
  if (e.target.closest && e.target.closest('#shortcutsSettingsList')) return;
  delete _shortcutRowErrors[_recordingShortcutActionId];
  _stopShortcutRecording();
  renderShortcutsSettings();
}

document.addEventListener('DOMContentLoaded', function() {
  var list = document.getElementById('shortcutsSettingsList');
  if (list) list.addEventListener('click', _onShortcutsListClick);
});
