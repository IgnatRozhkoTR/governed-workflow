// ═══════════════════════════════════════════════
//  NETWORK MODE
// ═══════════════════════════════════════════════

function _networkModeHeader() {
  return '<div class="card-header" style="cursor: pointer;" ' +
         'onclick="this.closest(\'.card\').classList.toggle(\'collapsed\')">' +
         '<span class="card-title">' + escapeHtml(t('networkMode.title')) + '</span>' +
         '<span class="card-collapse-chevron">&#9660;</span>' +
         '</div>';
}

async function renderNetworkMode() {
  var host = document.getElementById('networkModeCard');
  if (!host) return;

  var info;
  try {
    info = await apiGetNetworkMode();
  } catch (e) {
    host.innerHTML = _networkModeHeader() +
      '<div class="card-body"><div style="color: var(--text-muted); font-size: 0.82rem;">' +
      escapeHtml(t('networkMode.unavailable')) + '</div></div>';
    return;
  }

  var enabled = !!info.network_enabled;
  var lanIps = Array.isArray(info.lan_ips) ? info.lan_ips : [];

  var lanList = lanIps.length
    ? lanIps.map(function(ip) {
        return '<code>http://' + escapeHtml(ip) + ':5111</code>';
      }).join(', ')
    : '<em>' + escapeHtml(t('networkMode.noLan')) + '</em>';

  host.innerHTML = _networkModeHeader() +
    '<div class="card-body">' +
      '<label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">' +
        '<input type="checkbox" id="networkModeToggle"' + (enabled ? ' checked' : '') + '>' +
        '<span style="font-size: 0.85rem;">' + escapeHtml(t('networkMode.allowAccess')) + '</span>' +
      '</label>' +
      '<p style="margin: 10px 0 0; color: var(--text-muted); font-size: 0.78rem;">' +
        escapeHtml(t('networkMode.explain')) +
      '</p>' +
      (enabled
        ? '<p style="margin: 10px 0 0; color: var(--text-muted); font-size: 0.78rem;">' +
          escapeHtml(t('networkMode.reach')) + ' ' + lanList + '</p>'
        : '') +
    '</div>';

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
  div.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);color:#fff;display:flex;align-items:center;justify-content:center;z-index:9999;font-size:1rem;padding:24px;text-align:center;';
  var sub = nowNetworkMode
    ? t('networkMode.restartingNetwork')
    : t('networkMode.restartingLocal');
  div.innerHTML =
    '<div>' +
      '<div style="margin-bottom:12px; font-weight: 600;">' + escapeHtml(t('networkMode.restarting')) + '</div>' +
      '<div style="color: #bbb; font-size: 0.82rem;">' + escapeHtml(sub) + '</div>' +
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
