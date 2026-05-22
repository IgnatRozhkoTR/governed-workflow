// ═══════════════════════════════════════════════
//  ADVANCE MODES — per-major-phase dropdown section
// ═══════════════════════════════════════════════

var _am = typeof t === 'function' ? t : function(k) { return k; };

var _ADVANCE_MAJOR_PHASES = [
  { id: 1, nameKey: 'advanceModes.phase1Name' },
  { id: 2, nameKey: 'advanceModes.phase2Name' },
  { id: 3, nameKey: 'advanceModes.phase3Name' },
  { id: 4, nameKey: 'advanceModes.phase4Name' },
  { id: 5, nameKey: 'advanceModes.phase5Name' }
];

var _ADVANCE_MODE_OPTIONS = [
  { value: 'none',    labelKey: 'advanceModes.modeNone',    title: 'advanceModes.modeNoneTitle' },
  { value: 'compact', labelKey: 'advanceModes.modeCompact', title: 'advanceModes.modeCompactTitle' },
  { value: 'clear',   labelKey: 'advanceModes.modeClear',   title: 'advanceModes.modeClearTitle' }
];

function _amEscape(str) {
  var el = document.createElement('span');
  el.textContent = String(str);
  return el.innerHTML;
}

function _amRenderOptions(selectedValue) {
  return _ADVANCE_MODE_OPTIONS.map(function(opt) {
    var selected = opt.value === selectedValue ? ' selected' : '';
    var label = typeof t === 'function' ? t(opt.labelKey) : opt.labelKey;
    var title = typeof t === 'function' ? t(opt.title) : opt.title;
    return '<option value="' + _amEscape(opt.value) + '"' + selected + ' title="' + _amEscape(title) + '">'
      + _amEscape(label) + '</option>';
  }).join('');
}

function _amRenderRows(container) {
  var canonical = container._amCanonical;
  var pending = container._amPending;

  return _ADVANCE_MAJOR_PHASES.map(function(phase) {
    var currentValue = phase.id in pending ? pending[phase.id] : (canonical[phase.id] || 'none');
    var isPending = phase.id in pending;
    var phaseName = typeof t === 'function' ? t(phase.nameKey) : phase.nameKey;
    var rowClass = 'advance-modes__row' + (isPending ? ' advance-modes__row--pending' : '');

    return '<div class="' + rowClass + '">'
      + '<label class="advance-modes__label">'
      + _amEscape(t('advanceModes.phaseLabel').replace('{phase}', phase.id))
      + ' — '
      + _amEscape(phaseName)
      + (isPending ? '<span class="phase-settings__pending-dot" title="Unsaved"></span>' : '')
      + '</label>'
      + '<select class="advance-modes__select" data-phase-id="' + phase.id + '"'
      + ' onchange="_amOnChange(this)">'
      + _amRenderOptions(currentValue)
      + '</select>'
      + '</div>';
  }).join('');
}

function _amOnChange(select) {
  var container = select.closest('.advance-modes__container');
  if (!container) return;
  var phaseId = parseInt(select.getAttribute('data-phase-id'), 10);
  container._amPending[phaseId] = select.value;
  _amRefresh(container);
}

function _amRefresh(container) {
  var rowsEl = container.querySelector('.advance-modes__rows');
  if (rowsEl) rowsEl.innerHTML = _amRenderRows(container);
  _amNotifySharedSaveBar(container);
}

function _amNotifySharedSaveBar(container) {
  var sharedContainer = container._amSharedPhaseContainer;
  if (!sharedContainer) return;
  _phaseUpdateSaveBar(sharedContainer);
}

function amHasPending(container) {
  if (!container) return false;
  return Object.keys(container._amPending).length > 0;
}

async function amSave(container, projectId) {
  if (!container || !amHasPending(container)) return;
  var endpoint = '/api/projects/' + encodeURIComponent(projectId) + '/advance-modes';
  await apiPut(endpoint, { modes: container._amPending });
  var refreshed = await apiGet(endpoint);
  container._amCanonical = refreshed;
  container._amPending = {};
  _amRefresh(container);
}

function amDiscard(container) {
  if (!container) return;
  container._amPending = {};
  _amRefresh(container);
}

async function renderAdvanceModeSection(container, projectId) {
  if (!container) return;

  container.classList.add('advance-modes__container');
  container._amCanonical = {};
  container._amPending = {};
  container._amProjectId = projectId;
  container._amSharedPhaseContainer = null;

  container.innerHTML = '<div class="phase-settings__loading">' + (typeof t === 'function' ? t('research.loading') : 'Loading...') + '</div>';

  try {
    var endpoint = '/api/projects/' + encodeURIComponent(projectId) + '/advance-modes';
    var data = await apiGet(endpoint);
    container._amCanonical = data || {};
  } catch (e) {
    container.innerHTML = '<div class="phase-settings__error">Failed to load advance modes: ' + _amEscape(e.message) + '</div>';
    return;
  }

  var desc = typeof t === 'function' ? t('advanceModes.desc') : '';
  container.innerHTML = '<div class="phase-settings__desc">' + _amEscape(desc) + '</div>'
    + '<div class="advance-modes__rows">'
    + _amRenderRows(container)
    + '</div>';
}
