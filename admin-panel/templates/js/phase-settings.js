// ═══════════════════════════════════════════════
//  PHASE SETTINGS — toggle cards
// ═══════════════════════════════════════════════

function _phaseEscape(str) {
  var el = document.createElement('span');
  el.textContent = String(str);
  return el.innerHTML;
}

function _phaseLabel(phaseObj) {
  var id = _phaseEscape(phaseObj.id);
  var name = _phaseEscape(phaseObj.name || phaseObj.id);
  return name + (name !== id ? ' <span style="color: var(--text-muted); font-size: 0.75rem;">(' + id + ')</span>' : '');
}

function _phaseBadges(phaseObj) {
  var badges = '';
  if (phaseObj.always_on) {
    badges += '<span class="badge" style="font-size: 0.65rem; padding: 1px 6px; background: var(--text-muted); color: var(--bg-base); border-radius: 3px; margin-left: 4px;">'
      + (typeof t === 'function' ? t('labels.alwaysOn') : 'Always on') + '</span>';
  }
  if (phaseObj.is_user_gate) {
    badges += '<span class="badge" style="font-size: 0.65rem; padding: 1px 6px; background: var(--accent); color: var(--accent-text); border-radius: 3px; margin-left: 4px;">'
      + (typeof t === 'function' ? t('labels.userGate') : 'User gate') + '</span>';
  }
  return badges;
}

function _renderPhaseRows(phases, enabledMap, endpointBase, scope) {
  if (phases.length === 0) {
    return '<div style="color: var(--text-muted); font-size: 0.82rem; padding: 8px 0;">No phases available.</div>';
  }

  return phases.map(function(phase) {
    var isAlwaysOn = !!phase.always_on;
    var isEnabled = isAlwaysOn ? true : !!enabledMap[phase.id];
    var checkedAttr = isEnabled ? 'checked' : '';
    var disabledAttr = isAlwaysOn ? 'disabled' : '';
    var checkboxId = 'phase-toggle-' + scope + '-' + phase.id.replace(/\./g, '-');

    return '<div style="display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border);">'
      + '<input type="checkbox" id="' + checkboxId + '"'
      + ' data-phase-id="' + _phaseEscape(phase.id) + '"'
      + ' data-scope="' + _phaseEscape(scope) + '"'
      + ' data-endpoint="' + _phaseEscape(endpointBase) + '"'
      + ' ' + checkedAttr
      + ' ' + disabledAttr
      + ' onchange="_onPhaseToggleChange(this)"'
      + ' style="flex-shrink: 0;">'
      + '<label for="' + checkboxId + '" style="font-size: 0.82rem; color: var(--text-primary); cursor: ' + (isAlwaysOn ? 'default' : 'pointer') + '; flex: 1; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">'
      + _phaseLabel(phase)
      + _phaseBadges(phase)
      + '</label>'
      + '</div>';
  }).join('');
}

async function _onPhaseToggleChange(checkbox) {
  var phaseId = checkbox.getAttribute('data-phase-id');
  var endpointBase = checkbox.getAttribute('data-endpoint');
  var enabled = checkbox.checked;

  checkbox.disabled = true;
  var previousChecked = !enabled;

  try {
    var settings = {};
    settings[phaseId] = enabled;
    await apiPut(endpointBase, { settings: settings });
  } catch (e) {
    checkbox.checked = previousChecked;
    if (typeof showToast === 'function') {
      showToast('Failed to save phase setting: ' + e.message);
    }
  } finally {
    if (!checkbox.getAttribute('data-always-on')) {
      checkbox.disabled = false;
    }
  }
}

async function renderPhaseToggleCard(container, scope, endpointBase) {
  if (!container) return;

  container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.82rem;">'
    + (typeof t === 'function' ? t('research.loading') : 'Loading...') + '</div>';

  var phases = [];
  var enabledMap = {};

  try {
    var availableData = await apiGet('/api/phases/available');
    phases = availableData.phases || [];
  } catch (e) {
    container.innerHTML = '<div style="color: var(--danger); font-size: 0.82rem;">Failed to load phases: ' + _phaseEscape(e.message) + '</div>';
    return;
  }

  try {
    var settingsData = await apiGet(endpointBase);
    var settings = settingsData.settings || {};
    Object.keys(settings).forEach(function(id) {
      enabledMap[id] = !!settings[id];
    });
  } catch (e) {
    console.warn('Failed to load phase settings for ' + scope + ':', e.message);
  }

  var desc = typeof t === 'function' ? t('config.phaseSettingsDesc') : 'Enable or disable phases for this scope. Always-on phases cannot be disabled.';
  container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.78rem; margin-bottom: 10px;">' + _phaseEscape(desc) + '</div>'
    + _renderPhaseRows(phases, enabledMap, endpointBase, scope);
}
