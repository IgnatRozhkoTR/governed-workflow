// ═══════════════════════════════════════════════
//  GENERIC FILTERABLE COMBOBOX (typable <select> replacement)
// ═══════════════════════════════════════════════
var _filterSelects = {};

function initFilterSelect(hostId, onChange) {
  var host = document.getElementById(hostId);
  if (!host) return;
  var input = host.querySelector('.filter-select-input');
  var menu = host.querySelector('.filter-select-menu');
  if (!input || !menu) return;

  var widget = {
    host: host,
    input: input,
    menu: menu,
    options: [],
    filtered: [],
    value: null,
    onChange: onChange,
    highlightIndex: -1,
    open: false
  };
  _filterSelects[hostId] = widget;

  input.addEventListener('focus', function() { _openFilterSelect(hostId); });
  input.addEventListener('click', function() { _openFilterSelect(hostId); });
  input.addEventListener('input', function() { _filterFilterSelectOptions(hostId, input.value); });
  input.addEventListener('keydown', function(e) { _handleFilterSelectKeydown(hostId, e); });
  input.addEventListener('blur', function() { _closeFilterSelect(hostId, true); });

  menu.addEventListener('mousedown', function(e) { e.preventDefault(); });
  menu.addEventListener('click', function(e) {
    var row = e.target.closest('.filter-select-option');
    if (row && !row.classList.contains('no-matches')) {
      _commitFilterSelect(hostId, row.dataset.value);
    }
  });
}

function _filterSelectLabelFor(widget, value) {
  var match = widget.options.find(function(o) { return o.value === value; });
  return match ? match.label : '';
}

function _openFilterSelect(hostId) {
  var widget = _filterSelects[hostId];
  if (!widget || widget.open) return;
  widget.open = true;
  widget.host.classList.add('open');
  widget.input.select();
  _filterFilterSelectOptions(hostId, '');
  widget.menu.hidden = false;
}

function _closeFilterSelect(hostId, revert) {
  var widget = _filterSelects[hostId];
  if (!widget || !widget.open) return;
  widget.open = false;
  widget.host.classList.remove('open');
  widget.menu.hidden = true;
  widget.menu.innerHTML = '';
  if (revert) {
    widget.input.value = _filterSelectLabelFor(widget, widget.value);
  }
}

function _filterFilterSelectOptions(hostId, query) {
  var widget = _filterSelects[hostId];
  if (!widget) return;
  var normalizedQuery = (query || '').toLowerCase();
  widget.filtered = normalizedQuery
    ? widget.options.filter(function(o) { return o.label.toLowerCase().indexOf(normalizedQuery) !== -1; })
    : widget.options.slice();
  widget.highlightIndex = widget.filtered.length ? 0 : -1;
  _renderFilterSelectMenu(hostId);
}

function _renderFilterSelectMenu(hostId) {
  var widget = _filterSelects[hostId];
  if (!widget) return;
  widget.menu.innerHTML = '';

  if (widget.filtered.length === 0) {
    var noMatchesRow = document.createElement('div');
    noMatchesRow.className = 'filter-select-option no-matches';
    noMatchesRow.textContent = t('diff.noMatches');
    widget.menu.appendChild(noMatchesRow);
    return;
  }

  widget.filtered.forEach(function(option, index) {
    var row = document.createElement('div');
    row.className = 'filter-select-option';
    if (option.value === widget.value) row.classList.add('selected');
    if (index === widget.highlightIndex) row.classList.add('highlighted');
    row.textContent = option.label;
    row.dataset.value = option.value;
    widget.menu.appendChild(row);
  });
}

function _scrollFilterSelectHighlightIntoView(widget) {
  var el = widget.menu.querySelector('.filter-select-option.highlighted');
  if (el) el.scrollIntoView({ block: 'nearest' });
}

function _handleFilterSelectKeydown(hostId, e) {
  var widget = _filterSelects[hostId];
  if (!widget) return;

  if (!widget.open) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') _openFilterSelect(hostId);
    return;
  }

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!widget.filtered.length) return;
    var delta = e.key === 'ArrowDown' ? 1 : -1;
    widget.highlightIndex = (widget.highlightIndex + delta + widget.filtered.length) % widget.filtered.length;
    _renderFilterSelectMenu(hostId);
    _scrollFilterSelectHighlightIntoView(widget);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (widget.highlightIndex >= 0 && widget.filtered[widget.highlightIndex]) {
      _commitFilterSelect(hostId, widget.filtered[widget.highlightIndex].value);
    }
  } else if (e.key === 'Escape') {
    e.preventDefault();
    _closeFilterSelect(hostId, true);
  }
}

function _commitFilterSelect(hostId, value) {
  var widget = _filterSelects[hostId];
  if (!widget) return;
  var changed = widget.value !== value;
  widget.value = value;
  widget.input.value = _filterSelectLabelFor(widget, value);
  _closeFilterSelect(hostId, false);
  if (changed && typeof widget.onChange === 'function') widget.onChange(value);
}

function setFilterSelectOptions(hostId, options, selectedValue) {
  var widget = _filterSelects[hostId];
  if (!widget) return;
  widget.options = options || [];
  widget.value = selectedValue;
  if (!widget.open) {
    widget.input.value = _filterSelectLabelFor(widget, selectedValue);
  }
}

function getFilterSelectValue(hostId) {
  var widget = _filterSelects[hostId];
  return widget ? widget.value : undefined;
}

document.addEventListener('click', function(e) {
  Object.keys(_filterSelects).forEach(function(hostId) {
    var widget = _filterSelects[hostId];
    if (widget.open && !widget.host.contains(e.target)) {
      _closeFilterSelect(hostId, true);
    }
  });
});

initFilterSelect('diffRepoSelect', function(value) { setDiffRepo(value); });
initFilterSelect('diffBaseSelect', function(value) { setDiffBase(value); });

document.addEventListener('keydown', function(e) {
  var searchInput = document.getElementById('diffFileSearch');
  if (!searchInput) return;

  if (document.activeElement === searchInput && e.key === 'Escape') {
    searchInput.value = '';
    filterDiffFiles('');
    searchInput.blur();
    return;
  }

  var panelChanges = document.getElementById('panel-changes');
  if (!panelChanges || !panelChanges.classList.contains('active')) return;
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  if (e.key.length !== 1 || e.key === ' ') return;

  var target = e.target;
  var tagName = target && target.tagName;
  if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT' || (target && target.isContentEditable)) return;

  searchInput.focus();
});

// ═══════════════════════════════════════════════
//  DIFF FILE LIST
// ═══════════════════════════════════════════════
var _diffFilter = '';
var _showResolved = false;

async function goToFileViewer(filePath) {
  await switchTab('files');
  selectExplorerFile(filePath);
}

document.addEventListener('workspace-reset', function() {
  _diffFilter = '';
  var searchInput = document.getElementById('diffFileSearch');
  if (searchInput) searchInput.value = '';
});

function filterDiffFiles(query) {
  _diffFilter = query.toLowerCase();
  renderFileList();
}


function fileHasUnresolvedComments(filePath) {
  var key = 'review:' + filePath;
  var all = COMMENTS[key] || [];
  return all.some(function(c) { return !c.resolved && !c.parent_id; });
}

function renderFileList() {
  const container = document.getElementById('diffFileList');
  const header = container.querySelector('.diff-file-list-header');
  var wasMobileOpen = container.classList.contains('mobile-open');
  container.innerHTML = '';
  container.appendChild(header);
  if (wasMobileOpen) container.classList.add('mobile-open');

  var files = DIFF_DATA.files;
  if (_diffFilter) {
    files = files.filter(function(f) { return f.path.split('/').pop().toLowerCase().indexOf(_diffFilter) !== -1; });
  }

  if (state.fileView === 'flat') {
    files.forEach(f => {
      const div = document.createElement('div');
      div.className = 'file-item' + (state.selectedFile === f.path ? ' active' : '');
      div.title = f.path;
      div.dataset.path = f.path;
      div.onclick = (e) => { if (!e.target.closest('.comment-icon, .go-to-file-btn')) selectFile(f.path); };
      var unresolvedDot = fileHasUnresolvedComments(f.path) ? '<span class="file-unresolved-dot" title="Has unresolved comments"></span>' : '';
      var goToBtn = '<button class="btn btn-sm go-to-file-btn" data-filepath="' + escapeHtml(f.path) + '" title="' + t('buttons.goToFileViewer') + '" style="padding: 0 4px; font-size: 0.7rem; line-height: 1; flex-shrink: 0;">&#128196;</button>';
      var displayName = f.path.split('/').pop();
      if (f.old_path && f.old_path !== f.path) {
        displayName = f.path.split('/').pop() + ' ← ' + f.old_path.split('/').pop();
      }
      div.innerHTML = `<span>${escapeHtml(displayName)}</span>${unresolvedDot}${renderCommentIcon('review', f.path)}${goToBtn}<div class="file-stat"><span class="file-stat-add">+${f.additions}</span><span class="file-stat-del">-${f.deletions}</span></div>`;
      container.appendChild(div);
    });
  } else {
    const tree = buildFileTree(files, function(f) { return f.path; });
    renderTreeNode(tree, container, 0, {
      pathFn: function(item) { return item.path; },
      isSelected: function(path) { return state.selectedFile === path; },
      onClick: function(e, val) { if (!e.target.closest('.comment-icon, .go-to-file-btn')) selectFile(val.path); },
      renderFileContent: function(val, key) {
        var unresolvedDot = fileHasUnresolvedComments(val.path) ? '<span class="file-unresolved-dot" title="Has unresolved comments"></span>' : '';
        var goToBtn = '<button class="btn btn-sm go-to-file-btn" data-filepath="' + escapeHtml(val.path) + '" title="' + t('buttons.goToFileViewer') + '" style="padding: 0 4px; font-size: 0.7rem; line-height: 1; flex-shrink: 0;">&#128196;</button>';
        var displayKey = key;
        if (val.old_path && val.old_path !== val.path) {
          var oldName = val.old_path.split('/').pop();
          displayKey = key + ' ← ' + oldName;
        }
        return '<span>' + escapeHtml(displayKey) + '</span>' + unresolvedDot + renderCommentIcon('review', val.path) + goToBtn + '<div class="file-stat"><span class="file-stat-add">+' + val.additions + '</span><span class="file-stat-del">-' + val.deletions + '</span></div>';
      }
    });
  }

  var countEl = document.getElementById('fileCount');
  if (countEl) countEl.textContent = files.length;
  var badgeEl = document.getElementById('diffFileCount');
  if (badgeEl) badgeEl.textContent = t('badges.filesChanged', {count: DIFF_DATA.files.length});
}


function selectFile(path) {
  state.selectedFile = path;
  var fileList = document.getElementById('diffFileList');
  if (fileList) {
    fileList.querySelectorAll('.file-item').forEach(function(el) {
      if (el.dataset.path === path) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    });
  }
  renderDiff(path);
  var btn = document.getElementById('viewFileBtn');
  if (btn) btn.style.display = path ? '' : 'none';
}


function openSelectedFile() {
  if (state.selectedFile) showFilePreview(state.selectedFile);
}

function renderDiff(path) {
  const file = DIFF_DATA.files.find(f => f.path === path);
  if (!file) return;
  const container = document.getElementById('diffContent');
  container.innerHTML = '';

  const pathHeader = document.createElement('div');
  pathHeader.className = 'diff-path-header';
  pathHeader.style.cssText = 'padding: 6px 12px; font-size: 0.8rem; font-family: var(--font-mono); color: var(--text-secondary); background: var(--bg-secondary); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px;';

  var pathText = escapeHtml(path);
  if (file.old_path && file.old_path !== path) {
    pathText = '<span style="color: var(--text-muted);">' + escapeHtml(file.old_path) + '</span> <span style="color: var(--text-secondary); font-size: 0.75rem;">\u2192</span> ' + escapeHtml(path);
  }
  pathHeader.innerHTML = '<span style="opacity: 0.6;">\uD83D\uDCC4</span> ' + pathText + ' <span style="font-size: 0.75rem; color: var(--text-muted);">+' + file.additions + ' \u2212' + file.deletions + '</span>';

  var goToFileViewerBtn = document.createElement('button');
  goToFileViewerBtn.className = 'btn btn-sm';
  goToFileViewerBtn.style.cssText = 'margin-left: auto; font-size: 0.7rem;';
  goToFileViewerBtn.title = t('buttons.goToFileViewer');
  goToFileViewerBtn.innerHTML = '&#128196; ' + t('buttons.goToFileViewer');
  goToFileViewerBtn.onclick = function() { goToFileViewer(path); };
  pathHeader.appendChild(goToFileViewerBtn);

  var showResolvedBtn = document.createElement('button');
  showResolvedBtn.className = 'btn btn-sm';
  showResolvedBtn.style.cssText = 'font-size: 0.7rem;';
  showResolvedBtn.textContent = _showResolved ? t('review.hideResolved') : t('review.showResolved');
  showResolvedBtn.onclick = function() {
    _showResolved = !_showResolved;
    renderDiff(path);
  };
  pathHeader.appendChild(showResolvedBtn);
  container.appendChild(pathHeader);

  const targetEl = document.createElement('div');
  container.appendChild(targetEl);

  const ui = new Diff2HtmlUI(targetEl, file.diff, {
    drawFileList: false,
    matching: 'words',
    renderNothingWhenEmpty: true,
    outputFormat: state.diffMode,
    highlight: true,
    synchronisedScroll: true,
    stickyFileHeaders: false
  });
  ui.draw();
  ui.highlightCode();
  attachDiffLineClickHandlers(targetEl, path);
  renderDiffLineCommentIndicators(targetEl, path);
  autoExpandUnresolvedThreads(targetEl, path);
}

function getDiffLineNumber(td) {
  var text = td.textContent.trim();
  if (!text) return null;
  var match = text.match(/(\d+)/);
  if (!match) return null;
  return parseInt(match[1]);
}

function getDiffLineContent(tr) {
  var ctnEl = tr.querySelector('.d2h-code-line-ctn, .d2h-code-side-line-ctn');
  return ctnEl ? ctnEl.textContent : '';
}

function getDiffFilePath(td) {
  var fileWrapper = td.closest('.d2h-file-wrapper');
  if (fileWrapper) {
    var header = fileWrapper.querySelector('.d2h-file-name');
    if (header) return header.textContent.trim();
  }
  return null;
}

function attachDiffLineClickHandlers(container, filePath) {
  var lineNumCells = container.querySelectorAll('td.d2h-code-linenumber, td.d2h-code-side-linenumber');
  lineNumCells.forEach(function(td) {
    td.addEventListener('click', function(e) {
      e.stopPropagation();
      var lineNum = getDiffLineNumber(td);
      if (!lineNum) return;

      var tr = td.closest('tr');

      // Toggle: if a comment form/thread row is already open for this line, close it
      var existingRow = tr.nextElementSibling;
      if (existingRow && existingRow.classList.contains('line-comment-row')) {
        existingRow.remove();
        return;
      }

      var lineContent = getDiffLineContent(tr);
      var target = filePath;

      document.querySelectorAll('.diff-content .line-comment-row').forEach(function(el) { el.remove(); });

      var formRow = document.createElement('tr');
      formRow.className = 'line-comment-row';
      var formCell = document.createElement('td');
      var colSpan = tr.querySelectorAll('td').length;
      formCell.setAttribute('colspan', colSpan);
      formRow.appendChild(formCell);
      tr.parentNode.insertBefore(formRow, tr.nextSibling);

      var lineComments = getCommentsForLine(filePath, lineNum);
      lineComments.forEach(function(comment) {
        var thread = renderReviewThread(comment, {
          showFileInfo: false,
          onResolve: function(id) { resolveReviewComment(id); },
          onReply: function(id, text) { replyToReviewComment(id, text); }
        });
        formCell.appendChild(thread);
      });

      openLineCommentForm('review', target, filePath, lineNum, lineContent, formCell);
    });
  });
}

function renderDiffLineCommentIndicators(container, filePath) {
  var key = 'review:' + filePath;
  var allComments = COMMENTS[key] || [];
  var lineComments = {};
  allComments.forEach(function(c) {
    if (c.line_start != null && !c.parent_id && (!c.resolved || _showResolved)) {
      if (!lineComments[c.line_start]) lineComments[c.line_start] = [];
      lineComments[c.line_start].push(c);
    }
  });

  if (Object.keys(lineComments).length === 0) return;

  var lineNumCells = container.querySelectorAll('td.d2h-code-linenumber, td.d2h-code-side-linenumber');
  lineNumCells.forEach(function(td) {
    var lineNum = getDiffLineNumber(td);
    if (lineNum && lineComments[lineNum]) {
      var comments = lineComments[lineNum];
      var count = comments.length;
      var hasUnresolved = comments.some(function(c) { return !c.resolved; });
      var indicator = document.createElement('span');
      indicator.className = 'line-comment-indicator';
      indicator.innerHTML = '&#x1F4AC;';
      if (count > 1) {
        indicator.innerHTML += '<span class="line-comment-count">' + count + '</span>';
      }
      indicator.title = count + ' comment' + (count > 1 ? 's' : '');
      td.insertBefore(indicator, td.firstChild);
      var row = td.closest('tr');
      row.classList.add('line-has-comment');
      if (hasUnresolved) {
        row.classList.add('line-has-unresolved');
      }
    }
  });
}

function autoExpandUnresolvedThreads(container, filePath) {
  var key = 'review:' + filePath;
  var allComments = COMMENTS[key] || [];
  var unresolvedLines = {};
  allComments.forEach(function(c) {
    if (c.line_start != null && !c.parent_id && !c.resolved) {
      unresolvedLines[c.line_start] = true;
    }
  });

  if (Object.keys(unresolvedLines).length === 0) return;

  var processedLines = {};
  var lineNumCells = container.querySelectorAll('td.d2h-code-linenumber, td.d2h-code-side-linenumber');
  lineNumCells.forEach(function(td) {
    var lineNum = getDiffLineNumber(td);
    if (!lineNum || !unresolvedLines[lineNum]) return;
    if (processedLines[lineNum]) return;

    var tr = td.closest('tr');
    if (tr.nextElementSibling && tr.nextElementSibling.classList.contains('line-comment-row')) return;

    var formRow = document.createElement('tr');
    formRow.className = 'line-comment-row';
    var formCell = document.createElement('td');
    var colSpan = tr.querySelectorAll('td').length;
    formCell.setAttribute('colspan', colSpan);
    formRow.appendChild(formCell);
    tr.parentNode.insertBefore(formRow, tr.nextSibling);
    processedLines[lineNum] = true;

    var lineComments = getCommentsForLine(filePath, lineNum);
    lineComments.forEach(function(comment) {
      var thread = renderReviewThread(comment, {
        showFileInfo: false,
        onResolve: function(id) { resolveReviewComment(id); },
        onReply: function(id, text) { replyToReviewComment(id, text); }
      });
      formCell.appendChild(thread);
    });

    unresolvedLines[lineNum] = false;
  });
}

function getCommentsForLine(filePath, lineNum) {
  var key = 'review:' + filePath;
  var all = COMMENTS[key] || [];
  return all.filter(function(c) {
    if (c.parent_id) return false;
    if (c.resolved && !_showResolved) return false;
    return c.line_start <= lineNum && (c.line_end || c.line_start) >= lineNum;
  });
}

async function resolveReviewComment(commentId) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var allReview = getReviewComments();
    var comment = allReview.find(function(c) { return c.id === commentId; });
    var resolved = comment && comment.resolved;
    await apiResolveComment(ctx.projectId, ctx.branch, commentId, !resolved);
    await refreshComments();
  } catch(e) {
    showToast(t('messages.failedToResolve', {error: e.message}));
  }
}

async function replyToReviewComment(commentId, text) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    await apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/comments/' + commentId + '/reply', {text: text});
    await refreshComments();
  } catch(e) {
    showToast(t('messages.failedToUpdate', {error: e.message}));
  }
}

async function refreshComments() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  await loadReviewComments();
  renderDiffView();
  renderReviewTab();
  updateReviewBadge();
}

function renderDiffView() {
  renderFileList();
  if (state.selectedFile) renderDiff(state.selectedFile);
}

function setFileView(mode) {
  state.fileView = mode;
  localStorage.setItem('diff_fileView', mode);
  document.querySelectorAll('#viewModeToggle .toggle-opt').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  renderFileList();
}

function setDiffMode(mode) {
  state.diffMode = mode;
  localStorage.setItem('diff_diffMode', mode);
  document.querySelectorAll('#diffModeToggle .toggle-opt').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  if (state.selectedFile) renderDiff(state.selectedFile);
}

async function _loadDiff(mode, commitSha) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var diffData = await apiGetDiff(ctx.projectId, ctx.branch, mode, commitSha, state.diffRepo, state.diffBase);
    if (diffData) {
      AppState.diff = diffData;
      DIFF_DATA = AppState.diff;
    }
  } catch (e) {
    console.warn('Diff API unavailable:', e.message);
    // Clear diff data on error so stale files don't linger
    AppState.diff = { files: [] };
    DIFF_DATA = AppState.diff;
    if (e && e.payload && e.payload.error === 'base_ref_not_found') {
      showToast(t('diff.baseNotFound'));
    } else {
      showToast(t('diff.loadFailed'));
    }
  }
}

async function loadDiffRepos() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var data = await apiGetRepos(ctx.projectId, ctx.branch);
    var repos = data.repos || [];
    var options = repos.map(function(repo) { return { value: repo.path, label: repo.name }; });

    var validPaths = repos.map(function(repo) { return repo.path; });
    if (validPaths.indexOf(state.diffRepo) === -1) {
      state.diffRepo = '.';
      localStorage.removeItem('diff_repo');
    }
    setFilterSelectOptions('diffRepoSelect', options, state.diffRepo);
  } catch (e) {
    console.warn('Failed to load repos:', e.message);
    state.diffRepo = '.';
    var existingWidget = _filterSelects['diffRepoSelect'];
    if (!existingWidget || existingWidget.options.length === 0) {
      setFilterSelectOptions('diffRepoSelect', [{ value: '.', label: t('diff.repository') }], '.');
    }
  }
}

async function loadDiffBases() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var options = [{ value: '', label: t('diff.baseDefault') }];

  try {
    var data = await apiGetBranches(ctx.projectId, ctx.branch, state.diffRepo);
    var branches = data.branches || [];
    branches.forEach(function(branch) { options.push({ value: branch.name, label: branch.name }); });

    var validNames = branches.map(function(branch) { return branch.name; });
    if (state.diffBase && validNames.indexOf(state.diffBase) === -1) {
      state.diffBase = '';
      localStorage.removeItem('diff_base');
    }
  } catch (e) {
    console.warn('Failed to load base branches:', e.message);
  }

  setFilterSelectOptions('diffBaseSelect', options, state.diffBase);
}

async function setDiffRepo(path) {
  localStorage.setItem('diff_repo', path);
  state.diffRepo = path;
  state.activeCommit = null;
  state.historyCommits = [];
  state.selectedFile = null;

  await loadDiffBases();
  await setDiffSource(state.diffSource);
  renderFileList();
}

async function setDiffBase(name) {
  localStorage.setItem('diff_base', name);
  state.diffBase = name;

  if (state.diffSource === 'branch') {
    await _loadDiff(state.diffSource);
    renderFileList();
  } else {
    await setDiffSource('branch');
  }
}

async function setDiffSource(mode) {
  localStorage.setItem('diff_diffSource', mode);
  state.diffSource = mode;
  document.querySelectorAll('#diffSourceToggle .toggle-opt').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));

  if (mode !== 'commit') {
    state.activeCommit = null;
    await _loadDiff(mode);
    renderFileList();
    return;
  }

  if (state.historyCommits.length === 0) {
    await loadCommitHistory();
  }

  if (!state.activeCommit && state.historyCommits.length > 0) {
    state.activeCommit = state.historyCommits[0].full_sha;
  }

  openHistoryPanel();
  loadHistoryBranches();

  if (state.activeCommit) {
    await _loadDiff('commit', state.activeCommit);
    renderFileList();
    renderHistoryPanel();
  }
}

// ═══════════════════════════════════════════════
//  RESIZABLE FILE LIST PANEL
// ═══════════════════════════════════════════════
makeResizable('diffResizeHandle', 'diffFileList');
makeResizable('historyResizeHandle', 'diffBranchList');

document.addEventListener('click', function(e) {
  var btn = e.target.closest('.go-to-file-btn');
  if (btn && btn.dataset.filepath) {
    e.stopPropagation();
    goToFileViewer(btn.dataset.filepath);
  }
});

EventBus.on('state:refreshed', function() {
  renderFileList();
});

EventBus.on('comments:changed', function() {
  renderFileList();
  if (state.selectedFile) renderDiff(state.selectedFile);
});

// ═══════════════════════════════════════════════
//  COMMIT HISTORY PANEL
// ═══════════════════════════════════════════════

async function loadCommitHistory() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  state.historyLoading = true;
  state.historyError = null;
  renderHistoryPanel();
  try {
    var ref = (state.activeBranch && state.activeBranch !== ctx.branch) ? state.activeBranch : null;
    var data = await apiGetCommitHistory(ctx.projectId, ctx.branch, ref, state.diffRepo);
    state.historyCommits = data.commits || [];
    state.historySourceBranch = state.activeBranch || ctx.branch;
    if (state.branches.length === 0) {
      loadHistoryBranches();
    }
  } catch (e) {
    state.historyError = e.message;
  } finally {
    state.historyLoading = false;
    renderHistoryPanel();
  }
}

async function loadHistoryBranches() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var data = await apiGetBranches(ctx.projectId, ctx.branch, state.diffRepo);
    state.branches = data.branches || [];
    renderHistoryBranches();
  } catch (e) {
    console.warn('Failed to load branches:', e.message);
  }
}

function renderHistoryBranches() {
  var list = document.getElementById('diffBranchList');
  if (!list) return;
  list.innerHTML = '';

  state.branches.forEach(function(branch) {
    var row = document.createElement('div');
    row.className = 'diff-branch-row';
    if (branch.current && !state.activeBranch) row.classList.add('active');
    if (state.activeBranch === branch.ref) row.classList.add('active');
    row.textContent = branch.name;
    row.title = branch.ref;
    row.addEventListener('click', function() {
      selectHistoryBranch(branch.ref, branch.name);
    });
    list.appendChild(row);
  });
}

async function selectHistoryBranch(ref, displayName) {
  state.activeBranch = ref;
  state.activeCommit = null;
  state.selectedCommits = [];
  renderHistoryBranches();

  var ctx = getWorkspaceContext();
  if (!ctx) return;
  try {
    var refParam = (ref && ref !== ctx.branch) ? ref : null;
    var data = await apiGetCommitHistory(ctx.projectId, ctx.branch, refParam, state.diffRepo);
    state.historyCommits = data.commits || [];
    var label = document.getElementById('diffHistoryBranchLabel');
    if (label) label.textContent = displayName;
    renderHistoryPanel();
  } catch (e) {
    console.warn('Failed to load branch history:', e.message);
  }
}

function renderHistoryPanel() {
  var list = document.getElementById('diffHistoryList');
  if (!list) return;
  list.innerHTML = '';

  var branchLabel = document.getElementById('diffHistoryBranchLabel');
  if (branchLabel && state.historySourceBranch) {
    branchLabel.textContent = state.historySourceBranch;
  } else if (branchLabel) {
    branchLabel.textContent = '';
  }

  if (state.historyLoading) {
    var loadingEl = document.createElement('div');
    loadingEl.className = 'diff-history-loading';
    loadingEl.textContent = t('explorer.loading') || 'Loading...';
    list.appendChild(loadingEl);
    return;
  }

  if (state.historyError) {
    var errorEl = document.createElement('div');
    errorEl.className = 'diff-history-error';
    errorEl.textContent = state.historyError;
    list.appendChild(errorEl);
    return;
  }

  state.historyCommits.forEach(function(commit) {
    var row = document.createElement('div');
    var isActive = commit.full_sha === state.activeCommit;
    var isSelected = state.selectedCommits.indexOf(commit.full_sha) !== -1;
    var cls = 'diff-history-row';
    if (isActive) cls += ' active';
    if (isSelected) cls += ' selected';
    row.className = cls;

    var aheadDot = commit.ahead_of_origin ? '<span class="ahead-marker" title="Ahead of origin"></span>' : '';
    var sha = document.createElement('span');
    sha.className = 'commit-sha';
    sha.innerHTML = aheadDot + escapeHtml(commit.short_sha || commit.full_sha.substring(0, 7));

    var subject = document.createElement('span');
    subject.className = 'commit-subject';
    subject.textContent = commit.subject || '';
    subject.title = commit.subject || '';

    var author = document.createElement('span');
    author.className = 'commit-author';
    author.textContent = commit.author || '';

    var date = document.createElement('span');
    date.className = 'commit-date';
    date.textContent = commit.date ? formatRelativeDate(commit.date) : '';

    row.appendChild(sha);
    row.appendChild(subject);
    row.appendChild(author);
    row.appendChild(date);

    row.addEventListener('click', function(e) {
      selectCommit(commit.full_sha, e);
    });

    list.appendChild(row);
  });

  updateSelectionCountDisplay();
  updateRewriteButtonsState();
}

async function selectCommit(fullSha, event) {
  if (event && (event.metaKey || event.ctrlKey)) {
    var idx = state.selectedCommits.indexOf(fullSha);
    if (idx === -1) {
      state.selectedCommits.push(fullSha);
    } else {
      state.selectedCommits.splice(idx, 1);
    }
    renderHistoryPanel();
    return;
  }

  state.selectedCommits = [];
  state.activeCommit = fullSha;

  await _loadDiff('commit', fullSha);
  renderFileList();
  renderHistoryPanel();

  // Re-render the currently selected file if it exists in this commit's diff
  if (state.selectedFile && DIFF_DATA && DIFF_DATA.files) {
    var fileStillExists = DIFF_DATA.files.some(function(f) {
      return f.filename === state.selectedFile;
    });
    if (fileStillExists) {
      renderDiff(state.selectedFile);
    }
  }
}

function updateSelectionCountDisplay() {
  var countEl = document.getElementById('diffHistorySelectionCount');
  if (!countEl) return;
  var count = state.selectedCommits.length;
  if (count > 0) {
    countEl.textContent = count + ' selected';
    countEl.style.display = '';
  } else {
    countEl.style.display = 'none';
  }
}

async function openHistoryPanel() {
  state.historyPanelOpen = true;
  var panel = document.getElementById('diffHistoryPanel');
  if (panel) panel.style.display = '';

  if (state.diffSource !== 'commit') {
    await setDiffSource('commit');
  } else {
    await loadCommitHistory();
    loadHistoryBranches();
  }
}

async function toggleHistoryPanel() {
  if (state.historyPanelOpen) {
    closeHistoryPanel();
  } else {
    await openHistoryPanel();
  }
}

function closeHistoryPanel() {
  state.historyPanelOpen = false;
  var panel = document.getElementById('diffHistoryPanel');
  if (panel) panel.style.display = 'none';
}

// History panel always starts collapsed. Data loads when user clicks History button.

// ═══════════════════════════════════════════════
//  HISTORY REWRITE ACTIONS
// ═══════════════════════════════════════════════

function isSelectionContiguous(selectedShas, historyCommits) {
  if (selectedShas.length < 2) return false;
  var indices = selectedShas.map(function(sha) {
    return historyCommits.findIndex(function(c) { return c.full_sha === sha; });
  }).filter(function(i) { return i !== -1; });
  if (indices.length !== selectedShas.length) return false;
  indices.sort(function(a, b) { return a - b; });
  for (var i = 1; i < indices.length; i++) {
    if (indices[i] !== indices[i - 1] + 1) return false;
  }
  return true;
}

function updateRewriteButtonsState() {
  var renameBtn = document.getElementById('historyRenameBtn');
  var undoBtn = document.getElementById('historyUndoBtn');
  var squashBtn = document.getElementById('historySquashBtn');
  if (!renameBtn || !undoBtn || !squashBtn) return;

  var headIsLocalUnpushed = state.historyCommits.length >= 1 && state.historyCommits[0].ahead_of_origin === true;

  var active = state.historyCommits.find(function(c) { return c.full_sha === state.activeCommit; }) || state.historyCommits[0];
  var activeIsLocalUnpushed = !!(active && active.ahead_of_origin === true);

  var squashable = state.selectedCommits.length >= 2 &&
    state.selectedCommits.every(function(sha) {
      var c = state.historyCommits.find(function(h) { return h.full_sha === sha; });
      return c && c.ahead_of_origin === true;
    }) &&
    isSelectionContiguous(state.selectedCommits, state.historyCommits);

  renameBtn.disabled = !activeIsLocalUnpushed;
  renameBtn.title = activeIsLocalUnpushed
    ? ''
    : 'Rename is only available for a selected local unpushed commit';

  undoBtn.disabled = !headIsLocalUnpushed;
  undoBtn.title = headIsLocalUnpushed
    ? ''
    : 'Undo is only available for the latest local unpushed commit';

  squashBtn.disabled = !squashable;
  squashBtn.title = squashable
    ? ''
    : 'Squash requires a contiguous selection of 2+ local unpushed commits';
}

// ── Inline promise-based dialog helper ──────────────────────────────────────

function _showHistoryDialog(options) {
  return new Promise(function(resolve) {
    var existing = document.getElementById('historyDialogOverlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'historyDialogOverlay';
    overlay.className = 'file-preview-modal open';
    overlay.style.zIndex = '10100';

    var content = document.createElement('div');
    content.className = 'file-preview-content';
    content.style.maxWidth = '480px';

    var header = document.createElement('div');
    header.className = 'file-preview-header';
    var titleEl = document.createElement('span');
    titleEl.className = 'file-preview-path';
    titleEl.textContent = options.title || '';
    header.appendChild(titleEl);
    content.appendChild(header);

    var body = document.createElement('div');
    body.className = 'file-preview-body';
    body.style.display = 'flex';
    body.style.flexDirection = 'column';
    body.style.gap = '10px';

    if (options.message) {
      var msg = document.createElement('p');
      msg.style.margin = '0';
      msg.style.fontSize = '0.85rem';
      msg.style.color = 'var(--text-secondary)';
      msg.textContent = options.message;
      body.appendChild(msg);
    }

    if (options.extraHtml) {
      var extra = document.createElement('div');
      extra.innerHTML = options.extraHtml;
      body.appendChild(extra);
    }

    var inputEl = null;
    if (options.inputLabel) {
      var lbl = document.createElement('label');
      lbl.style.fontSize = '0.78rem';
      lbl.style.fontWeight = '600';
      lbl.style.color = 'var(--text-muted)';
      lbl.textContent = options.inputLabel;
      body.appendChild(lbl);

      if (options.textarea) {
        inputEl = document.createElement('textarea');
        inputEl.rows = 5;
        inputEl.style.width = '100%';
        inputEl.style.boxSizing = 'border-box';
        inputEl.style.fontFamily = 'var(--font-mono)';
        inputEl.style.fontSize = '0.8rem';
        inputEl.style.padding = '8px 10px';
        inputEl.style.border = '1px solid var(--border)';
        inputEl.style.borderRadius = 'var(--radius-sm)';
        inputEl.style.background = 'var(--bg-input)';
        inputEl.style.color = 'var(--text-primary)';
        inputEl.style.resize = 'vertical';
      } else {
        inputEl = document.createElement('input');
        inputEl.type = 'text';
        inputEl.style.width = '100%';
        inputEl.style.boxSizing = 'border-box';
        inputEl.style.fontFamily = 'var(--font-mono)';
        inputEl.style.fontSize = '0.85rem';
        inputEl.style.padding = '8px 10px';
        inputEl.style.border = '1px solid var(--border)';
        inputEl.style.borderRadius = 'var(--radius-sm)';
        inputEl.style.background = 'var(--bg-input)';
        inputEl.style.color = 'var(--text-primary)';
      }
      if (options.inputValue !== undefined) inputEl.value = options.inputValue;
      body.appendChild(inputEl);
    }

    var footer = document.createElement('div');
    footer.style.display = 'flex';
    footer.style.justifyContent = 'flex-end';
    footer.style.gap = '8px';
    footer.style.paddingTop = '4px';

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-sm';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = function() { overlay.remove(); resolve(null); };

    var confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-sm btn-primary';
    confirmBtn.textContent = options.confirmLabel || 'Confirm';
    confirmBtn.onclick = function() {
      overlay.remove();
      resolve(inputEl ? inputEl.value : true);
    };

    footer.appendChild(cancelBtn);
    footer.appendChild(confirmBtn);
    body.appendChild(footer);
    content.appendChild(body);
    overlay.appendChild(content);

    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) { overlay.remove(); resolve(null); }
    });

    document.body.appendChild(overlay);
    if (inputEl) inputEl.focus();
  });
}

async function historyRename() {
  var target = state.historyCommits.find(function(c) { return c.full_sha === state.activeCommit; }) || state.historyCommits[0];
  if (!target || !target.ahead_of_origin) {
    showToast(t('history.errors.renameFailed', { error: 'No local unpushed commit selected' }));
    return;
  }
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var fullMessage = target.subject || '';
  if (target.body) { fullMessage += '\n\n' + target.body; }

  var newMessage = await _showHistoryDialog({
    title: t('history.rename'),
    inputLabel: t('history.dialogs.renamePrompt'),
    inputValue: fullMessage,
    textarea: true,
    confirmLabel: t('history.rename')
  });
  if (newMessage === null || newMessage.trim() === '') return;

  try {
    await apiHistoryRename(ctx.projectId, ctx.branch, target.full_sha, newMessage.trim());
    showToast(t('history.rename') + ' OK');
    await loadCommitHistory();
  } catch (e) {
    showToast(t('history.errors.renameFailed', { error: e.message }));
  }
}

async function historyUndo() {
  if (state.historyCommits.length === 0 || !state.historyCommits[0].ahead_of_origin) {
    showToast(t('history.errors.undoFailed', { error: 'No local unpushed commit to undo' }));
    return;
  }
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var head = state.historyCommits[0];
  var subject = head.subject || '';
  var confirmed = await _showHistoryDialog({
    title: t('history.undo'),
    message: t('history.dialogs.undoConfirm', { subject: subject }),
    confirmLabel: t('history.undo')
  });
  if (!confirmed) return;

  try {
    await apiHistoryUndo(ctx.projectId, ctx.branch);
    showToast(t('history.undo') + ' OK');
    await loadCommitHistory();
  } catch (e) {
    showToast(t('history.errors.undoFailed', { error: e.message }));
  }
}

async function historySquash() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  if (state.selectedCommits.length < 2) {
    showToast(t('history.errors.squashFailed', { error: 'Select 2 or more commits to squash' }));
    return;
  }

  var allAhead = state.selectedCommits.every(function(sha) {
    var c = state.historyCommits.find(function(h) { return h.full_sha === sha; });
    return c && c.ahead_of_origin === true;
  });
  if (!allAhead) {
    showToast(t('history.errors.squashFailed', { error: 'All selected commits must be local unpushed' }));
    return;
  }

  if (!isSelectionContiguous(state.selectedCommits, state.historyCommits)) {
    showToast(t('history.errors.squashFailed', { error: 'Selection must be contiguous' }));
    return;
  }

  var selectedDetails = state.selectedCommits.map(function(sha) {
    return state.historyCommits.find(function(h) { return h.full_sha === sha; });
  }).filter(Boolean).sort(function(a, b) {
    return state.historyCommits.indexOf(a) - state.historyCommits.indexOf(b);
  });

  var newestSubject = selectedDetails[0].subject || '';
  var otherSubjects = selectedDetails.slice(1).map(function(c) { return c.subject || ''; });
  var defaultMessage = newestSubject + (otherSubjects.length > 0 ? '\n\n' + otherSubjects.join('\n\n') : '');

  var count = selectedDetails.length;
  var commitList = selectedDetails.map(function(c) {
    return (c.short_sha || c.full_sha.substring(0, 7)) + ' ' + escapeHtml(c.subject || '');
  }).join('\n');

  var editedMessage = await _showHistoryDialog({
    title: t('history.dialogs.squashTitle', { count: count }),
    extraHtml: '<pre style="font-size:0.75rem;color:var(--text-muted);background:var(--bg-base);padding:8px 10px;border-radius:var(--radius-sm);margin:0;overflow:auto;max-height:80px;">' + commitList + '</pre>',
    inputLabel: t('history.dialogs.squashMessage'),
    inputValue: defaultMessage,
    textarea: true,
    confirmLabel: t('history.squash')
  });
  if (editedMessage === null) return;

  var fullShas = selectedDetails.map(function(c) { return c.full_sha; });

  try {
    await apiHistorySquash(ctx.projectId, ctx.branch, fullShas, editedMessage.trim());
    showToast(t('history.squash') + ' OK');
    state.selectedCommits = [];
    await loadCommitHistory();
  } catch (e) {
    showToast(t('history.errors.squashFailed', { error: e.message }));
  }
}
