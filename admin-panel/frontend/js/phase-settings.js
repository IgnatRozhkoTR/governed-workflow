// ═══════════════════════════════════════════════
//  PHASE SETTINGS — toggle cards
// ═══════════════════════════════════════════════

var _t = typeof t === 'function' ? t : function(k) { return k; };

function _phaseLabel(phaseObj) {
  var id = escapeHtml(phaseObj.id);
  var name = escapeHtml(phaseObj.name || phaseObj.id);
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
  if (phaseObj.templated) {
    badges += '<span class="badge phase-settings__badge phase-settings__badge--per-sub-phase">'
      + _t('labels.perSubPhase') + '</span>';
  }
  return badges;
}

function _renderPhaseRows(phases, enabledMap, endpointBase, scope, pendingSettings) {
  if (phases.length === 0) {
    return '<div class="phase-settings__empty">No phases available.</div>';
  }

  return phases.map(function(phase) {
    var isAlwaysOn = !!phase.always_on;
    var isPending = pendingSettings && (phase.id in pendingSettings);
    var isEnabled = isAlwaysOn ? true : (
      isPending ? !!pendingSettings[phase.id] :
      (phase.id in enabledMap ? !!enabledMap[phase.id] : true)
    );
    var checkedAttr = isEnabled ? 'checked' : '';
    var disabledAttr = isAlwaysOn ? 'disabled' : '';
    var checkboxId = 'phase-toggle-' + scope + '-' + phase.id.replace(/\./g, '-');
    var labelCursorClass = isAlwaysOn ? 'phase-settings__label--disabled' : 'phase-settings__label--enabled';
    var rowPendingClass = isPending ? ' phase-settings__row--pending' : '';

    return '<div class="phase-settings__row' + rowPendingClass + '">'
      + '<input type="checkbox" class="phase-settings__checkbox" id="' + checkboxId + '"'
      + ' data-phase-id="' + escapeHtml(phase.id) + '"'
      + ' data-scope="' + escapeHtml(scope) + '"'
      + ' data-endpoint="' + escapeHtml(endpointBase) + '"'
      + ' ' + checkedAttr
      + ' ' + disabledAttr
      + ' onchange="_onPhaseToggleChange(this)">'
      + '<label for="' + checkboxId + '" class="phase-settings__label ' + labelCursorClass + '">'
      + _phaseLabel(phase)
      + _phaseBadges(phase)
      + (isPending ? '<span class="phase-settings__pending-dot" title="Unsaved"></span>' : '')
      + '</label>'
      + '</div>';
  }).join('');
}

async function _onPhaseToggleChange(checkbox) {
  var phaseId = checkbox.getAttribute('data-phase-id');
  var endpointBase = checkbox.getAttribute('data-endpoint');
  var enabled = checkbox.checked;
  var container = checkbox.closest('.phase-settings__container');

  if (container && container._batchSave) {
    container._pendingSettings[phaseId] = enabled;
    _phaseRefreshRows(container);
    return;
  }

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

function _phaseRefreshRows(container) {
  var rowsEl = container.querySelector('.phase-settings__rows');
  if (!rowsEl) return;
  rowsEl.innerHTML = _renderPhaseRows(
    container._phases,
    container._enabledMap,
    container._endpointBase,
    container._scope,
    container._pendingSettings
  );
  _phaseUpdateSaveBar(container);
}

function _phaseUpdateSaveBar(container) {
  var saveBtn = container.querySelector('.phase-settings__save-btn');
  var discardBtn = container.querySelector('.phase-settings__discard-btn');
  if (!saveBtn) return;
  var hasPending = Object.keys(container._pendingSettings).length > 0;
  saveBtn.disabled = !hasPending;
  if (discardBtn) discardBtn.disabled = !hasPending;
}

async function _phaseSaveSettings(container) {
  var saveBtn = container.querySelector('.phase-settings__save-btn');
  if (saveBtn) saveBtn.disabled = true;

  var saves = [];
  if (Object.keys(container._pendingSettings).length > 0) {
    saves.push(
      apiPut(container._endpointBase, { settings: container._pendingSettings })
        .then(function() {
          return apiGet(container._endpointBase).then(function(refreshedData) {
            var refreshed = refreshedData.settings || {};
            container._pendingSettings = {};
            container._enabledMap = {};
            Object.keys(refreshed).forEach(function(id) {
              container._enabledMap[id] = !!refreshed[id];
            });
            _phaseRefreshRows(container);
          });
        })
    );
  }

  try {
    await Promise.all(saves);
    if (typeof showToast === 'function') {
      showToast(_t('messages.phaseSettingsSaved'));
    }
  } catch (e) {
    if (typeof showToast === 'function') {
      showToast(_t('messages.phaseSettingsSaveFailed').replace('{error}', e.message));
    }
    if (saveBtn) saveBtn.disabled = false;
  }
}

function _phaseDiscardSettings(container) {
  container._pendingSettings = {};
  _phaseRefreshRows(container);
}

async function renderPhaseToggleCard(container, scope, endpointBase, options) {
  if (!container) return;

  var batchSave = !!(options && options.batchSave);

  container.innerHTML = '<div class="phase-settings__loading">' + _t('research.loading') + '</div>';

  var phases = [];
  var enabledMap = {};

  try {
    var availableData = await apiGet('/api/phases/available');
    phases = availableData.phases || [];
  } catch (e) {
    container.innerHTML = '<div class="phase-settings__error">Failed to load phases: ' + escapeHtml(e.message) + '</div>';
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

  if (batchSave) {
    container.className = (container.className || '') + ' phase-settings__container';
    container._batchSave = true;
    container._pendingSettings = {};
    container._phases = phases;
    container._enabledMap = enabledMap;
    container._endpointBase = endpointBase;
    container._scope = scope;

    container.innerHTML = '<div class="phase-settings__desc">' + escapeHtml(_t('config.phaseSettingsDesc')) + '</div>'
      + '<div class="phase-settings__rows">'
      + _renderPhaseRows(phases, enabledMap, endpointBase, scope, {})
      + '</div>'
      + '<div class="phase-settings__save-bar">'
      + '<button class="phase-settings__save-btn" disabled onclick="_phaseSaveSettings(this.closest(\'.phase-settings__container\'))">'
      + _t('buttons.savePhaseSettings')
      + '</button>'
      + '<button class="phase-settings__discard-btn" disabled onclick="_phaseDiscardSettings(this.closest(\'.phase-settings__container\'))">'
      + _t('buttons.discardPhaseSettings')
      + '</button>'
      + '</div>';
  } else {
    container.innerHTML = '<div class="phase-settings__desc">' + escapeHtml(_t('config.phaseSettingsDesc')) + '</div>'
      + _renderPhaseRows(phases, enabledMap, endpointBase, scope, null);
  }
}
