// ═══════════════════════════════════════════════
//  AUTH SCREEN
// ═══════════════════════════════════════════════

var _fallbackSetupCommand = 'python3 backend/app.py auth-token';

var _authScreenWired = false;
var _authConfiguredCache = null;
var _setupCommand = _fallbackSetupCommand;

async function _fetchAuthConfigured() {
  if (_authConfiguredCache !== null) return _authConfiguredCache;
  try {
    var status = await apiAuthStatus();
    _authConfiguredCache = !!(status && status.configured);
    if (status && typeof status.setup_command === 'string' && status.setup_command) {
      _setupCommand = status.setup_command;
    } else {
      _setupCommand = _fallbackSetupCommand;
    }
  } catch (e) {
    _authConfiguredCache = false;
    _setupCommand = _fallbackSetupCommand;
  }
  return _authConfiguredCache;
}

function _renderAuthScreen(configured) {
  var subtitleKey = configured ? 'auth.subtitleConfigured' : 'auth.subtitleUnconfigured';
  var cmd = escapeHtml(_setupCommand);
  return (
    '<div class="selector-container">' +
      '<div class="selector-title">' + t('auth.title') + '</div>' +
      '<div class="selector-subtitle">' + t(subtitleKey) + '</div>' +
      '<div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 12px;">' +
        t('auth.commandLabel') +
      '</div>' +
      '<div class="command-block">' +
        '<code>' + cmd + '</code>' +
        '<button class="copy-btn" id="auth-copy-btn" type="button">' + t('auth.copy') + '</button>' +
      '</div>' +
      '<div style="margin-top: 10px; color: var(--text-muted); font-size: 0.78rem;">' +
        t('auth.commandHint') +
      '</div>' +
      '<input type="password" id="auth-token-input" class="ws-input" ' +
             'placeholder="' + t('auth.placeholder') + '" style="margin-top: 20px;">' +
      '<div id="auth-error" style="display:none; margin-top: 8px; color: var(--danger); font-size: 0.82rem;"></div>' +
      '<button class="btn btn-primary" id="auth-submit-btn" ' +
              'style="margin-top: 12px;">' + t('auth.submit') + '</button>' +
    '</div>'
  );
}

async function showAuthScreen() {
  var selector = document.getElementById('project-selector');
  var appContent = document.getElementById('app-content');
  if (selector) selector.style.display = 'none';
  if (appContent) appContent.style.display = 'none';

  var configured = await _fetchAuthConfigured();

  var screen = document.getElementById('auth-screen');
  if (!screen) {
    screen = document.createElement('div');
    screen.id = 'auth-screen';
    screen.className = 'project-selector';
    document.body.appendChild(screen);
  }
  screen.innerHTML = _renderAuthScreen(configured);
  screen.style.display = '';

  var submitBtn = document.getElementById('auth-submit-btn');
  if (submitBtn) submitBtn.addEventListener('click', submitAuthToken);

  var input = document.getElementById('auth-token-input');
  if (input) {
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') submitAuthToken();
    });
    input.value = '';
    input.focus();
  }

  var copyBtn = document.getElementById('auth-copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      safeCopyToClipboard(_setupCommand).then(function() {
        flashButton(copyBtn, t('auth.copied'));
      });
    });
  }

  var err = document.getElementById('auth-error');
  if (err) err.style.display = 'none';
}

function hideAuthScreen() {
  var screen = document.getElementById('auth-screen');
  if (screen) screen.style.display = 'none';
}

async function submitAuthToken() {
  var input = document.getElementById('auth-token-input');
  var err = document.getElementById('auth-error');
  var token = input ? (input.value || '').trim() : '';
  if (!token) return;

  setAuthToken(token);
  try {
    var res = await apiAuthCheck(token);
    if (res && res.ok) {
      hideAuthScreen();
      if (err) err.style.display = 'none';
      initApp();
      return;
    }
    throw new Error('invalid');
  } catch (e) {
    clearAuthToken();
    _authConfiguredCache = null;
    if (err) {
      err.textContent = t('auth.invalid');
      err.style.display = '';
    }
  }
}

(function _wireAuthRequired() {
  if (_authScreenWired) return;
  _authScreenWired = true;
  if (typeof EventBus !== 'undefined' && EventBus && typeof EventBus.on === 'function') {
    EventBus.on('auth:required', showAuthScreen);
  }
})();
