// ═══════════════════════════════════════════════
//  KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════
// A combo is "<modifiers>+<KeyboardEvent.code>", e.g. "Ctrl+Alt+KeyT". Matching
// on the physical key keeps shortcuts working under the Mac Option key (which
// rewrites event.key) and non-Latin layouts such as Russian.
var SHORTCUTS_STORAGE_KEY = 'ui_shortcuts';
var SHORTCUT_MODIFIERS = ['Ctrl', 'Alt', 'Shift', 'Meta'];

var SHORTCUT_ACTIONS = [
  { id: 'toggleTerminal', labelKey: 'shortcuts.action.toggleTerminal', defaultCombo: 'Ctrl+Alt+KeyT', run: function() { toggleTerminal(); } },
  { id: 'switchTerminalMode', labelKey: 'shortcuts.action.switchTerminalMode', defaultCombo: 'Ctrl+Alt+Shift+Enter', run: function() { switchTerminalMode(); } },
  { id: 'openChanges', labelKey: 'shortcuts.action.openChanges', defaultCombo: 'Ctrl+Alt+Shift+KeyC', run: function() { switchTab('changes'); } },
  { id: 'openScratchpads', labelKey: 'shortcuts.action.openScratchpads', defaultCombo: 'Ctrl+Alt+Shift+KeyS', run: function() { switchTab('scratchpads'); } }
];

// These must keep reaching the shell (interrupt, EOF, suspend, clear) or the
// clipboard, so no action may claim them.
var RESERVED_SHORTCUT_COMBOS = ['Ctrl+KeyC', 'Ctrl+KeyV', 'Ctrl+KeyD', 'Ctrl+KeyZ', 'Ctrl+KeyL', 'Meta+KeyC', 'Meta+KeyV'];

var MODIFIER_KEY_CODES = ['ControlLeft', 'ControlRight', 'AltLeft', 'AltRight', 'ShiftLeft', 'ShiftRight', 'MetaLeft', 'MetaRight', 'OSLeft', 'OSRight', 'CapsLock', 'Fn'];

var SHORTCUT_KEY_LABELS = {
  Backquote: '`', Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Backslash: '\\',
  Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/', Space: 'Space', Escape: 'Esc',
  ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→'
};

var MAC_MODIFIER_SYMBOLS = { Ctrl: '⌃', Alt: '⌥', Shift: '⇧', Meta: '⌘' };

var _isRecordingShortcut = false;
var _shortcutOverrides = null;

// ─── Combos ─────────────────────────────────────────────────────────────
function shortcutComboFromEvent(e) {
  if (!e.code || MODIFIER_KEY_CODES.indexOf(e.code) !== -1) return null;
  var parts = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.altKey) parts.push('Alt');
  if (e.shiftKey) parts.push('Shift');
  if (e.metaKey) parts.push('Meta');
  parts.push(e.code);
  return parts.join('+');
}

function _comboModifiers(combo) {
  return combo.split('+').filter(function(part) { return SHORTCUT_MODIFIERS.indexOf(part) !== -1; });
}

function _comboKeyCode(combo) {
  var parts = combo.split('+');
  return parts[parts.length - 1];
}

function _keyLabel(code) {
  if (code === 'Enter') return _IS_MAC ? '↩' : 'Enter';
  if (SHORTCUT_KEY_LABELS[code]) return SHORTCUT_KEY_LABELS[code];
  return code.replace(/^(Key|Digit)/, '');
}

function formatShortcutCombo(combo) {
  var modifiers = _comboModifiers(combo);
  var key = _keyLabel(_comboKeyCode(combo));
  if (_IS_MAC) {
    return modifiers.map(function(m) { return MAC_MODIFIER_SYMBOLS[m]; }).join('') + key;
  }
  return modifiers.concat([key]).join('+');
}

// Shift alone only changes the typed character, so it does not make a combo.
function shortcutComboError(combo) {
  var modifiers = _comboModifiers(combo);
  var hasCommandModifier = modifiers.some(function(m) { return m !== 'Shift'; });
  if (!hasCommandModifier) return 'shortcuts.error.noModifier';
  if (RESERVED_SHORTCUT_COMBOS.indexOf(combo) !== -1) return 'shortcuts.error.reserved';
  return null;
}

// ─── Bindings (browser-local) ───────────────────────────────────────────
// Only overrides are stored: an empty string unbinds an action, and a missing
// entry falls back to its default. They are cached because every keystroke is
// matched against them; another browser tab's edit drops the cache.
function _loadShortcutOverrides() {
  if (!_shortcutOverrides) _shortcutOverrides = _readShortcutOverrides();
  return _shortcutOverrides;
}

function _readShortcutOverrides() {
  var raw;
  try { raw = localStorage.getItem(SHORTCUTS_STORAGE_KEY); } catch (e) { return {}; }
  if (!raw) return {};
  try {
    var parsed = JSON.parse(raw);
    return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? _migrateRemovedShortcuts(parsed) : {};
  } catch (e) {
    console.warn('[shortcuts] ignoring unreadable ' + SHORTCUTS_STORAGE_KEY + ':', e.message);
    return {};
  }
}

// "Open terminal" was merged into "Toggle terminal". Its customised combo
// carries over unless the user had already customised the toggle combo.
function _migrateRemovedShortcuts(overrides) {
  if (!('openTerminal' in overrides)) return overrides;
  if (typeof overrides.openTerminal === 'string' && typeof overrides.toggleTerminal !== 'string') {
    overrides.toggleTerminal = overrides.openTerminal;
  }
  delete overrides.openTerminal;
  return overrides;
}

function _saveShortcutOverrides(overrides) {
  _shortcutOverrides = overrides;
  try { localStorage.setItem(SHORTCUTS_STORAGE_KEY, JSON.stringify(overrides)); } catch (e) {
    showToast(t('shortcuts.error.saveFailed'));
  }
}

function getShortcutCombo(actionId) {
  var overrides = _loadShortcutOverrides();
  if (typeof overrides[actionId] === 'string') return overrides[actionId];
  var action = _findShortcutAction(actionId);
  return action ? action.defaultCombo : '';
}

function setShortcutCombo(actionId, combo) {
  var overrides = _loadShortcutOverrides();
  overrides[actionId] = combo;
  _saveShortcutOverrides(overrides);
}

function resetShortcutCombo(actionId) {
  var overrides = _loadShortcutOverrides();
  delete overrides[actionId];
  _saveShortcutOverrides(overrides);
}

function _findShortcutAction(actionId) {
  return SHORTCUT_ACTIONS.find(function(action) { return action.id === actionId; }) || null;
}

function _actionForCombo(combo) {
  if (!combo) return null;
  return SHORTCUT_ACTIONS.find(function(action) { return getShortcutCombo(action.id) === combo; }) || null;
}

// Used by the xterm key handler so bound combos never reach the shell.
function isBoundShortcutEvent(e) {
  return !!_actionForCombo(shortcutComboFromEvent(e));
}

function setShortcutRecording(isRecording) {
  _isRecordingShortcut = isRecording;
}

// ─── Dispatch ───────────────────────────────────────────────────────────
// Shortcuts drive the loaded workspace's tabs and terminal, so they are inert
// on the project selector, Setup, and phone layouts where those are absent.
function _areShortcutsAvailable() {
  if (_isRecordingShortcut || PHONE_LAYOUT_QUERY.matches || !getWorkspaceContext()) return false;
  var app = document.getElementById('app-content');
  return !!(app && app.style.display !== 'none');
}

// The terminal and the code editor are where people work, so shortcuts must
// keep working inside them; ordinary form fields keep every keystroke.
function _isTypingTarget(target) {
  if (!target || !target.closest) return false;
  if (target.closest('.xterm, .monaco-editor')) return false;
  var tagName = target.tagName;
  return tagName === 'INPUT' || tagName === 'TEXTAREA' || target.isContentEditable;
}

function _onShortcutKeydown(e) {
  var action = _actionForCombo(shortcutComboFromEvent(e));
  if (!action || !_areShortcutsAvailable() || _isTypingTarget(e.target)) return;
  e.preventDefault();
  e.stopPropagation();
  if (!e.repeat) action.run();
}

window.addEventListener('keydown', _onShortcutKeydown, true);
window.addEventListener('storage', function(e) {
  if (e.key === SHORTCUTS_STORAGE_KEY) _shortcutOverrides = null;
});
