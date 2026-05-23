// ═══════════════════════════════════════════════
//  ADVANCE MODES — per-boundary dropdown section
// ═══════════════════════════════════════════════

var _ADVANCE_BOUNDARIES = [
  { key: '1',   labelKey: 'advanceModes.boundary1Name',   descKey: 'advanceModes.boundary1Desc' },
  { key: '2',   labelKey: 'advanceModes.boundary2Name',   descKey: 'advanceModes.boundary2Desc' },
  { key: '3.1', labelKey: 'advanceModes.boundary31Name',  descKey: 'advanceModes.boundary31Desc' },
  { key: '3.x', labelKey: 'advanceModes.boundary3xName',  descKey: 'advanceModes.boundary3xDesc' },
  { key: '4',   labelKey: 'advanceModes.boundary4Name',   descKey: 'advanceModes.boundary4Desc' },
  { key: '5',   labelKey: 'advanceModes.boundary5Name',   descKey: 'advanceModes.boundary5Desc' }
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

  return _ADVANCE_BOUNDARIES.map(function(boundary) {
    var currentValue = boundary.key in pending ? pending[boundary.key] : (canonical[boundary.key] || 'none');
    var isPending = boundary.key in pending;
    var boundaryName = typeof t === 'function' ? t(boundary.labelKey) : boundary.labelKey;
    var boundaryDesc = typeof t === 'function' ? t(boundary.descKey) : boundary.descKey;
    var rowClass = 'advance-modes__row' + (isPending ? ' advance-modes__row--pending' : '');

    return '<div class="' + rowClass + '">'
      + '<div class="advance-modes__label-group">'
      + '<label class="advance-modes__label">'
      + _amEscape(boundaryName)
      + (isPending ? '<span class="phase-settings__pending-dot" title="Unsaved"></span>' : '')
      + '</label>'
      + '<span class="advance-modes__desc">' + _amEscape(boundaryDesc) + '</span>'
      + '</div>'
      + '<select class="advance-modes__select" data-boundary-key="' + _amEscape(boundary.key) + '"'
      + ' onchange="_amOnChange(this)">'
      + _amRenderOptions(currentValue)
      + '</select>'
      + '</div>';
  }).join('');
}

function _amOnChange(select) {
  var container = select.closest('.advance-modes__container');
  if (!container) return;
  var boundaryKey = select.getAttribute('data-boundary-key');
  container._amPending[boundaryKey] = select.value;
  _amRefresh(container);
}

function _amRefresh(container) {
  var rowsEl = container.querySelector('.advance-modes__rows');
  if (rowsEl) rowsEl.innerHTML = _amRenderRows(container);
  _amUpdateSaveBar(container);
}

function _amUpdateSaveBar(container) {
  var saveBtn = container.querySelector('.advance-modes__save-btn');
  if (!saveBtn) return;
  saveBtn.disabled = Object.keys(container._amPending).length === 0;
}

async function _amSave(container) {
  if (!container || Object.keys(container._amPending).length === 0) return;
  var projectId = container._amProjectId;
  var endpoint = '/api/projects/' + encodeURIComponent(projectId) + '/advance-modes';
  try {
    await apiPut(endpoint, { modes: container._amPending });
    Object.assign(container._amCanonical, container._amPending);
    container._amPending = {};
    try {
      var refreshed = await apiGet(endpoint);
      container._amCanonical = refreshed;
    } catch (e) {
      console.warn('advance-modes: refresh after save failed', e);
    }
  } catch (e) {
    console.warn('advance-modes: save failed', e);
  }
  _amRefresh(container);
}

async function renderAdvanceModeSection(container, projectId) {
  if (!container) return;

  container.classList.add('advance-modes__container');
  container._amCanonical = {};
  container._amPending = {};
  container._amProjectId = projectId;

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
    + '</div>'
    + '<div class="advance-modes__footer">'
    + '<button class="btn btn-primary advance-modes__save-btn" disabled onclick="_amSave(this.closest(\'.advance-modes__container\'))">'
    + (typeof t === 'function' ? t('buttons.save') : 'Save')
    + '</button>'
    + '</div>';
}
