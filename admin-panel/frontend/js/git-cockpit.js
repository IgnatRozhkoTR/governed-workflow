// ═══════════════════════════════════════════════
//  GIT COCKPIT (multi-repo overview, PRs, repositories)
// ═══════════════════════════════════════════════

var _gcCtx = null;
var _gcProjectType = 'single';
var _gcRepos = [];        // project-level repo registry rows
var _gcRepoState = null;  // {attached, available} for the current workspace
var _gcPrs = [];

function _gcSectionActive() {
  return typeof _currentSettingsSection === 'function' && _currentSettingsSection() === 'git';
}

async function loadGitCockpit() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  _gcCtx = ctx;

  var panel = document.getElementById('gcConvertPanel');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }

  await _gcLoadProjectType(ctx.projectId);
  _gcRenderOverview();
  await _gcRenderRepositories();
  await _gcLoadAndRenderPrs();
}

async function _gcLoadProjectType(projectId) {
  try {
    var data = await apiListProjects();
    var project = (data.projects || []).find(function(p) { return p.id === projectId; });
    _gcProjectType = (project && project.project_type) || 'single';
  } catch (e) {
    _gcProjectType = 'single';
  }
}

// ─── Overview ───

function _gcRenderOverview() {
  var body = document.getElementById('gcOverviewBody');
  if (!body) return;

  var branch = LOCK_DATA.branch || (_gcCtx && _gcCtx.branch) || '';
  var sourceBranch = LOCK_DATA.source_branch || null;
  var workingDir = LOCK_DATA.working_dir || '';
  var typeLabel = _gcProjectType === 'multi' ? t('gitCockpit.overview.typeMulti') : t('gitCockpit.overview.typeSingle');
  var typeBadgeClass = _gcProjectType === 'multi' ? 'gc-badge--multi' : 'gc-badge--single';

  var branchValue = sourceBranch
    ? escapeHtml(branch) + ' <span class="gc-arrow">&rarr;</span> ' + escapeHtml(sourceBranch)
    : escapeHtml(branch);

  body.innerHTML =
    '<div class="gc-overview-row">' +
      '<span class="gc-overview-label">' + t('gitCockpit.overview.projectType') + '</span>' +
      '<span class="gc-badge ' + typeBadgeClass + '">' + escapeHtml(typeLabel) + '</span>' +
    '</div>' +
    '<div class="gc-overview-row">' +
      '<span class="gc-overview-label">' + t('gitCockpit.overview.workspaceBranch') + '</span>' +
      '<span class="gc-overview-value">' + branchValue + '</span>' +
    '</div>' +
    '<div class="gc-overview-row">' +
      '<span class="gc-overview-label">' + t('gitCockpit.overview.workingDir') + '</span>' +
      '<span class="gc-overview-value gc-mono">' + escapeHtml(workingDir || '—') + '</span>' +
    '</div>';
}

// ─── Pull requests ───

async function _gcLoadAndRenderPrs() {
  var section = document.getElementById('gcPrsSection');
  if (!_gcCtx) return;

  try {
    var data = await apiListWorkspacePrs(_gcCtx.projectId, _gcCtx.branch);
    _gcPrs = data.prs || [];
    if (section) section.style.display = '';
  } catch (e) {
    _gcPrs = [];
    if (section) section.style.display = 'none';
    return;
  }

  _gcRenderPrs();
  _gcPopulatePrRepoSelect();
}

function _gcShortenUrl(url) {
  if (!url) return '';
  var stripped = url.replace(/^https?:\/\//, '');
  return stripped.length > 60 ? stripped.slice(0, 57) + '…' : stripped;
}

function _gcRenderPrs() {
  var list = document.getElementById('gcPrsList');
  if (!list) return;

  if (!_gcPrs.length) {
    list.innerHTML = '<div class="gc-empty-state">' + t('gitCockpit.prs.empty') + '</div>';
    return;
  }

  list.innerHTML = _gcPrs.map(function(pr) {
    var chipLabel = pr.name || pr.rel_path || t('gitCockpit.prs.repoWholeProject');
    var linkLabel = pr.title || _gcShortenUrl(pr.url);
    return '<div class="gc-pr-row">' +
      '<span class="gc-pr-chip">' + escapeHtml(chipLabel) + '</span>' +
      '<a class="gc-pr-link" href="' + escapeAttr(pr.url) + '" target="_blank" rel="noopener">' + escapeHtml(linkLabel) + '</a>' +
      '<button class="gc-pr-delete" title="' + t('gitCockpit.prs.deleteTitle') + '" onclick="gcDeletePr(' + pr.id + ')">&times;</button>' +
    '</div>';
  }).join('');
}

function _gcPopulatePrRepoSelect() {
  var select = document.getElementById('gcPrRepoSelect');
  if (!select) return;

  if (_gcProjectType !== 'multi' || !(_gcRepos && _gcRepos.length)) {
    select.style.display = 'none';
    select.innerHTML = '';
    return;
  }

  select.style.display = '';
  select.innerHTML = '<option value="">' + t('gitCockpit.prs.repoWholeProject') + '</option>' +
    _gcRepos.map(function(r) { return '<option value="' + r.id + '">' + escapeHtml(r.name) + '</option>'; }).join('');
}

async function gcAddPr() {
  var urlInput = document.getElementById('gcPrUrlInput');
  var repoSelect = document.getElementById('gcPrRepoSelect');
  var titleInput = document.getElementById('gcPrTitleInput');
  if (!urlInput || !_gcCtx) return;

  var url = urlInput.value.trim();
  if (!url) {
    showToast(t('messages.gcPrUrlRequired'));
    return;
  }

  var body = { url: url };
  var title = titleInput ? titleInput.value.trim() : '';
  if (title) body.title = title;
  if (repoSelect && repoSelect.style.display !== 'none' && repoSelect.value) {
    body.repo_id = parseInt(repoSelect.value, 10);
  }

  try {
    await apiAddWorkspacePr(_gcCtx.projectId, _gcCtx.branch, body);
    urlInput.value = '';
    if (titleInput) titleInput.value = '';
    if (repoSelect) repoSelect.value = '';
    showToast(t('messages.gcPrAdded'));
    await _gcLoadAndRenderPrs();
  } catch (e) {
    showToast(t('messages.gcPrAddFailed', {error: e.message}));
  }
}

function gcDeletePr(prId) {
  if (!_gcCtx) return;
  if (!confirm(t('gitCockpit.prs.confirmDelete'))) return;

  apiDeleteWorkspacePr(_gcCtx.projectId, _gcCtx.branch, prId)
    .then(function() {
      showToast(t('messages.gcPrDeleted'));
      return _gcLoadAndRenderPrs();
    })
    .catch(function(e) {
      showToast(t('messages.gcPrDeleteFailed', {error: e.message}));
    });
}

// ─── Repositories ───

async function _gcRenderRepositories() {
  var convertWrap = document.getElementById('gcConvertBtnWrap');
  var defaultBranchRow = document.getElementById('gitDefaultBranchRow');
  var multiBody = document.getElementById('gcMultiReposBody');
  if (!convertWrap || !defaultBranchRow || !multiBody) return;

  if (_gcProjectType !== 'multi') {
    convertWrap.style.display = '';
    defaultBranchRow.style.display = '';
    multiBody.style.display = 'none';
    multiBody.innerHTML = '';
    _gcRepos = [];
    return;
  }

  convertWrap.style.display = 'none';
  defaultBranchRow.style.display = 'none';
  multiBody.style.display = '';

  try {
    var reposData = await apiGetProjectRepos(_gcCtx.projectId);
    _gcRepos = reposData.repos || [];
  } catch (e) {
    // Backend not ready for this endpoint yet — degrade to the single-repo look.
    multiBody.style.display = 'none';
    multiBody.innerHTML = '';
    convertWrap.style.display = '';
    defaultBranchRow.style.display = '';
    _gcRepos = [];
    return;
  }

  try {
    _gcRepoState = await apiGetWorkspaceRepoState(_gcCtx.projectId, _gcCtx.branch);
  } catch (e) {
    _gcRepoState = { attached: [], available: [] };
  }

  _gcRenderMultiReposBody();
}

function _gcRenderMultiReposBody() {
  var multiBody = document.getElementById('gcMultiReposBody');
  if (!multiBody) return;

  var attachedByRepoId = {};
  ((_gcRepoState && _gcRepoState.attached) || []).forEach(function(a) { attachedByRepoId[a.repo_id] = a; });

  var rowsHtml = (_gcRepos || []).length === 0
    ? '<div class="gc-empty-state">' + t('gitCockpit.repos.noRepos') + '</div>'
    : _gcRepos.map(function(repo) { return _gcRepoRowHtml(repo, attachedByRepoId[repo.id]); }).join('');

  multiBody.innerHTML =
    '<div class="gc-repo-list">' + rowsHtml + '</div>' +
    '<div class="gc-repo-actions-row">' +
      '<button class="btn btn-sm btn-outline" onclick="gcOpenConvertPanel(\'edit\')">' + t('gitCockpit.repos.editSelectionBtn') + '</button>' +
    '</div>';
}

function _gcRepoRowHtml(repo, attached) {
  var isAttached = !!attached;
  var relPathHtml = repo.rel_path !== repo.name
    ? '<span class="gc-repo-relpath">' + escapeHtml(repo.rel_path) + '</span>'
    : '';

  var statusBadge = isAttached
    ? '<span class="gc-badge gc-badge--attached">' + t('gitCockpit.repos.attached') + ' · ' + escapeHtml(attached.branch || '') + '</span>'
    : '<span class="gc-badge gc-badge--detached">' + t('gitCockpit.repos.notAttached') + '</span>';

  var attachBtn = !isAttached
    ? '<button class="btn btn-sm" onclick="gcAttachRepo(' + repo.id + ', this)">' + t('gitCockpit.repos.attachBtn') + '</button>'
    : '';

  var overrideDot = repo.has_rules_override ? '<span class="gc-override-dot"></span>' : '';

  return '<div class="gc-repo-row" data-repo-id="' + repo.id + '">' +
    '<div class="gc-repo-row-main">' +
      '<div class="gc-repo-identity">' +
        '<span class="gc-repo-name">' + escapeHtml(repo.name) + '</span>' +
        relPathHtml +
      '</div>' +
      '<input type="text" class="context-input gc-repo-base-input" value="' + escapeAttr(repo.base_branch || '') + '" ' +
        'onchange="gcSaveBaseBranch(' + repo.id + ', this)" placeholder="' + t('gitCockpit.repos.baseBranchPlaceholder') + '">' +
      '<span class="settings-inline-flash" id="gcBaseFlash-' + repo.id + '"></span>' +
      statusBadge +
      attachBtn +
      '<button class="btn btn-sm btn-ghost" id="gcOverrideBtn-' + repo.id + '" onclick="gcToggleOverride(' + repo.id + ')">' +
        '<span class="gc-override-btn-label">' + t('gitCockpit.repos.overrideBtn') + '</span>' +
        overrideDot +
      '</button>' +
    '</div>' +
    '<div class="gc-override-panel" id="gcOverridePanel-' + repo.id + '" style="display:none;"></div>' +
  '</div>';
}

async function gcSaveBaseBranch(repoId, inputEl) {
  if (!_gcCtx) return;

  var value = inputEl.value.trim();
  var previous = inputEl.defaultValue;
  inputEl.disabled = true;
  try {
    var updated = await apiUpdateProjectRepo(_gcCtx.projectId, repoId, { base_branch: value });
    inputEl.defaultValue = updated.base_branch != null ? updated.base_branch : value;
    var repo = (_gcRepos || []).find(function(r) { return r.id === repoId; });
    if (repo) repo.base_branch = inputEl.defaultValue;
    _flashSettingsInline('gcBaseFlash-' + repoId);
  } catch (e) {
    inputEl.value = previous;
    showToast(t('messages.gitSaveFailed', {error: e.message}));
  } finally {
    inputEl.disabled = false;
  }
}

async function gcAttachRepo(repoId, btnEl) {
  if (!_gcCtx) return;

  btnEl.disabled = true;
  btnEl.textContent = t('gitCockpit.repos.attaching');
  try {
    var result = await apiAttachWorkspaceRepo(_gcCtx.projectId, _gcCtx.branch, repoId);
    if (!_gcRepoState) _gcRepoState = { attached: [], available: [] };
    _gcRepoState.attached = (_gcRepoState.attached || []).filter(function(a) { return a.repo_id !== repoId; });
    if (result.attached) _gcRepoState.attached.push(result.attached);
    _gcRepoState.available = (_gcRepoState.available || []).filter(function(a) { return a.repo_id !== repoId; });
    _gcRenderMultiReposBody();
    var attachedRepo = (_gcRepos || []).find(function(r) { return r.id === repoId; });
    _wsNotifyBaseSync(result.base_sync, attachedRepo && attachedRepo.base_branch);
  } catch (e) {
    showToast(t('messages.gcRepoAttachFailed', {error: e.message}));
    btnEl.disabled = false;
    btnEl.textContent = t('gitCockpit.repos.attachBtn');
  }
}

async function gcToggleOverride(repoId) {
  var panel = document.getElementById('gcOverridePanel-' + repoId);
  if (!panel || !_gcCtx) return;

  if (panel.dataset.loaded === 'true') {
    panel.style.display = panel.style.display === 'none' ? '' : 'none';
    return;
  }

  panel.style.display = '';
  panel.innerHTML = '<div class="gc-override-loading">' + t('research.loading') + '</div>';
  try {
    var full = await apiGetProjectRepo(_gcCtx.projectId, repoId);
    panel.dataset.loaded = 'true';
    panel.innerHTML =
      '<textarea class="context-textarea gc-override-textarea" id="gcOverrideText-' + repoId + '" placeholder="' + t('gitCockpit.repos.overridePlaceholder') + '">' +
        escapeHtml(full.git_rules_override || '') +
      '</textarea>' +
      '<div class="gc-override-actions">' +
        '<button class="btn btn-sm" onclick="gcClearOverride(' + repoId + ')">' + t('gitCockpit.repos.overrideClear') + '</button>' +
        '<button class="btn btn-sm btn-primary" onclick="gcSaveOverride(' + repoId + ')">' + t('gitCockpit.repos.overrideSave') + '</button>' +
      '</div>';
  } catch (e) {
    panel.innerHTML = '<div class="gc-override-error">' + escapeHtml(e.message) + '</div>';
  }
}

async function gcSaveOverride(repoId) {
  var textarea = document.getElementById('gcOverrideText-' + repoId);
  if (!textarea || !_gcCtx) return;

  var content = textarea.value;
  try {
    var updated = await apiUpdateProjectRepo(_gcCtx.projectId, repoId, { git_rules_override: content });
    _gcApplyOverrideFlag(repoId, !!(updated.git_rules_override && updated.git_rules_override.length));
    showToast(t('messages.gcOverrideSaved'));
  } catch (e) {
    showToast(t('messages.gitSaveFailed', {error: e.message}));
  }
}

async function gcClearOverride(repoId) {
  if (!_gcCtx) return;

  try {
    await apiUpdateProjectRepo(_gcCtx.projectId, repoId, { git_rules_override: null });
    var textarea = document.getElementById('gcOverrideText-' + repoId);
    if (textarea) textarea.value = '';
    _gcApplyOverrideFlag(repoId, false);
    showToast(t('messages.gcOverrideCleared'));
  } catch (e) {
    showToast(t('messages.gitSaveFailed', {error: e.message}));
  }
}

function _gcApplyOverrideFlag(repoId, hasOverride) {
  var repo = (_gcRepos || []).find(function(r) { return r.id === repoId; });
  if (repo) repo.has_rules_override = hasOverride;

  var btn = document.getElementById('gcOverrideBtn-' + repoId);
  if (!btn) return;
  var existingDot = btn.querySelector('.gc-override-dot');
  if (hasOverride && !existingDot) {
    var dot = document.createElement('span');
    dot.className = 'gc-override-dot';
    btn.appendChild(dot);
  } else if (!hasOverride && existingDot) {
    existingDot.remove();
  }
}

// ─── Convert to multi-repo / edit repo selection ───

async function gcOpenConvertPanel(mode) {
  var panel = document.getElementById('gcConvertPanel');
  if (!panel || !_gcCtx) return;

  panel.style.display = '';
  panel.innerHTML = '<div class="gc-checklist-loading">' + t('research.loading') + '</div>';

  var candidates;
  try {
    var scanResult = await apiGetRepoScan(_gcCtx.projectId);
    candidates = scanResult.candidates || [];
  } catch (e) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    showToast(t('messages.gcRepoScanFailed', {error: e.message}));
    return;
  }

  if (mode === 'convert' && candidates.length < 2) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    showToast(t('messages.gcNoSubReposFound'));
    return;
  }

  panel.innerHTML = _gcConvertChecklistHtml(candidates, mode);
}

function _gcConvertChecklistHtml(candidates, mode) {
  var registryByPath = {};
  (_gcRepos || []).forEach(function(r) { registryByPath[r.rel_path] = r; });

  var rows = [];
  var seen = {};
  candidates.forEach(function(c) {
    seen[c.rel_path] = true;
    var reg = registryByPath[c.rel_path];
    var checked = mode === 'edit' ? !!(reg && reg.enabled) : true;
    var baseBranch = reg ? reg.base_branch : c.current_branch;
    rows.push({ rel_path: c.rel_path, name: c.name, checked: checked, baseBranch: baseBranch || '' });
  });
  if (mode === 'edit') {
    (_gcRepos || []).forEach(function(r) {
      if (seen[r.rel_path]) return;
      rows.push({ rel_path: r.rel_path, name: r.name, checked: !!r.enabled, baseBranch: r.base_branch || '' });
    });
  }

  var rowsHtml = rows.map(function(row) {
    var checkedAttr = row.checked ? ' checked' : '';
    var relPathHtml = row.rel_path !== row.name
      ? '<span class="gc-checklist-relpath">' + escapeHtml(row.rel_path) + '</span>'
      : '';
    return '<div class="gc-checklist-row">' +
      '<label class="gc-checklist-check">' +
        '<input type="checkbox" data-rel-path="' + escapeAttr(row.rel_path) + '"' + checkedAttr + '>' +
        '<span class="gc-checklist-name">' + escapeHtml(row.name) + '</span>' +
        relPathHtml +
      '</label>' +
      '<input type="text" class="context-input gc-checklist-base-input" value="' + escapeAttr(row.baseBranch) + '" placeholder="' + t('gitCockpit.repos.baseBranchPlaceholder') + '">' +
    '</div>';
  }).join('');

  return '<div class="gc-checklist-title">' + t('gitCockpit.repos.checklistTitle') + '</div>' +
    '<div class="gc-checklist-rows">' + rowsHtml + '</div>' +
    '<div class="gc-checklist-actions">' +
      '<button class="btn btn-sm" onclick="gcCancelConvert()">' + t('gitCockpit.repos.cancelConvert') + '</button>' +
      '<button class="btn btn-sm btn-primary" onclick="gcConfirmConvert()">' + t('gitCockpit.repos.confirmConvert') + '</button>' +
    '</div>';
}

function gcCancelConvert() {
  var panel = document.getElementById('gcConvertPanel');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

async function gcConfirmConvert() {
  var panel = document.getElementById('gcConvertPanel');
  if (!panel || !_gcCtx) return;

  var repos = [];
  panel.querySelectorAll('.gc-checklist-row').forEach(function(rowEl) {
    var checkbox = rowEl.querySelector('input[type="checkbox"]');
    if (!checkbox || !checkbox.checked) return;
    var relPath = checkbox.getAttribute('data-rel-path');
    var baseInput = rowEl.querySelector('.gc-checklist-base-input');
    var baseBranch = (baseInput && baseInput.value.trim()) || 'develop';
    repos.push({ rel_path: relPath, base_branch: baseBranch });
  });

  if (repos.length === 0) {
    showToast(t('messages.gcSelectAtLeastOne'));
    return;
  }

  var confirmBtn = panel.querySelector('.gc-checklist-actions .btn-primary');
  if (confirmBtn) confirmBtn.disabled = true;

  try {
    var result = await apiConvertProjectMulti(_gcCtx.projectId, repos);
    _gcProjectType = result.project_type || 'multi';
    _gcRepos = result.repos || [];
    panel.style.display = 'none';
    panel.innerHTML = '';
    showToast(t('messages.gcConvertSuccess', {count: _gcRepos.length}));
    await _gcRenderRepositories();
    _gcRenderOverview();
    await _gcLoadAndRenderPrs();
  } catch (e) {
    showToast(t('messages.gcConvertFailed', {error: e.message}));
  } finally {
    if (confirmBtn) confirmBtn.disabled = false;
  }
}

// ─── Refresh on workspace state change ───

EventBus.on('state:refreshed', function() {
  if (!_gcCtx || !_gcSectionActive()) return;

  _gcRenderOverview();
  if (_gcProjectType === 'multi') {
    apiGetWorkspaceRepoState(_gcCtx.projectId, _gcCtx.branch).then(function(data) {
      _gcRepoState = data;
      _gcRenderMultiReposBody();
    }).catch(function() {});
  }
});
