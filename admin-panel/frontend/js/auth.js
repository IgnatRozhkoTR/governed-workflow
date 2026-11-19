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
    '<div class="ws-auth">' +
      '<div class="ws-brand">' +
        '<img src="/img/logo.png" alt="" width="40" height="40">' +
        '<h1 class="ws-selector-title">' + t('shell.brand') + '</h1>' +
      '</div>' +
      '<section class="card">' +
        '<div class="ch"><h3>' + t('auth.title') + '</h3></div>' +
        '<div class="cb">' +
          '<p class="dim">' + t(subtitleKey) + '</p>' +
          '<div class="lbl">' + t('auth.commandLabel') +
            '<div class="command-block">' +
              '<code>' + cmd + '</code>' +
              '<button class="btn xs" id="auth-copy-btn" type="button">' + t('auth.copy') + '</button>' +
            '</div>' +
          '</div>' +
          '<p class="dim sm">' + t('auth.commandHint') + '</p>' +
          '<label class="lbl">' + t('auth.tokenLabel') +
            '<input type="password" id="auth-token-input" class="inp mono" placeholder="' + t('auth.placeholder') + '">' +
          '</label>' +
          '<div id="auth-error" class="auth-error" style="display:none;"></div>' +
          '<div><button class="btn pri lg" id="auth-submit-btn">' + t('auth.submit') + '</button></div>' +
        '</div>' +
      '</section>' +
      _renderAuthToolbar() +
    '</div>'
  );
}

function _renderAuthToolbar() {
  var themeIcon = cpIcon(state.theme === 'dark' ? 'moon' : 'sun');
  return '<div class="auth-toolbar">' +
    '<select class="btn locale-select" id="authLocaleSelect" aria-label="Language">' +
      '<option value="en">EN</option><option value="ru">RU</option></select>' +
    '<button class="btn ic" id="authThemeBtn" type="button" aria-label="' + escapeHtml(t('shell.switchTheme')) + '">' + themeIcon + '</button>' +
  '</div>';
}

function _wireAuthToolbar() {
  var localeSelect = document.getElementById('authLocaleSelect');
  if (localeSelect) {
    localeSelect.value = I18N_LOCALE;
    localeSelect.addEventListener('change', function() {
      localStorage.setItem('admin-panel-locale', localeSelect.value);
      I18N_LOCALE = localeSelect.value;
      loadI18n(localeSelect.value).then(showAuthScreen);
    });
  }
  var themeBtn = document.getElementById('authThemeBtn');
  if (themeBtn) {
    themeBtn.addEventListener('click', function() {
      toggleTheme();
      themeBtn.innerHTML = cpIcon(state.theme === 'dark' ? 'moon' : 'sun');
    });
  }
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
    document.body.appendChild(screen);
  }
  screen.innerHTML = _renderAuthScreen(configured);
  _wireAuthToolbar();
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
