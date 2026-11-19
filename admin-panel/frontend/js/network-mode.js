// ═══════════════════════════════════════════════
//  NETWORK MODE
// ═══════════════════════════════════════════════

function _networkModeSubsectionTitle() {
  return '<div class="settings-subsection-title">' + escapeHtml(t('networkMode.title')) + '</div>';
}

async function renderNetworkMode() {
  var host = document.getElementById('networkModeCard');
  if (!host) return;

  var info;
  try {
    info = await apiGetNetworkMode();
  } catch (e) {
    host.innerHTML = _networkModeSubsectionTitle() +
      '<div class="hint-text hint-text--lg">' +
      escapeHtml(t('networkMode.unavailable')) + '</div>';
    return;
  }

  var enabled = !!info.network_enabled;
  var lanIps = Array.isArray(info.lan_ips) ? info.lan_ips : [];

  var lanList = lanIps.length
    ? lanIps.map(function(ip) {
        return '<code>http://' + escapeHtml(ip) + ':5111</code>';
      }).join(', ')
    : '<em>' + escapeHtml(t('networkMode.noLan')) + '</em>';

  host.innerHTML = _networkModeSubsectionTitle() +
    '<label class="inline-check">' +
      '<input type="checkbox" id="networkModeToggle"' + (enabled ? ' checked' : '') + '>' +
      '<span>' + escapeHtml(t('networkMode.allowAccess')) + '</span>' +
    '</label>' +
    '<p class="hint-text hint-text--block">' +
      escapeHtml(t('networkMode.explain')) +
    '</p>' +
    (enabled
      ? '<p class="hint-text hint-text--block">' +
        escapeHtml(t('networkMode.reach')) + ' ' + lanList + '</p>'
      : '');

  var toggle = document.getElementById('networkModeToggle');
  if (toggle) toggle.addEventListener('change', onNetworkModeToggleChange);
}

async function onNetworkModeToggleChange(ev) {
  var enabled = ev.target.checked;
  var message = enabled
    ? t('networkMode.confirmEnable')
    : t('networkMode.confirmDisable');
  var proceed = confirm(message);
  if (!proceed) {
    ev.target.checked = !enabled;
    return;
  }

  try {
    await apiSetNetworkMode(enabled);
  } catch (e) {
    ev.target.checked = !enabled;
    showToast(t('networkMode.saveFailed', { error: e.message }));
    return;
  }

  showReconnectingOverlay(enabled);
  try { await apiRestartBackend(); } catch (e) { /* response may drop on restart — that's fine */ }
  pollForBackendAndReload(enabled);
}

function _networkModeTargetHost(nowNetworkMode) {
  return nowNetworkMode ? '0.0.0.0' : '127.0.0.1';
}

function showReconnectingOverlay(nowNetworkMode) {
  var existing = document.getElementById('reconnect-overlay');
  if (existing) existing.remove();

  var div = document.createElement('div');
  div.id = 'reconnect-overlay';
  div.className = 'reconnect-overlay';
  var sub = nowNetworkMode
    ? t('networkMode.restartingNetwork')
    : t('networkMode.restartingLocal');
  div.innerHTML =
    '<div>' +
      '<div class="reconnect-overlay__title">' + escapeHtml(t('networkMode.restarting')) + '</div>' +
      '<div class="hint-text hint-text--lg">' + escapeHtml(sub) + '</div>' +
    '</div>';
  document.body.appendChild(div);
}

async function pollForBackendAndReload(nowNetworkMode) {
  var deadline = Date.now() + 30000;
  var targetHost = _networkModeTargetHost(nowNetworkMode);
  var targetPort = '5111';
  while (Date.now() < deadline) {
    try {
      var r = await fetch('/api/auth/status', { cache: 'no-store' });
      if (r.ok) {
        var currentPort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
        if (window.location.hostname === targetHost && currentPort === targetPort) {
          window.location.reload();
          return;
        }
        var target = 'http://' + targetHost + ':' + targetPort + window.location.pathname + window.location.search;
        window.location.href = target;
        return;
      }
    } catch (e) { /* still down */ }
    await new Promise(function(res) { setTimeout(res, 500); });
  }

  var ov = document.getElementById('reconnect-overlay');
  if (ov) ov.innerHTML = '<div>' + escapeHtml(t('networkMode.timeoutManual')) + '</div>';
}
