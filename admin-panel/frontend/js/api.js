// ═══════════════════════════════════════════════
//  API CLIENT
// ═══════════════════════════════════════════════

const API_BASE = '';  // Same origin
const AUTH_TOKEN_KEY = 'admin-panel-auth-token';

// ─── Auth token helpers ───

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || '';
}

function setAuthToken(token) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function clearAuthToken() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

function _authHeaders(base) {
  const headers = base ? Object.assign({}, base) : {};
  const token = getAuthToken();
  if (token) headers['Authorization'] = 'Bearer ' + token;
  return headers;
}

async function _handleAuthFailure() {
  clearAuthToken();
  if (typeof EventBus !== 'undefined' && EventBus && typeof EventBus.emit === 'function') {
    EventBus.emit('auth:required');
  }
}

function _appendTokenToWsUrl(url) {
  const token = getAuthToken();
  if (!token) return url;
  const sep = url.includes('?') ? '&' : '?';
  return url + sep + 'token=' + encodeURIComponent(token);
}

// ─── Workspace context and routes ───

// The workspace the app has loaded. The URL only mirrors it: other views
// (Setup, the project selector) rewrite the query string while the workspace
// stays loaded behind them, so readers must never re-derive it from location.
let _loadedWorkspace = readWorkspaceFromUrl();
let _isRestoringRoute = false;

function readWorkspaceFromUrl() {
  const ws = new URLSearchParams(window.location.search).get('ws');
  const slashIdx = ws ? ws.indexOf('/') : -1;
  if (slashIdx <= 0) return null;
  return {
    projectId: ws.substring(0, slashIdx),
    branch: ws.substring(slashIdx + 1)
  };
}

function isSetupRoute() {
  return new URLSearchParams(window.location.search).get('view') === 'setup';
}

function getWorkspaceContext() {
  if (!_loadedWorkspace) return null;
  return { projectId: _loadedWorkspace.projectId, branch: _loadedWorkspace.branch };
}

function isLoadedWorkspace(ctx) {
  return !!(ctx && _loadedWorkspace &&
    ctx.projectId === _loadedWorkspace.projectId && ctx.branch === _loadedWorkspace.branch);
}

function workspaceRoute(ctx) {
  return '/?' + new URLSearchParams({ ws: ctx.projectId + '/' + ctx.branch });
}

function setWorkspaceContext(projectId, branch) {
  _loadedWorkspace = { projectId: projectId, branch: branch };
  pushRoute(workspaceRoute(_loadedWorkspace));
}

// Leaves the workspace for the project selector. The bare "/" keeps a
// refresh on the selector from redirecting back into the workspace.
function clearWorkspaceContext() {
  _loadedWorkspace = null;
  pushRoute('/');
}

// Records a navigation in browser history, except while a Back/Forward step
// is being replayed: that entry already exists and must not be duplicated.
function pushRoute(url) {
  if (_isRestoringRoute) return;
  window.history.pushState(null, '', url);
}

function restoreRoute(render) {
  _isRestoringRoute = true;
  try {
    render();
  } finally {
    _isRestoringRoute = false;
  }
}

// ─── Generic fetch helpers ───

function _buildApiErrorMessage(err, fallback) {
  const main = err.error || err.details || fallback;
  if (err.error && err.details && err.details !== err.error) {
    return main + ' — ' + err.details;
  }
  return main;
}

function _apiError(res, payload) {
  const message = payload && typeof payload === 'object'
    ? _buildApiErrorMessage(payload, res.statusText)
    : res.statusText;
  const err = new Error(message);
  err.status = res.status;
  err.payload = payload;
  return err;
}

async function _checkAndParseResponse(res) {
  if (res.status === 401) {
    await _handleAuthFailure();
    const err = new Error('Unauthorized');
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ error: res.statusText }));
    throw _apiError(res, payload);
  }
  return res.json();
}

async function apiGet(path) {
  const res = await fetch(API_BASE + path, { headers: _authHeaders() });
  return _checkAndParseResponse(res);
}

// GET with ETag revalidation. Returns { notModified: true, etag } when the
// server responds with 304, otherwise { data, etag, notModified: false }.
async function apiGetWithEtag(path, lastEtag) {
  const headers = {};
  if (lastEtag) headers['If-None-Match'] = lastEtag;
  const res = await fetch(API_BASE + path, { headers: _authHeaders(headers) });

  if (res.status === 304) {
    return { notModified: true, etag: res.headers.get('ETag') || lastEtag || null, data: null };
  }
  const data = await _checkAndParseResponse(res);
  return { notModified: false, etag: res.headers.get('ETag') || null, data };
}

async function apiPost(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: _authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body)
  });
  return _checkAndParseResponse(res);
}

async function apiPut(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'PUT',
    headers: _authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body)
  });
  return _checkAndParseResponse(res);
}

async function apiPatch(path, body) {
  const res = await fetch(API_BASE + path, {
    method: 'PATCH',
    headers: _authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body)
  });
  return _checkAndParseResponse(res);
}

async function apiDelete(path) {
  const res = await fetch(API_BASE + path, { method: 'DELETE', headers: _authHeaders() });
  return _checkAndParseResponse(res);
}

// ─── Project endpoints ───

function apiListProjects() {
  return apiGet('/api/projects');
}

function apiRegisterProject(name, path) {
  return apiPost('/api/projects', { name, path });
}

function apiDeleteProject(id) {
  return apiDelete('/api/projects/' + encodeURIComponent(id));
}

// ─── Branch & workspace endpoints ───

function apiListBranches(projectId) {
  return apiGet('/api/projects/' + encodeURIComponent(projectId) + '/branches');
}

function apiListWorkspaces(projectId) {
  return apiGet('/api/projects/' + encodeURIComponent(projectId) + '/workspaces');
}

function apiCreateWorkspace(projectId, branch, source, worktree, workflowMode, repos) {
  var body = { branch, source, worktree, workflow_mode: workflowMode };
  if (repos && repos.length) body.repos = repos;
  return apiPost('/api/projects/' + encodeURIComponent(projectId) + '/workspaces', body);
}

function apiArchiveWorkspace(projectId, branch) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/archive');
}

// ─── Multi-repo (git cockpit) endpoints ───

function apiGetRepoScan(projectId) {
  return apiGet('/api/projects/' + encodeURIComponent(projectId) + '/repo-scan');
}

function apiConvertProjectMulti(projectId, repos) {
  return apiPost('/api/projects/' + encodeURIComponent(projectId) + '/convert-multi', { repos: repos });
}

function apiGetProjectRepos(projectId) {
  return apiGet('/api/projects/' + encodeURIComponent(projectId) + '/repos');
}

function apiGetProjectRepo(projectId, repoId) {
  return apiGet('/api/projects/' + encodeURIComponent(projectId) + '/repos/' + encodeURIComponent(repoId));
}

function apiUpdateProjectRepo(projectId, repoId, patch) {
  return apiPut('/api/projects/' + encodeURIComponent(projectId) + '/repos/' + encodeURIComponent(repoId), patch);
}

function apiGetWorkspaceRepoState(projectId, branch) {
  return apiGet('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/repo-state');
}

function apiAttachWorkspaceRepo(projectId, branch, repoId) {
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/repos/attach', { repo_id: repoId });
}

function apiListWorkspacePrs(projectId, branch) {
  return apiGet('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/prs');
}

function apiAddWorkspacePr(projectId, branch, body) {
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/prs', body);
}

function apiDeleteWorkspacePr(projectId, branch, prId) {
  return apiDelete('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/prs/' + encodeURIComponent(prId));
}

// ─── Workspace state endpoints ───

function apiGetState(projectId, branch, lastEtag) {
  return apiGetWithEtag(
    '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/state',
    lastEtag
  );
}

function apiSetScope(projectId, branch, scope) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/scope', { scope });
}

function apiSetPhase(projectId, branch, phase) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/phase', { phase: phase });
}

function apiSetWorkflowMode(projectId, branch, mode) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/workflow-mode', { mode: mode });
}

function apiSetReviewMode(projectId, branch, mode) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/review-mode', { mode: mode });
}

function apiAddComment(projectId, branch, scope, target, text, filePath, lineStart, lineEnd, lHash) {
  var body = { scope: scope, target: target, text: text };
  if (filePath) body.file_path = filePath;
  if (lineStart != null) body.line_start = lineStart;
  if (lineEnd != null) body.line_end = lineEnd;
  if (lHash) body.line_hash = lHash;
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/comments', body);
}

function apiResolveComment(projectId, branch, commentId, resolved) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/comments/' + commentId + '/resolve', { resolved: resolved });
}

function apiResolveAllReviewIssues(workspaceId, resolution) {
  return apiPost(
    '/api/workspaces/' + encodeURIComponent(workspaceId) + '/review-issues/resolve-all',
    { resolution: resolution }
  );
}

function apiStartReviewPipeline(workspaceId, options) {
  var body = {};
  if (options && options.force) body.force = true;
  if (options && options.baseBranch) body.base_branch = options.baseBranch;
  return apiPost(
    '/api/workspaces/' + encodeURIComponent(workspaceId) + '/review-pipeline/start',
    body
  );
}

function apiListComments(projectId, branch, scope, showResolved) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/comments';
  var params = [];
  if (scope) params.push('scope=' + encodeURIComponent(scope));
  if (showResolved) params.push('resolved=true');
  if (params.length) url += '?' + params.join('&');
  return apiGet(url);
}

function apiListProposals(projectId, branch) {
  return apiGet('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/proposals');
}

function apiResolveProposal(projectId, branch, proposalId, status, resultJson) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/proposals/' + proposalId + '/resolve', { status: status, result_json: resultJson || null });
}

function apiSavePlan(projectId, branch, planData) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/plan', planData);
}

function apiAdvance(projectId, branch, body) {
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/advance', body || {});
}

function apiApprove(projectId, branch, commitMessage) {
  var body = {};
  if (commitMessage) body.commit_message = commitMessage;
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/approve', body);
}

function apiReject(projectId, branch, comments) {
  return apiPost('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/reject', { comments: comments });
}

// ─── Auth endpoints ───

async function apiAuthStatus() {
  const res = await fetch(API_BASE + '/api/auth/status', { cache: 'no-store' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.details || res.statusText);
  }
  return res.json();
}

async function apiAuthCheck(token) {
  const res = await fetch(API_BASE + '/api/auth/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: token })
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ error: res.statusText }));
    const err = new Error(payload.error || payload.details || res.statusText);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// ─── Network mode + restart ───

function apiGetNetworkMode() {
  return apiGet('/api/network-mode');
}

function apiSetNetworkMode(enabled) {
  return apiPut('/api/network-mode', { enabled: !!enabled });
}

function apiRestartBackend() {
  return apiPost('/api/restart', {});
}

// ─── File & diff endpoints ───

function apiReadFile(projectId, branch, filePath, startLine, endLine, absolute) {
  let url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/file?path=' + encodeURIComponent(filePath);
  if (startLine != null) url += '&start=' + startLine;
  if (endLine != null) url += '&end=' + endLine;
  if (absolute) url += '&absolute=true';
  return apiGet(url);
}

function apiWriteFile(projectId, branch, filePath, content) {
  return apiPut('/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/file', { path: filePath, content: content });
}

function apiGetDiff(projectId, branch, mode, commit, repo, base) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/diff';
  var q = [];
  if (mode && mode !== 'branch') q.push('mode=' + encodeURIComponent(mode));
  if (commit) q.push('commit=' + encodeURIComponent(commit));
  if (repo && repo !== '.') q.push('repo=' + encodeURIComponent(repo));
  if (base && (!mode || mode === 'branch')) q.push('base=' + encodeURIComponent(base));
  if (q.length) url += '?' + q.join('&');
  return apiGet(url);
}

function _annotationsUrl(projectId, branch, suffix) {
  return '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/annotations' + (suffix || '');
}

function apiGetAnnotations(projectId, branch, filePath, repo, ref) {
  var q = ['file=' + encodeURIComponent(filePath), 'repo=' + encodeURIComponent(repo || ''), 'ref=' + encodeURIComponent(ref || '')];
  return apiGet(_annotationsUrl(projectId, branch) + '?' + q.join('&'));
}

function apiUpdateAnnotation(projectId, branch, annotationId, patch) {
  return apiPatch(_annotationsUrl(projectId, branch, '/' + encodeURIComponent(annotationId)), patch);
}

function apiDeleteAnnotation(projectId, branch, annotationId) {
  return apiDelete(_annotationsUrl(projectId, branch, '/' + encodeURIComponent(annotationId)));
}

function apiGetCommitHistory(projectId, branch, ref, repo) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/history';
  var q = [];
  if (ref) q.push('ref=' + encodeURIComponent(ref));
  if (repo && repo !== '.') q.push('repo=' + encodeURIComponent(repo));
  if (q.length) url += '?' + q.join('&');
  return apiGet(url);
}

function apiGetBranches(projectId, branch, repo) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/branches';
  if (repo && repo !== '.') url += '?repo=' + encodeURIComponent(repo);
  return apiGet(url);
}

function apiGetRepos(projectId, branch) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/repos';
  return apiGet(url);
}

function _scratchpadsUrl(projectId, branch, suffix, repo, extraParams) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/scratchpads' + suffix;
  var params = [];
  if (repo && repo !== '.') params.push('repo=' + encodeURIComponent(repo));
  if (extraParams) params = params.concat(extraParams);
  if (params.length) url += '?' + params.join('&');
  return url;
}

function apiGetScratchpads(projectId, branch, repo) {
  return apiGet(_scratchpadsUrl(projectId, branch, '', repo));
}

function apiGetScratchpadContent(projectId, branch, name, repo) {
  return apiGet(_scratchpadsUrl(projectId, branch, '/content', repo, ['name=' + encodeURIComponent(name)]));
}

function apiSaveScratchpadContent(projectId, branch, name, content, repo) {
  return apiPut(_scratchpadsUrl(projectId, branch, '/content', repo, ['name=' + encodeURIComponent(name)]), { content: content });
}

function apiHistoryRename(projectId, branch, sha, message) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/history/rename';
  return apiPost(url, { sha: sha, message: message });
}

function apiHistoryUndo(projectId, branch) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/history/undo';
  return apiPost(url, {});
}

function apiHistorySquash(projectId, branch, commits, message) {
  var url = '/api/ws/' + encodeURIComponent(projectId) + '/' + encodeURIComponent(branch) + '/history/squash';
  return apiPost(url, { commits: commits, message: message });
}
