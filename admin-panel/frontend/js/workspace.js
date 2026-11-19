let _wsCurrentView = 'project-list';
let _wsSelectedProjectId = null;
let _wsSelectedProjectName = null;
let _wsShowArchived = false;
let _wsFastModeDefaultPrior = false;
let _wsSelectedProjectType = 'single';

function showProjectSelector() {
  resetUrlToSelector();
  document.getElementById('project-selector').style.display = 'flex';
  document.getElementById('app-content').style.display = 'none';
  _wsSwitchView('project-list');
  loadProjects();
}

function hideProjectSelector() {
  document.getElementById('project-selector').style.display = 'none';
  document.getElementById('app-content').style.display = '';
}

function _wsSwitchView(view) {
  _wsCurrentView = view;
  const listView = document.getElementById('ws-project-list-view');
  const workspaceView = document.getElementById('ws-workspace-view');
  if (view === 'project-list') {
    listView.style.display = 'block';
    workspaceView.style.display = 'none';
  } else {
    listView.style.display = 'none';
    workspaceView.style.display = 'block';
  }
}

function _wsRenderCopyCommand(command) {
  const id = 'cmd-' + Math.random().toString(36).substring(2, 9);
  return `<div class="command-block">
    <code id="${id}">${_wsEscape(command)}</code>
    <button class="btn btn-sm" onclick="_wsCopyCommand('${id}', this)">${t('buttons.copy')}</button>
  </div>`;
}

function _wsCopyCommand(codeId, btn) {
  const text = document.getElementById(codeId).textContent;
  navigator.clipboard.writeText(text);
  const original = btn.textContent;
  btn.textContent = t('buttons.copied');
  setTimeout(() => { btn.textContent = original; }, 1500);
}

function _wsEscape(str) {
  return escapeHtml(String(str)).replace(/'/g, '&#39;');
}

function _wsToggleSessions(id, event) {
  event.stopPropagation();
  const el = document.getElementById(id);
  if (!el) return;
  const isHidden = el.style.display === 'none';
  el.style.display = isHidden ? 'block' : 'none';
}

function _wsClearError(containerId) {
  const container = document.getElementById(containerId);
  if (container) container.textContent = '';
}

function _wsShowError(containerId, message) {
  const container = document.getElementById(containerId);
  if (container) {
    container.textContent = message;
    container.style.color = 'var(--danger)';
    container.style.fontSize = '0.78rem';
    container.style.marginTop = '8px';
  }
}

async function loadProjects() {
  const listEl = document.getElementById('ws-project-cards');
  listEl.innerHTML = '<div class="empty sm">' + t('workspace.loadingProjects') + '</div>';
  _wsClearError('ws-project-list-error');

  try {
    const data = await apiListProjects();
    const projects = data.projects || [];
    if (projects.length === 0) {
      listEl.innerHTML = '<div class="empty sm">' + t('workspace.noProjectsRegistered') + '</div>';
      _wsRenderGateSummary([]);
      return;
    }
    listEl.innerHTML = projects.map(function(p) { return _wsProjectRowHtml(p, null); }).join('');
    _wsLoadProjectActivity(projects);
  } catch (err) {
    _wsShowError('ws-project-list-error', err.message);
  }
}

function _wsProjectRowHtml(project, activity) {
  const id = _wsEscape(project.id);
  const badge = activity ? _wsProjectBadgeHtml(project, activity) : _wsProjectTypeBadge(project);
  return '<div class="row ws-project-row">' +
    '<div class="grow"><div class="ti brk">' + _wsEscape(project.name) + '</div>' +
    '<div class="mono dim brk">' + _wsEscape(project.path) + '</div></div>' +
    badge +
    '<button class="btn pri" onclick="openProject(\'' + id + '\')">' + t('buttons.open') + '</button>' +
    '<div class="btn-dropdown">' +
      '<button class="btn ic" data-icon="more" aria-label="' + _wsEscape(t('workspace.projectActions')) + '" onclick="_wsToggleProjectMenu(this, event)"></button>' +
      '<div class="btn-dropdown-menu" style="display:none;">' +
        '<button class="btn-dropdown-item" onclick="_wsRemoveProject(\'' + id + '\')">' + t('buttons.remove') + '</button>' +
      '</div>' +
    '</div>' +
  '</div>';
}

function _wsProjectTypeBadge(project) {
  return project.project_type === 'multi' ? '<span class="pill line">' + t('workspace.multiRepo') + '</span>' : '';
}

function _wsProjectBadgeHtml(project, activity) {
  if (activity.gates.length) {
    return '<span class="pill gate"><span class="dot gate"></span>' + t('workspace.gatesBadge', {count: activity.gates.length}) + '</span>';
  }
  if (activity.running) {
    return '<span class="pill info">' + t('workspace.runningBadge', {count: activity.running}) + '</span>';
  }
  return _wsProjectTypeBadge(project);
}

function _wsToggleProjectMenu(button, event) {
  event.stopPropagation();
  const menu = button.nextElementSibling;
  const wasOpen = menu.style.display !== 'none';
  document.querySelectorAll('#ws-project-cards .btn-dropdown-menu').forEach(function(m) { m.style.display = 'none'; });
  menu.style.display = wasOpen ? 'none' : '';
}

document.addEventListener('click', function() {
  document.querySelectorAll('#ws-project-cards .btn-dropdown-menu').forEach(function(m) { m.style.display = 'none'; });
});

async function _wsFetchWorkspaceGates(projectId, workspaces) {
  const gates = {};
  const candidates = workspaces.filter(function(ws) {
    return ws.status !== 'archived' && _mayHoldGate(ws.phase);
  });
  await Promise.all(candidates.map(async function(ws) {
    try {
      const response = await apiGetState(projectId, ws.branch);
      gates[ws.branch] = describePendingGate(response.data);
    } catch (err) {
      gates[ws.branch] = null;
    }
  }));
  return gates;
}

async function _wsLoadProjectActivity(projects) {
  const activities = await Promise.all(projects.map(async function(project) {
    try {
      const data = await apiListWorkspaces(project.id);
      const workspaces = (data.workspaces || []).filter(function(ws) { return ws.status !== 'archived'; });
      const gateByBranch = await _wsFetchWorkspaceGates(project.id, workspaces);
      const gates = workspaces.filter(function(ws) { return gateByBranch[ws.branch]; })
        .map(function(ws) { return { project: project, ws: ws, gate: gateByBranch[ws.branch] }; });
      const running = workspaces.filter(function(ws) {
        return !gateByBranch[ws.branch] && ws.phase !== '0' && ws.phase !== '6' && (ws.sessions || []).length > 0;
      }).length;
      return { project: project, gates: gates, running: running };
    } catch (err) {
      return { project: project, gates: [], running: 0 };
    }
  }));
  const listEl = document.getElementById('ws-project-cards');
  if (!listEl || _wsCurrentView !== 'project-list') return;
  listEl.innerHTML = activities.map(function(a) { return _wsProjectRowHtml(a.project, a); }).join('');
  hydrateStaticIcons(listEl);
  _wsRenderGateSummary(activities);
}

function _wsRenderGateSummary(activities) {
  const el = document.getElementById('ws-gate-summary');
  if (!el) return;
  const gates = [].concat.apply([], activities.map(function(a) { return a.gates; }));
  if (!gates.length) {
    el.innerHTML = '';
    return;
  }
  gates.sort(function(x, y) { return _wsGateAge(y.gate) - _wsGateAge(x.gate); });
  const projectCount = activities.filter(function(a) { return a.gates.length; }).length;
  const detail = activities.filter(function(a) { return a.gates.length; }).map(function(a) {
    return a.project.name + ': ' + a.gates.map(function(g) { return t(g.gate.config.nameKey).toLowerCase(); }).join(', ');
  }).join(' · ');
  const oldest = gates[0];
  el.innerHTML = '<div class="gatecard">' +
    '<span class="gateico">' + cpGateIcon(22) + '</span>' +
    '<div class="grow"><div class="k">' + _wsEscape(t('workspace.gateSummary', {gates: gates.length, projects: projectCount})) + '</div>' +
    '<h2 class="ws-gate-title">' + _wsEscape(t('workspace.agentsWaiting')) + '</h2>' +
    '<div class="d brk">' + _wsEscape(detail) + '</div></div>' +
    '<button class="btn pri lg" onclick="openWorkspace(\'' + _wsEscape(oldest.project.id) + '\', \'' + _wsEscape(oldest.ws.branch) + '\')">' + t('workspace.reviewOldest') + '</button>' +
  '</div>';
}

function _wsGateAge(gate) {
  return gate.since ? Date.now() - gate.since.getTime() : 0;
}

async function _wsRemoveProject(projectId) {
  _wsClearError('ws-project-list-error');
  try {
    await apiDeleteProject(projectId);
    await loadProjects();
  } catch (err) {
    _wsShowError('ws-project-list-error', err.message);
  }
}

async function _wsRegisterProject() {
  const pathInput = document.getElementById('ws-register-path');
  const nameInput = document.getElementById('ws-register-name');
  const path = pathInput.value.trim();
  const name = nameInput.value.trim() || undefined;

  _wsClearError('ws-register-error');

  if (!path) {
    _wsShowError('ws-register-error', t('errors.directoryPathRequired'));
    return;
  }

  try {
    await apiRegisterProject(name, path);
    pathInput.value = '';
    nameInput.value = '';
    await loadProjects();
  } catch (err) {
    _wsShowError('ws-register-error', err.message);
  }
}

function _wsRenderWorkspaceCards(projectId, workspaces, gateByBranch) {
  var gates = gateByBranch || {};
  var archived = workspaces.filter(function(ws) { return ws.status === 'archived'; });
  var visible = _wsShowArchived ? workspaces : workspaces.filter(function(ws) { return ws.status !== 'archived'; });

  if (visible.length === 0) {
    var msg = workspaces.length > 0
      ? t('workspace.allArchived') + ' <a href="#" onclick="_wsToggleArchived(event)">' + t('workspace.showArchived', {count: archived.length}) + '</a>'
      : t('workspace.noWorkspacesYet');
    return '<div class="empty sm">' + msg + '</div>';
  }

  var toggleHtml = '';
  if (archived.length > 0) {
    var label = _wsShowArchived ? t('workspace.hideArchived', {count: archived.length}) : t('workspace.showArchived', {count: archived.length});
    toggleHtml = '<div class="ws-archived-toggle"><a href="#" onclick="_wsToggleArchived(event)">' + label + '</a></div>';
  }

  var needs = visible.filter(function(ws) { return gates[ws.branch]; });
  needs.sort(function(a, b) { return _wsGateAge(gates[b.branch]) - _wsGateAge(gates[a.branch]); });
  var others = visible.filter(function(ws) { return !gates[ws.branch]; });

  return toggleHtml +
    _wsWorkspaceGroupHtml(projectId, needs, gates, needs.length && others.length ? t('shell.needsYou') : '') +
    _wsWorkspaceGroupHtml(projectId, others, gates, needs.length && others.length ? t('workspace.otherWorkspaces') : '');
}

function _wsWorkspaceGroupHtml(projectId, group, gates, caption) {
  if (!group.length) return '';
  var head = caption ? '<div class="cap ws-group-cap">' + _wsEscape(caption) + '</div>' : '';
  return head + group.map(function(ws) { return _wsWorkspaceRowHtml(projectId, ws, gates[ws.branch]); }).join('');
}

function _wsWorkspaceStatusHtml(ws, gate) {
  if (ws.status === 'archived') return '<span class="pill">' + t('badges.archived') + '</span>';
  if (gate) {
    var wait = formatWaitDuration(gate.since);
    return '<span class="pill gate"><span class="dot gate"></span>' + _wsEscape(t(gate.config.nameKey) + (wait ? ' · ' + wait : '')) + '</span>';
  }
  if (ws.phase === '6') return '<span class="pill ok">' + t('shell.done') + '</span>';
  if (ws.phase === '0') return '<span class="pill">' + t('workspace.notStarted') + '</span>';
  return '<span class="pill info">' + t('shell.agentWorking') + '</span>';
}

function _wsWorkspaceRowHtml(projectId, ws, gate) {
  var isArchived = ws.status === 'archived';
  var branchLabel = _wsEscape(ws.branch);
  if (isArchived && ws.created) {
    var d = new Date(ws.created);
    var dateStr = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    branchLabel += ' <span class="dim sm">(' + dateStr + ')</span>';
  }
  var pid = _wsEscape(projectId);
  var branch = _wsEscape(ws.branch);
  var actions = isArchived ? '' :
    '<button class="btn pri" onclick="openWorkspace(\'' + pid + '\', \'' + branch + '\')">' + t('buttons.open') + '</button>' +
    '<button class="btn danger" onclick="_wsArchiveWorkspace(\'' + pid + '\', \'' + branch + '\', event)">' + t('buttons.archive') + '</button>';
  return '<div class="row ws-workspace-row' + (isArchived ? ' is-archived' : '') + '">' +
    '<div class="grow mono brk ws-branch">' + branchLabel + '</div>' +
    _wsWorkspaceStatusHtml(ws, gate) +
    (ws.phase != null ? '<span class="tag">' + t('badges.phase', {phase: ws.phase}) + '</span>' : '') +
    (ws.workflow_mode === 'fast' ? '<span class="pill warn">' + t('badges.fastMode') + '</span>' : '') +
    (!isArchived && (ws.sessions || []).length > 0 ? '<span class="pill line">' + t('badges.sessionActive') + '</span>' : '') +
    actions +
  '</div>';
}

function _wsToggleArchived(event) {
  event.preventDefault();
  _wsShowArchived = !_wsShowArchived;
  if (_wsSelectedProjectId) openProject(_wsSelectedProjectId);
}

async function openProject(projectId) {
  _wsSelectedProjectId = projectId;
  _wsSwitchView('workspace');

  const headerEl = document.getElementById('ws-workspace-project-name');
  const pathEl = document.getElementById('ws-workspace-project-path');
  headerEl.textContent = t('research.loading');
  pathEl.textContent = '';

  const workspaceListEl = document.getElementById('ws-workspace-cards');
  workspaceListEl.innerHTML = '<div class="empty sm">' + t('workspace.loadingWorkspaces') + '</div>';
  _wsClearError('ws-workspace-error');

  try {
    const data = await apiListProjects();
    const projects = data.projects || [];
    const project = projects.find(p => p.id === projectId);
    _wsSelectedProjectName = project ? project.name : projectId;
    headerEl.textContent = _wsSelectedProjectName;
    pathEl.textContent = project ? project.path : '';
    await _wsApplyProjectTypeToCreateForm(project);
  } catch (err) {
    headerEl.textContent = projectId;
    await _wsApplyProjectTypeToCreateForm(null);
  }

  try {
    const wsData = await apiListWorkspaces(projectId);
    const workspaces = wsData.workspaces || [];
    const gates = await _wsFetchWorkspaceGates(projectId, workspaces);
    workspaceListEl.innerHTML = _wsRenderWorkspaceCards(projectId, workspaces, gates);
  } catch (err) {
    _wsShowError('ws-workspace-error', err.message);
  }

  await loadBranches(projectId);
  _wsLoadProjectDefaults(projectId);
}

async function loadBranches(projectId) {
  const selectEl = document.getElementById('ws-source-branch');
  selectEl.innerHTML = '<option value="">' + t('workspace.loadingBranches') + '</option>';

  try {
    const brData = await apiListBranches(projectId);
    const branches = [...new Set([...(brData.local || []), ...(brData.remote || [])])];
    if (branches.length === 0) {
      selectEl.innerHTML = '<option value="">' + t('workspace.noBranchesFound') + '</option>';
      return;
    }

    const developExists = branches.includes('develop');
    const defaultBranch = developExists ? 'develop' : branches[0];

    selectEl.innerHTML = branches.map(b =>
      `<option value="${_wsEscape(b)}" ${b === defaultBranch ? 'selected' : ''}>${_wsEscape(b)}</option>`
    ).join('');
  } catch (err) {
    selectEl.innerHTML = '<option value="">' + t('workspace.failedToLoadBranches') + '</option>';
  }
}

async function _wsApplyProjectTypeToCreateForm(project) {
  _wsSelectedProjectType = (project && project.project_type) || 'single';

  const worktreeCheckbox = document.getElementById('ws-worktree');
  const forcedNote = document.getElementById('wsWorktreeForcedNote');
  const attachRow = document.getElementById('wsRepoAttachRow');
  const attachList = document.getElementById('wsRepoAttachList');

  if (_wsSelectedProjectType !== 'multi') {
    if (worktreeCheckbox) worktreeCheckbox.disabled = false;
    if (forcedNote) forcedNote.style.display = 'none';
    if (attachRow) attachRow.style.display = 'none';
    if (attachList) attachList.innerHTML = '';
    return;
  }

  if (worktreeCheckbox) { worktreeCheckbox.checked = true; worktreeCheckbox.disabled = true; }
  if (forcedNote) forcedNote.style.display = '';
  if (attachRow) attachRow.style.display = '';
  if (attachList) attachList.innerHTML = '<div class="gc-empty-state">' + t('research.loading') + '</div>';

  try {
    const data = await apiGetProjectRepos(project.id);
    const repos = (data.repos || []).filter(function(r) { return r.enabled; });
    if (!attachList) return;
    attachList.innerHTML = repos.length
      ? repos.map(function(r) {
          const relPathHtml = r.rel_path !== r.name
            ? ' <span class="gc-checklist-relpath">' + _wsEscape(r.rel_path) + '</span>'
            : '';
          return '<label class="ws-checkbox-label">' +
            '<input type="checkbox" class="ws-repo-attach-check" value="' + r.id + '">' +
            _wsEscape(r.name) + relPathHtml +
          '</label>';
        }).join('')
      : '<div class="gc-empty-state">' + t('gitCockpit.create.noReposEnabled') + '</div>';
  } catch (err) {
    if (attachRow) attachRow.style.display = 'none';
    if (attachList) attachList.innerHTML = '';
  }
}

async function createWorkspace(projectId) {
  const branchInput = document.getElementById('ws-new-branch');
  const sourceSelect = document.getElementById('ws-source-branch');
  const worktreeCheckbox = document.getElementById('ws-worktree');
  const fastModeCheckbox = document.getElementById('ws-fast-mode');
  const resultEl = document.getElementById('ws-create-result');

  const branch = branchInput.value.trim();
  const source = sourceSelect.value;
  const worktree = worktreeCheckbox.checked;
  const workflowMode = fastModeCheckbox && fastModeCheckbox.checked ? 'fast' : 'standard';
  const repos = Array.from(document.querySelectorAll('.ws-repo-attach-check:checked')).map(function(el) {
    return parseInt(el.value, 10);
  });

  _wsClearError('ws-create-error');
  resultEl.innerHTML = '';

  if (!branch) {
    _wsShowError('ws-create-error', t('errors.branchNameRequired'));
    return;
  }

  let result;
  try {
    result = await apiCreateWorkspace(projectId, branch, source, worktree, workflowMode, repos);
  } catch (err) {
    resultEl.innerHTML = '';
    _wsShowError('ws-create-error', err.message);
    return;
  }

  if (!result || !result.workspace) {
    resultEl.innerHTML = '';
    _wsShowError('ws-create-error', t('errors.workspaceCreationFailed'));
    return;
  }

  let resultHtml = '<div class="ws-create-result-card">';
  if (result.working_dir) {
    resultHtml += `<div class="ws-result-row">
      <span class="ws-result-label">${t('labels.workingDirectory')}</span>
      <span class="ws-result-value">${_wsEscape(result.working_dir)}</span>
    </div>`;
  }
  resultHtml += `<button class="btn btn-primary" style="margin-top: 12px; width: 100%; justify-content: center;" onclick="openWorkspace('${_wsEscape(projectId)}', '${_wsEscape(branch)}')">${t('buttons.openWorkspace')}</button>`;
  resultHtml += '</div>';

  resultEl.innerHTML = resultHtml;
  branchInput.value = '';

  _wsNotifyBaseSync(result.base_sync, source);
  _wsNotifyAttachedRepos(result.attached_repos);

  try {
    const workspaceListEl = document.getElementById('ws-workspace-cards');
    const wsData2 = await apiListWorkspaces(projectId);
    const workspaces = wsData2.workspaces || [];
    const gates = await _wsFetchWorkspaceGates(projectId, workspaces);
    workspaceListEl.innerHTML = _wsRenderWorkspaceCards(projectId, workspaces, gates);
  } catch (err) {
    _wsShowError('ws-workspace-error', err.message);
  }
}

function _wsNotifyBaseSync(baseSync, baseBranch) {
  if (!baseSync) return;

  const branchLabel = baseSync.branch || baseBranch;

  if (baseSync.updated) {
    showToast(t('messages.baseSyncUpdated', {branch: branchLabel}));
    return;
  }

  const trivialReasons = ['no-local-branch', 'not-remote-based'];
  if (trivialReasons.indexOf(baseSync.reason) !== -1) return;

  showToast(t('messages.baseSyncNotUpdated', {branch: branchLabel, reason: baseSync.reason}));
}

// Notifies base-sync results for each repo attached at workspace-creation time
// (multi-repo projects). Mirrors _wsNotifyBaseSync's single-repo semantics,
// one toast per repo (later toasts replace earlier ones per showToast's
// single-instance behavior, so only the last notable result is visible).
function _wsNotifyAttachedRepos(attachedRepos) {
  if (!attachedRepos || !attachedRepos.length) return;
  attachedRepos.forEach(function(item) {
    _wsNotifyBaseSync(item.base_sync, item.rel_path);
  });
}

async function _wsArchiveWorkspace(projectId, branch, event) {
  event.stopPropagation();
  if (!confirm(t('dialog.archiveWorkspace', {branch: branch}))) return;
  _wsClearError('ws-workspace-error');
  try {
    await apiArchiveWorkspace(projectId, branch);
    await openProject(projectId);
  } catch (err) {
    _wsShowError('ws-workspace-error', err.message);
  }
}

function openWorkspace(projectId, branch) {
  setWorkspaceContext(projectId, branch);
  hideProjectSelector();
  if (typeof applyStoredTabForContext === 'function') {
    var tabId = applyStoredTabForContext(getWorkspaceContext());
    if (typeof _activateTabHooks === 'function') _activateTabHooks(tabId);
  }
  if (typeof initApp === 'function') {
    initApp();
  }
}

function _wsInitSelector() {
  const selector = document.getElementById('project-selector');
  if (!selector) return;

  selector.innerHTML = `
    <div class="ws-selector-container">
      <div class="ws-brand">
        <img src="/img/logo.png" alt="" width="40" height="40">
        <h1 class="ws-selector-title">${t('shell.brand')}</h1>
      </div>

      <div id="ws-project-list-view">
        <div id="ws-gate-summary"></div>

        <section class="card">
          <div class="ch">
            <h3 class="grow">${t('workspace.registeredProjects')}</h3>
            <button class="btn" data-icon="setup" onclick="showSetupPage()">${t('setup.openSetupBtn')}</button>
          </div>
          <div class="cb flush" id="ws-project-cards"></div>
          <div id="ws-project-list-error"></div>
        </section>

        <section class="card">
          <div class="ch"><h3>${t('workspace.registerNewProject')}</h3></div>
          <div class="cb">
            <label class="lbl">${t('workspace.projectRoot')}
              <input type="text" id="ws-register-path" class="inp mono" placeholder="${t('placeholders.projectPath')}">
            </label>
            <label class="lbl">${t('workspace.projectNameOptional')}
              <input type="text" id="ws-register-name" class="inp" placeholder="${t('placeholders.projectName')}">
            </label>
            <div><button class="btn pri" data-icon="plus" onclick="_wsRegisterProject()">${t('buttons.register')}</button></div>
            <div id="ws-register-error"></div>
          </div>
        </section>
      </div>

      <div id="ws-workspace-view" style="display: none;">
        <div class="ws-titlebar">
          <button class="btn" data-icon="back" onclick="_wsBackToProjects()">${t('shell.projects')}</button>
          <h2 id="ws-workspace-project-name"></h2>
          <span class="grow"></span>
          <span class="mono dim brk" id="ws-workspace-project-path"></span>
        </div>

        <section class="card">
          <div class="ch"><h3 class="grow">${t('workspace.workspacesTitle')}</h3></div>
          <div class="cb flush" id="ws-workspace-cards"></div>
          <div id="ws-workspace-error"></div>
        </section>

        <section class="card">
          <div class="ch"><h3>${t('workspace.createNewWorkspace')}</h3></div>
          <div class="cb">
            <label class="lbl">${t('workspace.branchLabel')}
              <input type="text" id="ws-new-branch" class="inp mono" placeholder="${t('placeholders.featureBranch')}" required>
            </label>
            <label class="lbl">${t('labels.sourceBranch')}
              <select id="ws-source-branch" class="sel"><option value="">${t('research.loading')}</option></select>
            </label>
            <label class="ws-checkbox-label">
              <input type="checkbox" id="ws-worktree" checked>
              ${t('labels.createAsGitWorktree')}
            </label>
            <div id="wsWorktreeForcedNote" style="display:none;">
              <span class="gc-hint-text">${t('gitCockpit.create.worktreeForced')}</span>
            </div>
            <label class="ws-checkbox-label">
              <input type="checkbox" id="ws-fast-mode">
              ${t('labels.fastMode')}
            </label>
            <div class="vs" id="wsRepoAttachRow" style="display:none;">
              <span class="cap">${t('gitCockpit.create.attachRepos')}</span>
              <div id="wsRepoAttachList" class="gc-checklist-rows gc-checklist-rows--compact"></div>
            </div>
            <div><button class="btn pri" data-icon="plus" onclick="createWorkspace(_wsSelectedProjectId)">${t('buttons.createWorkspace')}</button></div>
            <div id="ws-create-error"></div>
            <div id="ws-create-result"></div>
          </div>
        </section>
      </div>
    </div>
  `;
  hydrateStaticIcons(selector);

  if (!document.getElementById('selector-toolbar')) {
    var toolbar = document.createElement('div');
    toolbar.id = 'selector-toolbar';
    toolbar.style.cssText = 'position: absolute; top: 16px; right: 16px; display: flex; gap: 8px; align-items: center; z-index: 10;';
    toolbar.innerHTML = '<select class="btn locale-select" id="selectorLocaleSelect" onchange="onSelectorLocaleChange(this.value)"><option value="en">EN</option><option value="ru">RU</option></select>'
      + '<button class="btn ic" onclick="toggleTheme()" title="' + escapeHtml(t('shell.switchTheme')) + '" aria-label="' + escapeHtml(t('shell.switchTheme')) + '" id="selectorThemeBtn"></button>';
    selector.appendChild(toolbar);
  }

  var localeSelect = document.getElementById('selectorLocaleSelect');
  if (localeSelect && typeof I18N_LOCALE !== 'undefined') {
    localeSelect.value = I18N_LOCALE;
  }
  if (typeof _updateThemeButtons === 'function' && typeof state !== 'undefined') {
    _updateThemeButtons(state.theme);
  }
}

function onSelectorLocaleChange(value) {
  localStorage.setItem('admin-panel-locale', value);
  I18N_LOCALE = value;
  loadI18n(value).then(function() {
    _wsInitSelector();
    loadProjects();
    var workspaceLocaleSelect = document.getElementById('localeSelect');
    if (workspaceLocaleSelect) workspaceLocaleSelect.value = value;
  });
}

function _wsBackToProjects() {
  _wsSelectedProjectId = null;
  _wsSelectedProjectName = null;
  _wsSwitchView('project-list');
  loadProjects();
}

async function _wsLoadProjectDefaults(projectId) {
  var createFastModeCheckbox = document.getElementById('ws-fast-mode');
  if (!createFastModeCheckbox) return;
  try {
    var data = await apiGet('/api/projects/' + encodeURIComponent(projectId) + '/settings');
    _wsFastModeDefaultPrior = !!data.fast_mode_default;
    createFastModeCheckbox.checked = _wsFastModeDefaultPrior;
  } catch (err) {
    createFastModeCheckbox.checked = false;
  }
}

(function () {
  const ctx = getWorkspaceContext();
  const savedLocale = localStorage.getItem('admin-panel-locale') || 'en';

  function _wsBoot() {
    _wsInitSelector();
    if (ctx) {
      hideProjectSelector();
      if (typeof initApp === 'function') {
        initApp();
      }
    } else {
      showProjectSelector();
      loadProjects();
    }
  }

  if (typeof loadI18n === 'function') {
    loadI18n(savedLocale).then(_wsBoot);
  } else {
    _wsBoot();
  }
})();
