// ═══════════════════════════════════════════════
//  ACCEPTANCE CRITERIA
// ═══════════════════════════════════════════════
var CRITERIA_DATA = AppState.criteria;

function loadCriteria() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/criteria')
    .then(function(data) {
      if (data && data.criteria) {
        AppState.criteria = data.criteria;
        CRITERIA_DATA = AppState.criteria;
        renderCriteria();
        EventBus.emit('criteria:changed', data.criteria);
      }
    });
}

var CRITERIA_TYPE_KEYS = { unit_test: 'criteria.unitTest', integration_test: 'criteria.integrationTest', bdd_scenario: 'criteria.bddScenario', custom: 'criteria.custom' };

function _criterionTypeLabel(type) {
  return t(CRITERIA_TYPE_KEYS[type] || 'criteria.' + type);
}

function _criterionStatusPill(c) {
  if (c.status === 'proposed') {
    return '<span class="pill info">' + (c.source === 'agent' ? t('badges.proposedByAgent') : t('badges.pendingReview')) + '</span>';
  }
  if (c.status === 'accepted') return '<span class="pill ok">' + t('badges.accepted') + '</span>';
  if (c.status === 'rejected') return '<span class="pill bad">' + t('badges.rejected') + '</span>';
  return '';
}

function _criterionValidationHtml(c) {
  var message = escapeHtml(c.validation_message || '');
  if (c.type === 'custom') {
    if (c.validated === 1) return '<span class="pill ok">' + t('badges.userApproved') + '</span>';
    if (c.validated === -1) {
      return '<span class="pill bad">' + t('badges.userRejected') + '</span>' +
        '<button class="btn xs" onclick="validateCriterion(' + c.id + ', true)">' + t('buttons.reapprove') + '</button>';
    }
    return '<button class="btn xs" onclick="validateCriterionManual(' + c.id + ')">' + t('buttons.validate') + '</button>';
  }
  if (c.validated === 1) return '<span class="pill ok" title="' + message + '">' + t('badges.passed') + '</span>';
  if (c.validated === -1) return '<span class="pill bad" title="' + message + '">' + t('badges.failed') + '</span>';
  return '';
}

function _criterionCommentsHtml(c) {
  if (typeof COMMENTS === 'undefined') return '';
  var matching = (COMMENTS.criteria || []).filter(function(cmt) { return cmt.target === 'criterion:' + c.id && !cmt.resolved; });
  if (!matching.length) return '';
  return '<div class="vs g4">' + matching.map(function(cmt) {
    return '<div class="cmt">' + cpIcon('comment', 14) + '<span class="grow brk">' + escapeHtml(cmt.text) + '</span></div>';
  }).join('') + '</div>';
}

function _buildCriterionHtml(c) {
  var hasDetails = c.details && (c.details.file || c.details.test_names || c.details.scenario_names || c.details.instruction);
  var detailsLink = hasDetails
    ? '<a class="criteria-details-link" onclick="showCriterionDetails(' + c.id + ')" title="' + t('criteria.viewDetails') + '">' + t('criteria.detailsLink') + '</a>'
    : '';
  return '<div class="row top criteria-item">' +
    '<div class="grow vs g4">' +
      '<div class="hs top between"><span class="grow brk">' + escapeHtml(c.description) + '</span>' + detailsLink + '</div>' +
      '<div class="hs wrap"><span class="tag">' + escapeHtml(_criterionTypeLabel(c.type)) + '</span>' +
        _criterionStatusPill(c) + _criterionValidationHtml(c) +
        '<button class="btn ic xs criteria-delete" onclick="deleteCriterion(' + c.id + ')" title="' + t('buttons.delete') + '">' + cpIcon('x', 12) + '</button></div>' +
      _criterionCommentsHtml(c) +
    '</div>' +
  '</div>';
}

function _renderCriteriaTally() {
  var tally = document.getElementById('criteriaTally');
  if (!tally) return;
  var proposed = CRITERIA_DATA.filter(function(c) { return c.status === 'proposed'; }).length;
  if (proposed) tally.textContent = t('criteria.proposedTally', {n: proposed});
  else tally.textContent = CRITERIA_DATA.length ? _criteriaAcceptedTally() : '';
}

function _criteriaAcceptedTally() {
  var accepted = CRITERIA_DATA.filter(function(c) { return c.status === 'accepted'; }).length;
  return t('overview.criteriaCount', {accepted: accepted, total: CRITERIA_DATA.length});
}

function renderCriteria() {
  var list = document.getElementById('criteriaList');
  if (!list) return;
  _renderCriteriaTally();

  if (CRITERIA_DATA.length === 0) {
    list.innerHTML = '<div class="empty">' + t('criteria.noEntries') + '</div>';
    return;
  }

  list.innerHTML = CRITERIA_DATA.map(_buildCriterionHtml).join('') +
    '<div class="row sm dim">' + t('criteria.acceptedOnPlanApproval') + '</div>';
}

function _ensureCriterionDialog() {
  var modal = document.getElementById('criterionDetailModal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'criterionDetailModal';
  modal.className = 'file-preview-modal';
  modal.onclick = function(e) { if (e.target === modal) modal.classList.remove('open'); };
  modal.innerHTML = '<div class="file-preview-content criterion-dialog" role="dialog" aria-modal="true">' +
    '<div class="file-preview-header">' +
      '<h3 class="grow" id="criterionDetailTitle"></h3>' +
      '<button class="btn ic xs" onclick="document.getElementById(\'criterionDetailModal\').classList.remove(\'open\')" aria-label="' + escapeHtml(t('buttons.close')) + '">' + cpIcon('x', 14) + '</button>' +
    '</div>' +
    '<div class="file-preview-body vs g12" id="criterionDetailBody"></div>' +
  '</div>';
  document.body.appendChild(modal);
  return modal;
}

function _criterionDetailSection(label, bodyHtml) {
  return '<div class="vs g4"><span class="cap">' + label + '</span>' + bodyHtml + '</div>';
}

function _buildCriterionDetailsHtml(c) {
  var d = c.details;
  var html = '';
  if (d.file) html += _criterionDetailSection(t('labels.file'), '<code class="mono brk">' + escapeHtml(d.file) + '</code>');

  var names = d.test_names || d.scenario_names || [];
  if (names.length > 0) {
    var label = (d.test_names ? t('labels.testMethods') : t('labels.scenarios')) + ' (' + names.length + ')';
    html += _criterionDetailSection(label, '<div class="inset vs g4">' +
      names.map(function(n) { return '<code class="mono brk">' + escapeHtml(n) + '</code>'; }).join('') + '</div>');
  }

  if (d.instruction) html += _criterionDetailSection(t('labels.instruction'), '<div class="brk">' + escapeHtml(d.instruction) + '</div>');

  if (c.validation_message) {
    var tone = c.validated === 1 ? 'ok' : c.validated === -1 ? 'bad' : '';
    html += _criterionDetailSection(t('labels.validationResult'), '<div><span class="pill ' + tone + ' criteria-validation">' + escapeHtml(c.validation_message) + '</span></div>');
  }
  return html || '<div class="empty">' + t('criteria.noDetailsAvailable') + '</div>';
}

function showCriterionDetails(id) {
  var c = CRITERIA_DATA.find(function(item) { return item.id === id; });
  if (!c || !c.details) return;

  var modal = _ensureCriterionDialog();
  document.getElementById('criterionDetailTitle').textContent = _criterionTypeLabel(c.type) + ': ' + c.description;
  document.getElementById('criterionDetailBody').innerHTML = _buildCriterionDetailsHtml(c);
  modal.classList.add('open');
}

function addCriterion() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var type = document.getElementById('criteriaType').value;
  var desc = document.getElementById('criteriaDesc').value.trim();
  if (!desc) return;

  var body = { type: type, description: desc };

  if (type !== 'custom') {
    var file = document.getElementById('criteriaFile').value.trim();
    var namesStr = document.getElementById('criteriaTestNames').value.trim();
    var details = {};
    if (file) details.file = file;
    if (namesStr) {
      var nameKey = type === 'bdd_scenario' ? 'scenario_names' : 'test_names';
      details[nameKey] = namesStr.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    }
    if (Object.keys(details).length > 0) {
      body.details_json = JSON.stringify(details);
    }
  } else {
    var customDesc = document.getElementById('criteriaDesc').value.trim();
    if (customDesc) {
      body.details_json = JSON.stringify({ instruction: customDesc });
    }
  }

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/criteria', body)
    .then(function() {
      document.getElementById('criteriaDesc').value = '';
      document.getElementById('criteriaFile').value = '';
      document.getElementById('criteriaTestNames').value = '';
      loadCriteria();
    });
}

function deleteCriterion(id) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  apiDelete('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/criteria/' + id)
    .then(function() { loadCriteria(); });
}

async function validateCriterionManual(id) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    await apiPut('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/criteria/' + id + '/validate', { passed: true });
    await loadCriteria();
  } catch (err) {
    showToast(t('messages.failedToUpdate').replace('{error}', err && err.message ? err.message : String(err)));
  }
}

async function validateCriterion(id, passed) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    await apiPut('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/criteria/' + id + '/validate', { passed: passed });
    await loadCriteria();
  } catch (err) {
    showToast(t('messages.failedToUpdate').replace('{error}', err && err.message ? err.message : String(err)));
  }
}

document.addEventListener('DOMContentLoaded', function() {
  var typeSelect = document.getElementById('criteriaType');
  if (typeSelect) {
    var detailsForm = document.getElementById('criteriaDetailsForm');
    // Show details for initial value (unit_test)
    if (detailsForm && typeSelect.value !== 'custom') {
      detailsForm.style.display = 'block';
    }
    typeSelect.addEventListener('change', function() {
      if (detailsForm) {
        detailsForm.style.display = this.value !== 'custom' ? 'block' : 'none';
      }
    });
  }
});

EventBus.on('state:refreshed', function() {
  if (typeof loadCriteria === 'function') loadCriteria();
});
