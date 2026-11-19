// ═══════════════════════════════════════════════
//  PROJECT RULES (.claude/rules/*.md)
// ═══════════════════════════════════════════════
var RULES_DATA = [];
var RULE_NAME_REGEX = /^[a-z0-9][a-z0-9\-_]{0,62}$/;
var _currentRuleName = null;

function loadRules() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  apiGet('/api/projects/' + encodeURIComponent(ctx.projectId) + '/rules')
    .then(function(data) {
      RULES_DATA = Array.isArray(data) ? data : [];
      renderRules();
    })
    .catch(function(e) { console.warn('rules loadRules failed:', e && e.message); });
}

function renderRules() {
  var list = document.getElementById('rulesList');
  if (!list) return;

  if (RULES_DATA.length === 0) {
    list.innerHTML = '<p class="dim">' + t('rules.noEntries') + '</p>';
    return;
  }

  list.innerHTML = RULES_DATA.map(function(r) {
    var isDefault = r.source === 'default';
    var sourceLabel = isDefault ? t('rules.sourceDefault') : t('rules.sourceUser');
    var nameSafe = escapeHtml(r.name);
    var descSafe = escapeHtml(r.description || '');
    var pathsHtml = (r.paths || []).map(function(p) {
      return '<code class="rules-item-path-chip">' + escapeHtml(p) + '</code>';
    }).join('');

    var errorHtml = '';
    if (r.error) {
      errorHtml = '<div class="rules-item-error">' + escapeHtml(r.error) + '</div>';
    }

    var editBtn = '<button class="btn xs" onclick="openRuleModal(\'' + encodeURIComponent(r.name) + '\')"' +
      (isDefault ? ' disabled title="' + t('rules.sourceDefault') + '"' : '') + '>' +
      t('buttons.edit') + '</button>';
    var deleteBtn = isDefault ? '' :
      ' <button class="btn xs danger" onclick="deleteRuleConfirm(\'' + encodeURIComponent(r.name) + '\')" title="' + t('buttons.delete') + '">&times;</button>';

    return '<div class="rules-item">' +
      '<div class="rules-item-header">' +
        '<div>' +
          '<span class="rules-item-name">' + nameSafe + '</span>' +
          ' <span class="rules-item-source">' + sourceLabel + '</span>' +
        '</div>' +
        '<div class="rules-item-actions">' +
          editBtn + deleteBtn +
        '</div>' +
      '</div>' +
      (descSafe ? '<div class="rules-item-desc">' + descSafe + '</div>' : '') +
      (pathsHtml ? '<div class="rules-item-paths">' + pathsHtml + '</div>' : '') +
      errorHtml +
    '</div>';
  }).join('');
}

function ensureRuleModal() {
  var modal = document.getElementById('ruleEditModal');
  if (modal) return modal;

  modal = document.createElement('div');
  modal.id = 'ruleEditModal';
  modal.className = 'dlg-scrim rule-scrim';
  modal.onclick = function(e) { if (e.target === modal) modal.classList.remove('open'); };
  modal.innerHTML = '<div class="dlg rule-dlg" role="dialog">' +
    '<h3 id="ruleEditTitle"></h3>' +
    '<label class="lbl"><span data-i18n="rules.name">Name</span>' +
      '<input type="text" id="ruleFieldName" class="inp" data-i18n-placeholder="placeholders.ruleName" /></label>' +
    '<label class="lbl"><span data-i18n="rules.description">Description</span>' +
      '<input type="text" id="ruleFieldDescription" class="inp" /></label>' +
    '<label class="lbl"><span data-i18n="rules.paths">Paths (globs, one per line)</span>' +
      '<textarea id="ruleFieldPaths" class="ta mono rule-paths" data-i18n-placeholder="placeholders.rulePaths"></textarea></label>' +
    '<label class="lbl"><span data-i18n="rules.body">Body (Markdown)</span>' +
      '<textarea id="ruleFieldBody" class="ta mono rule-body" data-i18n-placeholder="placeholders.ruleBody"></textarea></label>' +
    '<div class="hs rule-actions">' +
      '<button class="btn ghost" onclick="document.getElementById(\'ruleEditModal\').classList.remove(\'open\')" data-i18n="buttons.close">Close</button>' +
      '<button class="btn pri" id="ruleSaveButton" data-i18n="buttons.saveRule">Save rule</button>' +
    '</div>' +
  '</div>';
  document.body.appendChild(modal);
  applyI18nToDOM();

  var saveBtn = document.getElementById('ruleSaveButton');
  if (saveBtn) {
    saveBtn.onclick = function() { saveRuleFromModal(); };
  }

  return modal;
}

function openRuleModal(encodedName) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var modal = ensureRuleModal();
  var nameField = document.getElementById('ruleFieldName');
  var descField = document.getElementById('ruleFieldDescription');
  var pathsField = document.getElementById('ruleFieldPaths');
  var bodyField = document.getElementById('ruleFieldBody');
  var title = document.getElementById('ruleEditTitle');

  var isEdit = !!encodedName;
  var ruleName = encodedName ? decodeURIComponent(encodedName) : '';
  _currentRuleName = isEdit ? ruleName : null;

  nameField.value = '';
  descField.value = '';
  pathsField.value = '';
  bodyField.value = '';
  nameField.disabled = isEdit;

  if (isEdit) {
    title.textContent = t('rules.editTitle', {name: ruleName});
    apiGet('/api/projects/' + encodeURIComponent(ctx.projectId) + '/rules/' + encodeURIComponent(ruleName))
      .then(function(rule) {
        nameField.value = rule.name || ruleName;
        descField.value = rule.description || '';
        pathsField.value = (rule.paths || []).join('\n');
        bodyField.value = rule.body || '';
      })
      .catch(function(e) { showToast(t('messages.ruleSaveFailed', {error: e.message})); });
  } else {
    title.textContent = t('rules.createTitle');
  }

  modal.classList.add('open');
  setTimeout(function() { (isEdit ? descField : nameField).focus(); }, 50);
}

function saveRuleFromModal() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var isEdit = _currentRuleName !== null;
  var originalName = _currentRuleName || '';

  var name = document.getElementById('ruleFieldName').value.trim();
  var description = document.getElementById('ruleFieldDescription').value.trim();
  var pathsRaw = document.getElementById('ruleFieldPaths').value;
  var body = document.getElementById('ruleFieldBody').value;

  var paths = pathsRaw.split('\n').map(function(s) { return s.trim(); }).filter(function(s) { return s.length > 0; });

  if (!isEdit) {
    if (!name || !RULE_NAME_REGEX.test(name)) {
      showToast(t('rules.invalidName'));
      return;
    }
  }
  if (!description) {
    showToast(t('messages.ruleSaveFailed', {error: t('rules.description')}));
    return;
  }
  if (paths.length === 0) {
    showToast(t('rules.pathsRequired'));
    return;
  }
  if (!body || !body.trim()) {
    showToast(t('messages.ruleSaveFailed', {error: t('rules.body')}));
    return;
  }

  var base = '/api/projects/' + encodeURIComponent(ctx.projectId) + '/rules';
  var request;
  if (isEdit) {
    request = apiPut(base + '/' + encodeURIComponent(originalName), {
      description: description, paths: paths, body: body
    });
  } else {
    request = apiPost(base, {
      name: name, description: description, paths: paths, body: body
    });
  }

  request
    .then(function() {
      showToast(t('messages.ruleSaved'));
      var modal = document.getElementById('ruleEditModal');
      if (modal) modal.classList.remove('open');
      loadRules();
    })
    .catch(function(e) { showToast(t('messages.ruleSaveFailed', {error: e.message})); });
}

function deleteRuleConfirm(encodedName) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  var ruleName = decodeURIComponent(encodedName);
  if (!confirm(t('rules.confirmDelete', {name: ruleName}))) return;

  apiDelete('/api/projects/' + encodeURIComponent(ctx.projectId) + '/rules/' + encodeURIComponent(ruleName))
    .then(function() {
      showToast(t('messages.ruleDeleted'));
      loadRules();
    })
    .catch(function(e) { showToast(t('messages.ruleSaveFailed', {error: e.message})); });
}
