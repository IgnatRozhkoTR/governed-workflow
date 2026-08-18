// ═══════════════════════════════════════════════
//  TERMINAL
// ═══════════════════════════════════════════════
var term = null;
var fitAddon = null;
var terminalWs = null;
var terminalConnected = false;
var _lastPastedImageKey = '';
var _lastPastedImageAt = 0;
var PASTED_IMAGE_DEDUPE_WINDOW_MS = 10000;
var _lastTerminalEnterAt = 0;
var POST_ENTER_PASTE_SUPPRESS_MS = 500;
var _IS_MAC = /Mac/.test(navigator.platform || navigator.userAgent || '');

function _uploadPastedImage(file, ws) {
  var ctx = (typeof getWorkspaceContext === 'function') ? getWorkspaceContext() : null;
  if (!ctx) return;
  var form = new FormData();
  form.append('image', file, file.name || 'pasted.png');
  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/terminal/paste-image';
  var headers = {};
  var token = (typeof getAuthToken === 'function') ? getAuthToken() : null;
  if (token) headers['Authorization'] = 'Bearer ' + token;
  fetch(url, { method: 'POST', headers: headers, body: form })
    .then(function(r) { return r.json().then(function(d){ return { ok: r.ok, body: d }; }); })
    .then(function(res) {
      if (res.ok && res.body && res.body.path) {
        var mode = res.body.mode;
        if (mode === 'clipboard') {
          if (typeof showToast === 'function') showToast(t('terminal.imagePasted') || 'Image attached');
        } else if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('@' + res.body.path);
          if (typeof showToast === 'function') showToast(t('terminal.imagePasted') || 'Image attached');
        } else {
          var msg = 'Image paste failed';
          if (typeof showToast === 'function') showToast(msg);
        }
      } else {
        var msg = (res.body && res.body.error) ? res.body.error : 'Image paste failed';
        if (typeof showToast === 'function') showToast(msg);
      }
    })
    .catch(function(err) {
      if (typeof showToast === 'function') showToast('Image paste failed: ' + err.message);
    });
}

function _getActiveTerminalKind() {
  return typeof ACTIVE_TERMINAL_KIND === 'string' && ACTIVE_TERMINAL_KIND ? ACTIVE_TERMINAL_KIND : 'claude';
}

function _terminalWsOrigin() {
  var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return protocol + '//' + window.location.host;
}

function _buildTerminalWsUrl(projectId, branch) {
  var base = _terminalWsOrigin() + '/ws/terminal/' +
             encodeURIComponent(projectId) + '/' + encodeURIComponent(branch);
  var kind = _getActiveTerminalKind();
  var withKind = kind && kind !== 'claude' ? base + '/' + encodeURIComponent(kind) : base;
  return _appendTokenToWsUrl(withKind);
}

function _buildSessionTerminalWsUrl(sessionName) {
  return _appendTokenToWsUrl(
    _terminalWsOrigin() + '/ws/terminal-session/' + encodeURIComponent(sessionName)
  );
}

var TERMINAL_THEMES = {
  dark: {
    background: '#1a1a2e',
    foreground: '#e0e0e0',
    cursor: '#e0e0e0',
    cursorAccent: '#1a1a2e',
    selectionBackground: 'rgba(255, 255, 255, 0.15)',
    black: '#2a2a3e',
    red: '#ff6b6b',
    green: '#51cf66',
    yellow: '#ffd43b',
    blue: '#818cf8',
    magenta: '#da77f2',
    cyan: '#22d3ee',
    white: '#e0e0e0',
    brightBlack: '#6b7280',
    brightRed: '#ff8787',
    brightGreen: '#69db7c',
    brightYellow: '#ffe066',
    brightBlue: '#a5b4fc',
    brightMagenta: '#e599f7',
    brightCyan: '#67e8f9',
    brightWhite: '#ffffff'
  },
  light: {
    background: '#faf8f5',
    foreground: '#2c2c2c',
    cursor: '#2c2c2c',
    cursorAccent: '#faf8f5',
    selectionBackground: 'rgba(0, 0, 0, 0.1)',
    black: '#2c2c2c',
    red: '#c92a2a',
    green: '#2b8a3e',
    yellow: '#e67700',
    blue: '#1864ab',
    magenta: '#862e9c',
    cyan: '#0c8599',
    white: '#faf8f5',
    brightBlack: '#868e96',
    brightRed: '#e03131',
    brightGreen: '#37b24d',
    brightYellow: '#f59f00',
    brightBlue: '#1c7ed6',
    brightMagenta: '#9c36b5',
    brightCyan: '#1098ad',
    brightWhite: '#ffffff'
  }
};

function getTerminalTheme() {
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  return isDark ? TERMINAL_THEMES.dark : TERMINAL_THEMES.light;
}

function _createTerminal(containerId, wsRef) {
  var container = document.getElementById(containerId);
  if (!container) return null;

  var terminal = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: "'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace",
    theme: getTerminalTheme(),
    allowProposedApi: true,
    scrollback: 5000,
    copyOnSelect: false
  });

  var addon = new FitAddon.FitAddon();
  terminal.loadAddon(addon);

  var webLinksAddon = new WebLinksAddon.WebLinksAddon();
  terminal.loadAddon(webLinksAddon);

  terminal.open(container);
  addon.fit();

  terminal.attachCustomKeyEventHandler(function(e) {
    if (e.type !== 'keydown') return true;
    if (e.key === 'Enter') {
      _lastTerminalEnterAt = Date.now();
    }
    var isMacCopy = e.metaKey && !e.ctrlKey && e.key === 'c';
    var isCtrlShiftCopy = e.ctrlKey && e.shiftKey && e.key === 'C';
    if ((isMacCopy || isCtrlShiftCopy) && terminal.hasSelection()) {
      var selected = terminal.getSelection();
      if (selected && typeof safeCopyToClipboard === 'function') {
        safeCopyToClipboard(selected);
      }
      return false;
    }
    // On Windows/Linux, plain Ctrl+V is the paste shortcut. xterm maps it to a
    // control character and cancels the keydown, which suppresses the browser's
    // native paste event. Returning false here makes xterm bail out before it
    // cancels the event, so the browser's default paste proceeds normally.
    // On macOS, Ctrl+V is left alone since paste is Cmd+V there and Ctrl+V is
    // the terminal's "quoted insert" shortcut.
    var isPlainCtrlV = e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey &&
      (e.keyCode === 86 || (typeof e.key === 'string' && e.key.toLowerCase() === 'v'));
    if (!_IS_MAC && isPlainCtrlV) {
      return false;
    }
    return true;
  });

  if (terminal.parser) {
    terminal.parser.registerOscHandler(52, function(data) {
      var parts = data.split(';');
      if (parts.length >= 2) {
        var payload = parts[parts.length - 1];
        if (payload === '?') { return true; }
        try {
          var decoded = atob(payload);
          if (typeof safeCopyToClipboard === 'function') {
            safeCopyToClipboard(decoded);
          }
        } catch(e) {}
      }
      return true;
    });
  }

  container.addEventListener('wheel', function(e) {
    e.stopPropagation();
  }, { passive: true });

  container.addEventListener('paste', function(e) {
    var ws = wsRef();
    var cd = e.clipboardData || window.clipboardData;
    if (!cd) { return; }

    var pastedText = cd.getData ? cd.getData('text') : '';
    if (pastedText && pastedText.length > 0) {
      var delta = Date.now() - _lastTerminalEnterAt;
      var suppressed = delta < POST_ENTER_PASTE_SUPPRESS_MS;
      if (suppressed) {
        e.preventDefault();
        e.stopPropagation();
      }
      console.log('[paste-guard] text paste ' + pastedText.length + ' chars, ' + delta + 'ms after last Enter — ' + (suppressed ? 'SUPPRESSED' : 'allowed'));
      return;
    }

    var items = cd.items ? Array.prototype.slice.call(cd.items) : [];
    var imageItem = null;
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file' && items[i].type && items[i].type.indexOf('image/') === 0) {
        imageItem = items[i];
        break;
      }
    }

    if (imageItem) {
      var file = imageItem.getAsFile();
      if (!file) { return; }

      var imageKey = file.size + ':' + file.type + ':' + (file.lastModified || 0) + ':' + (file.name || '');
      var now = Date.now();
      if (imageKey === _lastPastedImageKey && (now - _lastPastedImageAt) < PASTED_IMAGE_DEDUPE_WINDOW_MS) {
        return;
      }

      e.preventDefault();
      e.stopPropagation();
      _lastPastedImageKey = imageKey;
      _lastPastedImageAt = now;
      _uploadPastedImage(file, ws);
      return;
    }
  }, true);

  console.log('[paste-guard] armed, window=' + POST_ENTER_PASTE_SUPPRESS_MS + 'ms');

  terminal.onData(function(data) {
    var ws = wsRef();
    if (data === '\r') {
      _lastTerminalEnterAt = Date.now();
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  });

  terminal.onResize(function(size) {
    var ws = wsRef();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ resize: [size.cols, size.rows] }));
    }
  });

  return { terminal: terminal, fitAddon: addon };
}

function _connectTerminal(terminal, addon, wsUrl, options) {
  var ws = new WebSocket(wsUrl);

  ws.onopen = function() {
    options.onConnected();
    terminal.clear();
    if (addon) {
      addon.fit();
      if (options.focusOnOpen) terminal.focus();
      var dims = addon.proposeDimensions();
      if (dims) {
        ws.send(JSON.stringify({ resize: [dims.cols, dims.rows] }));
      }
    }
  };

  ws.onmessage = function(event) {
    if (typeof event.data === 'string' && event.data.startsWith('{')) {
      try {
        var msg = JSON.parse(event.data);
        if (msg.error) {
          terminal.writeln('\r\n\x1b[31m' + msg.error + '\x1b[0m');
          options.onError();
          return;
        }
      } catch(e) {}
    }
    terminal.write(event.data);
  };

  ws.onclose = function() {
    options.onDisconnected();
  };

  ws.onerror = function() {
    options.onError();
  };

  return ws;
}

function initTerminal() {
  if (term) return;

  var result = _createTerminal('terminalContainer', function() { return terminalWs; });
  if (!result) return;

  term = result.terminal;
  fitAddon = result.fitAddon;

  window.addEventListener('resize', function() {
    if (document.getElementById('panel-terminal').classList.contains('active')) {
      _fitAndPushSize(_activeTerminalTarget());
    }
    if (splitFitAddon && document.getElementById('splitContainer') &&
        document.getElementById('splitContainer').classList.contains('split-active')) {
      splitFitAddon.fit();
    }
  });

  term.writeln('Terminal ready. Click Connect or use Start/Resume.');
}

function connectTerminal() {
  if (!term) {
    initTerminal();
  }
  showWorkspaceTerminalView();

  var ctx = getWorkspaceContext();
  if (!ctx) {
    if (term) term.writeln('\r\n\x1b[31mNo workspace selected.\x1b[0m');
    return;
  }

  if (terminalWs && terminalWs.readyState === WebSocket.OPEN) {
    return;
  }

  var wsUrl = _buildTerminalWsUrl(ctx.projectId, ctx.branch);

  updateTerminalStatus('connecting');
  if (term) term.writeln('\r\nConnecting to tmux session...');

  terminalWs = _connectTerminal(term, fitAddon, wsUrl, {
    focusOnOpen: true,
    onConnected: function() {
      terminalConnected = true;
      updateTerminalStatus('connected');
    },
    onDisconnected: function() {
      terminalConnected = false;
      updateTerminalStatus('disconnected');
      if (term) term.writeln('\r\n\x1b[33mDisconnected from terminal.\x1b[0m');
    },
    onError: function() {
      terminalConnected = false;
      updateTerminalStatus('error');
      if (term) term.writeln('\r\n\x1b[31mWebSocket error. Is the tmux session running?\x1b[0m');
    }
  });
}

function disconnectTerminal() {
  if (terminalWs) {
    terminalWs.close();
    terminalWs = null;
  }
  terminalConnected = false;
  updateTerminalStatus('disconnected');
}

function killTerminalSession() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  disconnectTerminal();

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/terminal/kill', {
    kind: _getActiveTerminalKind()
  })
  .then(function() {
    if (term) term.writeln('\r\n\x1b[33mSession killed.\x1b[0m');
    loadTerminalSessions();
  })
  .catch(function(e) {
    if (term) term.writeln('\r\n\x1b[31mKill failed: ' + e.message + '\x1b[0m');
  });
}

function updateTerminalStatus(status) {
  var el = document.getElementById('terminalStatus');
  var connectBtn = document.getElementById('terminalConnectBtn');
  var disconnectBtn = document.getElementById('terminalDisconnectBtn');
  var killBtn = document.getElementById('terminalKillBtn');

  if (el) {
    switch(status) {
      case 'connected':
        el.textContent = t('terminal.connected');
        el.className = 'terminal-status connected';
        break;
      case 'connecting':
        el.textContent = t('terminal.connecting');
        el.className = 'terminal-status';
        break;
      case 'error':
        el.textContent = t('terminal.error');
        el.className = 'terminal-status';
        break;
      default:
        el.textContent = t('terminal.disconnected');
        el.className = 'terminal-status';
    }
  }

  if (connectBtn) connectBtn.style.display = (status === 'connected') ? 'none' : '';
  if (disconnectBtn) disconnectBtn.style.display = (status === 'connected') ? '' : 'none';
  if (killBtn) killBtn.style.display = (status === 'connected') ? '' : 'none';
}

function updateTerminalTheme() {
  if (term) {
    term.options.theme = getTerminalTheme();
  }
  if (splitTerm) {
    splitTerm.options.theme = getTerminalTheme();
  }
  Object.keys(_sessionTabs).forEach(function(name) {
    var tab = _sessionTabs[name];
    if (tab.terminal) tab.terminal.options.theme = getTerminalTheme();
  });
}

function onTerminalTabActivated() {
  if (!term) {
    initTerminal();
  }
  _fitActiveTerminalSoon(true);
  startSessionListPolling();
  _refreshWorkspaceSessionName();
}

// ═══════════════════════════════════════════════
//  SESSION LIST
// ═══════════════════════════════════════════════
var _sessionListInterval = null;
var _sessionListSignature = null;
var _sessionListErrorShown = false;
var _workspaceSessionName = null;
var _lastSessionListPayload = [];

// Learns the exact tmux session name the workspace terminal is backed by, so the
// by-name chip for that same session can be suppressed instead of showing the
// workspace's own terminal twice in the toolbar.
function _refreshWorkspaceSessionName() {
  var ctx = (typeof getWorkspaceContext === 'function') ? getWorkspaceContext() : null;
  if (!ctx) return;

  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) +
             '/terminal/status?kind=' + encodeURIComponent(_getActiveTerminalKind());

  apiGet(url)
    .then(function(data) {
      _workspaceSessionName = (data && data.session) ? data.session : null;
      renderSessionList(_lastSessionListPayload);
    })
    .catch(function(e) {
      console.warn('[chips] workspace session name lookup failed', e);
    });
}

function loadTerminalSessions() {
  apiGet('/api/terminal/sessions')
    .then(function(sessions) {
      // Only a successful listing is authoritative — a failed poll must not tear
      // down terminals for sessions that are still alive.
      try {
        _closeVanishedSessionTabs(sessions);
      } catch (e) {
        console.error('[chips] closing vanished session tabs failed', e);
      }
      renderSessionList(sessions);
    })
    .catch(function(e) {
      console.warn('[chips] session poll failed', e);
      renderSessionList([]);
    });
}

function renderSessionList(sessions) {
  var container = document.getElementById('terminalSessionList');
  if (!container) return;

  try {
    if (!Array.isArray(sessions)) {
      console.warn('[chips] unexpected payload', sessions);
      sessions = [];
    }
    _lastSessionListPayload = sessions;

    var signature = _sessionChipSignature(sessions);

    // The signature is a claim about what the container currently holds, so it is
    // recorded only once the rebuild has actually produced those chips, and it is
    // distrusted whenever the container is empty. Recording it up front would make
    // a single interrupted rebuild permanent: every later poll carries the same
    // signature, skips the rebuild and leaves the toolbar blank for good.
    if (signature !== _sessionListSignature || !container.firstChild) {
      _rebuildSessionChips(container, sessions);
      _sessionListSignature = signature;
    }

    _updateSessionChipStates();
  } catch (e) {
    console.error('[chips] render failed', e);
    _sessionListSignature = null;
    if (!_sessionListErrorShown) {
      _sessionListErrorShown = true;
      if (typeof showToast === 'function') showToast(t('terminal.sessionListError'));
    }
  }
}

function _sessionChipSignature(sessions) {
  return I18N_LOCALE + '\u0002' + (_workspaceSessionName || '') + '\u0002' + sessions.map(function(s) {
    return s.name + '\u0001' + (s.attached ? '1' : '0') + '\u0001' + (s.command || '');
  }).join('\u0002');
}

// Chips are built as DOM nodes rather than markup so tmux-supplied session names
// never have to survive a round trip through HTML/attribute escaping.
function _rebuildSessionChips(container, sessions) {
  var frag = document.createDocumentFragment();
  frag.appendChild(_buildWorkspaceChip());

  // The workspace terminal chip already represents this session, so listing it
  // again by name would open a second tmux client attached to the same session.
  var otherSessions = sessions.filter(function(session) {
    return session.name !== _workspaceSessionName;
  });

  if (!otherSessions.length) {
    var empty = document.createElement('span');
    empty.className = 'session-list-empty';
    empty.textContent = t('terminal.noSessions');
    frag.appendChild(empty);
  } else {
    otherSessions.forEach(function(session) {
      frag.appendChild(_buildSessionChip(session));
    });
  }

  container.textContent = '';
  container.appendChild(frag);
}

function _buildWorkspaceChip() {
  var chip = document.createElement('div');
  chip.className = 'session-item';
  chip.title = _workspaceSessionName
    ? t('terminal.workspaceSession') + ' (' + _workspaceSessionName + ')'
    : t('terminal.workspaceSession');

  var label = document.createElement('span');
  label.className = 'session-name';
  label.textContent = t('terminal.workspaceSession');
  chip.appendChild(label);

  chip.addEventListener('click', showWorkspaceTerminalView);
  return chip;
}

function _buildSessionChip(session) {
  var chip = document.createElement('div');
  chip.className = 'session-item';
  chip.dataset.session = session.name;
  chip.title = session.command || session.name;

  var dot = document.createElement('span');
  dot.className = 'session-status-dot ' + (session.attached ? 'session-attached' : 'session-detached');
  chip.appendChild(dot);

  var name = document.createElement('span');
  name.className = 'session-name';
  name.textContent = session.name;
  chip.appendChild(name);

  var status = document.createElement('span');
  status.className = 'session-status-label';
  status.textContent = session.attached ? t('terminal.attached') : t('terminal.detached');
  chip.appendChild(status);

  var killBtn = document.createElement('button');
  killBtn.className = 'session-kill-btn';
  killBtn.title = t('terminal.killSession');
  killBtn.innerHTML = '&times;';
  killBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    killSessionByName(session.name);
  });
  chip.appendChild(killBtn);

  chip.addEventListener('click', function() { openSessionTab(session.name); });
  return chip;
}

function _updateSessionChipStates() {
  var container = document.getElementById('terminalSessionList');
  if (!container) return;
  container.querySelectorAll('.session-item').forEach(function(chip) {
    var name = chip.dataset.session || null;
    var tab = name ? _sessionTabs[name] : null;
    chip.classList.toggle('active', name === _activeSessionTabName);
    chip.classList.toggle('open', !!(tab && tab.ws && tab.ws.readyState === WebSocket.OPEN));
  });
}

function killSessionByName(name) {
  apiPost('/api/terminal/sessions/' + encodeURIComponent(name) + '/kill', {})
    .then(function() {
      closeSessionTab(name);
      loadTerminalSessions();
    })
    .catch(function(e) {
      if (typeof showToast === 'function') showToast(t('terminal.killFailed') + ': ' + e.message);
      loadTerminalSessions();
    });
}

function startSessionListPolling() {
  loadTerminalSessions();
  if (_sessionListInterval) clearInterval(_sessionListInterval);
  _sessionListInterval = setInterval(loadTerminalSessions, 5000);
}

function stopSessionListPolling() {
  if (_sessionListInterval) {
    clearInterval(_sessionListInterval);
    _sessionListInterval = null;
  }
}

// ═══════════════════════════════════════════════
//  SESSION TERMINAL TABS
// ═══════════════════════════════════════════════
var _sessionTabs = {};
var _activeSessionTabName = null;
var _sessionViewCounter = 0;

function openSessionTab(name) {
  var tab = _sessionTabs[name] || _createSessionTabView(name);
  if (!tab) return;

  _showTerminalView(name);

  if (!tab.terminal) {
    var created = _createTerminal(tab.viewId, function() { return tab.ws; });
    if (!created) {
      closeSessionTab(name);
      return;
    }
    tab.terminal = created.terminal;
    tab.fitAddon = created.fitAddon;
  }

  if (!tab.ws || tab.ws.readyState > WebSocket.OPEN) {
    _connectSessionTab(tab);
  }

  _fitActiveTerminalSoon(true);
}

function _createSessionTabView(name) {
  var container = document.getElementById('terminalContainer');
  if (!container) return null;

  _sessionViewCounter += 1;
  var view = document.createElement('div');
  view.className = 'terminal-view';
  view.id = 'sessionTerminalView' + _sessionViewCounter;
  container.appendChild(view);

  var tab = { name: name, viewId: view.id, viewEl: view, terminal: null, fitAddon: null, ws: null };
  _sessionTabs[name] = tab;
  return tab;
}

function _connectSessionTab(tab) {
  tab.ws = _connectTerminal(tab.terminal, tab.fitAddon, _buildSessionTerminalWsUrl(tab.name), {
    focusOnOpen: _activeSessionTabName === tab.name,
    onConnected: _updateSessionChipStates,
    onDisconnected: function() {
      if (tab.terminal) tab.terminal.writeln('\r\n\x1b[33m' + t('terminal.sessionClosed') + '\x1b[0m');
      _updateSessionChipStates();
    },
    onError: function() {
      if (tab.terminal) tab.terminal.writeln('\r\n\x1b[31m' + t('terminal.sessionError') + '\x1b[0m');
      _updateSessionChipStates();
    }
  });
}

function closeSessionTab(name) {
  var tab = _sessionTabs[name];
  if (!tab) return;

  if (tab.ws) {
    tab.ws.onopen = null;
    tab.ws.onmessage = null;
    tab.ws.onclose = null;
    tab.ws.onerror = null;
    tab.ws.close();
    tab.ws = null;
  }
  if (tab.terminal) {
    tab.terminal.dispose();
    tab.terminal = null;
  }
  if (tab.viewEl && tab.viewEl.parentNode) {
    tab.viewEl.parentNode.removeChild(tab.viewEl);
  }
  delete _sessionTabs[name];

  if (_activeSessionTabName === name) {
    showWorkspaceTerminalView();
  }
}

function closeAllSessionTabs() {
  Object.keys(_sessionTabs).forEach(closeSessionTab);
}

function _closeVanishedSessionTabs(sessions) {
  if (!Array.isArray(sessions)) {
    console.warn('[chips] unexpected payload', sessions);
    sessions = [];
  }
  var alive = {};
  sessions.forEach(function(s) { alive[s.name] = true; });
  Object.keys(_sessionTabs).forEach(function(name) {
    if (!alive[name]) closeSessionTab(name);
  });
}

function showWorkspaceTerminalView() {
  _showTerminalView(null);
  _fitActiveTerminalSoon(true);
}

function _showTerminalView(name) {
  _activeSessionTabName = name;

  var container = document.getElementById('terminalContainer');
  if (container) container.classList.toggle('session-view-active', !!name);

  Object.keys(_sessionTabs).forEach(function(key) {
    _sessionTabs[key].viewEl.classList.toggle('active', key === name);
  });

  _updateSessionChipStates();
}

function _activeTerminalTarget() {
  var tab = _activeSessionTabName ? _sessionTabs[_activeSessionTabName] : null;
  if (tab) return tab;
  return { terminal: term, fitAddon: fitAddon, ws: terminalWs };
}

// A hidden xterm cannot measure itself, so every reveal must re-fit and tell the
// backend pty about the dimensions it ended up with.
function _fitAndPushSize(target) {
  if (!target || !target.fitAddon) return;
  target.fitAddon.fit();
  var dims = target.fitAddon.proposeDimensions();
  if (!dims || !dims.cols || !dims.rows) return;
  var ws = target.ws;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ resize: [dims.cols, dims.rows] }));
  }
}

function _fitActiveTerminalSoon(shouldFocus) {
  setTimeout(function() {
    var target = _activeTerminalTarget();
    _fitAndPushSize(target);
    if (shouldFocus && target.terminal) target.terminal.focus();
  }, 50);
}

// ═══════════════════════════════════════════════
//  SPLIT TERMINAL
// ═══════════════════════════════════════════════
var splitTerm = null;
var splitFitAddon = null;
var splitWs = null;
var splitConnected = false;

function toggleSplitTerminal() {
  var container = document.getElementById('splitContainer');
  var btn = document.getElementById('splitTerminalBtn');
  if (!container) return;

  var isActive = container.classList.contains('split-active');

  if (isActive) {
    container.classList.remove('split-active');
    if (btn) btn.classList.remove('active');
    disconnectSplitTerminal();
  } else {
    container.classList.add('split-active');
    if (btn) btn.classList.add('active');

    if (!splitTerm) {
      initSplitTerminal();
    }

    if (splitFitAddon) {
      setTimeout(function() { splitFitAddon.fit(); }, 100);
      setTimeout(function() {
        if (splitTerm) splitTerm.focus();
      }, 150);
    }

    connectSplitTerminal();
  }
}

function initSplitTerminal() {
  if (splitTerm) return;

  var result = _createTerminal('splitTerminalContainer', function() { return splitWs; });
  if (!result) return;

  splitTerm = result.terminal;
  splitFitAddon = result.fitAddon;
}

function connectSplitTerminal() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  if (splitWs && splitWs.readyState === WebSocket.OPEN) return;

  var wsUrl = _buildTerminalWsUrl(ctx.projectId, ctx.branch);

  updateSplitTerminalStatus('connecting');

  splitWs = _connectTerminal(splitTerm, splitFitAddon, wsUrl, {
    focusOnOpen: true,
    onConnected: function() {
      splitConnected = true;
      updateSplitTerminalStatus('connected');
    },
    onDisconnected: function() {
      splitConnected = false;
      updateSplitTerminalStatus('disconnected');
    },
    onError: function() {
      splitConnected = false;
      updateSplitTerminalStatus('error');
    }
  });
}

function disconnectSplitTerminal() {
  if (splitWs) {
    splitWs.close();
    splitWs = null;
  }
  splitConnected = false;
  updateSplitTerminalStatus('disconnected');
}

function updateSplitTerminalStatus(status) {
  var el = document.getElementById('splitTerminalStatus');
  var connectBtn = document.getElementById('splitConnectBtn');
  var disconnectBtn = document.getElementById('splitDisconnectBtn');

  if (el) {
    switch(status) {
      case 'connected':
        el.textContent = t('terminal.connected');
        el.className = 'terminal-status connected';
        break;
      case 'connecting':
        el.textContent = t('terminal.connecting');
        el.className = 'terminal-status';
        break;
      default:
        el.textContent = t('terminal.disconnected');
        el.className = 'terminal-status';
    }
  }

  if (connectBtn) connectBtn.style.display = (status === 'connected') ? 'none' : '';
  if (disconnectBtn) disconnectBtn.style.display = (status === 'connected') ? '' : 'none';
}

// Drag-to-resize split panel
(function() {
  var handle = null;
  var startX = 0;
  var startWidth = 0;

  document.addEventListener('mousedown', function(e) {
    if (e.target.id === 'splitHandle') {
      handle = e.target;
      startX = e.clientX;
      var splitTermEl = document.getElementById('splitTerminal');
      startWidth = splitTermEl ? splitTermEl.offsetWidth : 400;
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    }
  });

  document.addEventListener('mousemove', function(e) {
    if (!handle) return;
    var diff = startX - e.clientX;
    var newWidth = Math.max(300, Math.min(startWidth + diff, window.innerWidth - 400));
    var splitTermEl = document.getElementById('splitTerminal');
    if (splitTermEl) {
      splitTermEl.style.width = newWidth + 'px';
      splitTermEl.style.flex = 'none';
    }
    if (splitFitAddon) splitFitAddon.fit();
    if (fitAddon && document.getElementById('panel-terminal').classList.contains('active')) fitAddon.fit();
  });

  document.addEventListener('mouseup', function() {
    if (handle) {
      handle.classList.remove('dragging');
      handle = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
  });
})();

document.addEventListener('workspace-reset', function() {
  if (typeof disconnectTerminal === 'function') disconnectTerminal();
  closeAllSessionTabs();
  _sessionListSignature = null;
  _workspaceSessionName = null;
  if (typeof disconnectSplitTerminal === 'function') disconnectSplitTerminal();
  if (term) { term.clear(); term.dispose(); term = null; fitAddon = null; }
  if (typeof splitTerm !== 'undefined' && splitTerm) { splitTerm.clear(); splitTerm.dispose(); splitTerm = null; splitFitAddon = null; }
  terminalConnected = false;
});
