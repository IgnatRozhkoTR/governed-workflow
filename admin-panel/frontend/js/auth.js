// ═══════════════════════════════════════════════
//  AUTH SCREEN
// ═══════════════════════════════════════════════

var _authScreenWired = false;

function showAuthScreen() {
  var selector = document.getElementById('project-selector');
  var appContent = document.getElementById('app-content');
  if (selector) selector.style.display = 'none';
  if (appContent) appContent.style.display = 'none';

  var screen = document.getElementById('auth-screen');
  if (!screen) {
    screen = document.createElement('div');
    screen.id = 'auth-screen';
    screen.className = 'project-selector';
    screen.innerHTML =
      '<div class="selector-container">' +
        '<div class="selector-title">' + t('auth.title') + '</div>' +
        '<div class="selector-subtitle">' + t('auth.subtitle') + '</div>' +
        '<input type="password" id="auth-token-input" class="ws-input" ' +
               'placeholder="' + t('auth.placeholder') + '" style="margin-top: 16px;">' +
        '<div id="auth-error" style="display:none; margin-top: 8px; color: var(--danger); font-size: 0.82rem;"></div>' +
        '<button class="btn btn-primary" id="auth-submit-btn" ' +
                'style="margin-top: 12px;">' + t('auth.submit') + '</button>' +
        '<div style="margin-top: 16px; color: var(--text-muted); font-size: 0.78rem;">' + t('auth.hint') + '</div>' +
      '</div>';
    document.body.appendChild(screen);
    document.getElementById('auth-submit-btn').addEventListener('click', submitAuthToken);
    document.getElementById('auth-token-input').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') submitAuthToken();
    });
  }
  screen.style.display = '';
  var input = document.getElementById('auth-token-input');
  if (input) {
    input.value = '';
    input.focus();
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
