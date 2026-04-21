// ═══════════════════════════════════════════════
//  PHASE SETTINGS — toggle cards
// ═══════════════════════════════════════════════

var _t = typeof t === 'function' ? t : function(k) { return k; };

function _phaseEscape(str) {
  var el = document.createElement('span');
  el.textContent = String(str);
  return el.innerHTML;
}

function _phaseLabel(phaseObj) {
  var id = _phaseEscape(phaseObj.id);
  var name = _phaseEscape(phaseObj.name || phaseObj.id);
  return name + (name !== id ? ' <span class="phase-settings__id">(' + id + ')</span>' : '');
}

function _phaseBadges(phaseObj) {
  var badges = '';
  if (phaseObj.always_on) {
    badges += '<span class="badge phase-settings__badge phase-settings__badge--always-on">'
      + _t('labels.alwaysOn') + '</span>';
  }
  if (phaseObj.is_user_gate) {
    badges += '<span class="badge phase-settings__badge phase-settings__badge--user-gate">'
      + _t('labels.userGate') + '</span>';
  }
  return badges;
}

function _renderPhaseRows(phases, enabledMap, endpointBase, scope) {
  if (phases.length === 0) {
    return '<div class="phase-settings__empty">No phases available.</div>';
  }

  return phases.map(function(phase) {
    var isAlwaysOn = !!phase.always_on;
    var isEnabled = isAlwaysOn ? true : !!enabledMap[phase.id];
    var checkedAttr = isEnabled ? 'checked' : '';
    var disabledAttr = isAlwaysOn ? 'disabled' : '';
    var checkboxId = 'phase-toggle-' + scope + '-' + phase.id.replace(/\./g, '-');
    var labelCursorClass = isAlwaysOn ? 'phase-settings__label--disabled' : 'phase-settings__label--enabled';

    return '<div class="phase-settings__row">'
      + '<input type="checkbox" class="phase-settings__checkbox" id="' + checkboxId + '"'
      + ' data-phase-id="' + _phaseEscape(phase.id) + '"'
      + ' data-scope="' + _phaseEscape(scope) + '"'
      + ' data-endpoint="' + _phaseEscape(endpointBase) + '"'
      + ' ' + checkedAttr
      + ' ' + disabledAttr
      + ' onchange="_onPhaseToggleChange(this)">'
      + '<label for="' + checkboxId + '" class="phase-settings__label ' + labelCursorClass + '">'
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

  container.innerHTML = '<div class="phase-settings__loading">' + _t('research.loading') + '</div>';

  var phases = [];
  var enabledMap = {};

  try {
    var availableData = await apiGet('/api/phases/available');
    phases = availableData.phases || [];
  } catch (e) {
    container.innerHTML = '<div class="phase-settings__error">Failed to load phases: ' + _phaseEscape(e.message) + '</div>';
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

  container.innerHTML = '<div class="phase-settings__desc">' + _phaseEscape(_t('config.phaseSettingsDesc')) + '</div>'
    + _renderPhaseRows(phases, enabledMap, endpointBase, scope);
}
