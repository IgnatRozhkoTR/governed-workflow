// ═══════════════════════════════════════════════
//  TERMINAL MODES
// ═══════════════════════════════════════════════
// The terminal is shown either full screen (the Terminal tab) or as a panel
// docked beside the current tab. The mode used last is remembered browser-wide
// so "open terminal" brings back whichever one the user works in.
var TERMINAL_MODE_KEY = 'ui_terminal_mode';
var TERMINAL_MODE_FULL_SCREEN = 'fullscreen';
var TERMINAL_MODE_PANEL = 'panel';

function getLastTerminalMode() {
  var stored;
  try { stored = localStorage.getItem(TERMINAL_MODE_KEY); } catch (e) { stored = null; }
  return stored === TERMINAL_MODE_PANEL ? TERMINAL_MODE_PANEL : TERMINAL_MODE_FULL_SCREEN;
}

function rememberTerminalMode(mode) {
  try { localStorage.setItem(TERMINAL_MODE_KEY, mode); } catch (e) {}
}

function _isFullScreenTerminalActive() {
  return getActiveTabId() === 'terminal';
}

function toggleTerminal() {
  if (_isFullScreenTerminalActive()) {
    switchTab(getTabBeforeTerminal());
  } else if (isTerminalPanelOpen()) {
    closeTerminalPanel();
  } else {
    openTerminal();
  }
}

function openTerminal() {
  if (_isFullScreenTerminalActive() || getLastTerminalMode() === TERMINAL_MODE_FULL_SCREEN) {
    _showFullScreenTerminal();
  } else {
    openTerminalPanel();
  }
}

// With neither mode on screen, switching opens the mode that was not used last.
function switchTerminalMode() {
  if (_isFullScreenTerminalActive()) {
    switchTab(getTabBeforeTerminal());
    openTerminalPanel();
  } else if (isTerminalPanelOpen() || getLastTerminalMode() === TERMINAL_MODE_PANEL) {
    _moveTerminalPanelToFullScreen();
  } else {
    openTerminalPanel();
  }
}

function _showFullScreenTerminal() {
  if (!_isFullScreenTerminalActive()) switchTab('terminal');
  if (isActiveTerminalConnected()) {
    focusActiveTerminalSoon();
  } else {
    connectTerminal();
  }
}

// The panel always shows the workspace session, so full screen continues in it
// rather than in whichever other tmux session was last picked there.
function _moveTerminalPanelToFullScreen() {
  closeTerminalPanel();
  switchTab('terminal');
  connectTerminal();
}
