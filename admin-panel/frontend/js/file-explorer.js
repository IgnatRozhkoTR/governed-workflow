// ═══════════════════════════════════════════════
//  FILE EXPLORER (lazy directory loading)
// ═══════════════════════════════════════════════

var explorerState = { selectedFile: null, filter: '', mdMode: 'preview', dirCache: {}, totalFiles: 0 };
var _explorerPreviousLspFile = null;
var _explorerSaveBtn = null;
var _explorerEditorDirty = false;

function explorerApiUrl(ctx, params) {
  var url = '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/files';
  if (params) url += '?' + params;
  return url;
}

async function loadExplorerFiles() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  explorerState.dirCache = {};
  explorerState.filter = '';
  var searchInput = document.getElementById('fileExplorerSearch');
  if (searchInput) searchInput.value = '';
  try {
    var data = await apiGet(explorerApiUrl(ctx));
    explorerState.dirCache[''] = data.entries || [];
    explorerState.totalFiles = data.total || 0;
    renderExplorerLazy();
  } catch (e) {
    console.warn('Failed to load files:', e.message);
  }
}

async function expandExplorerDir(dirPath, dirEl) {
  if (dirEl.dataset.loading === 'true') return;

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var childrenEl = dirEl.nextElementSibling;
  if (!childrenEl || !childrenEl.classList.contains('dir-children')) return;

  if (dirEl.classList.contains('collapsed')) {
    dirEl.classList.remove('collapsed');
    if (explorerState.dirCache[dirPath]) {
      if (!childrenEl.hasChildNodes()) {
        renderExplorerEntries(explorerState.dirCache[dirPath], childrenEl, dirPath);
      }
      childrenEl.style.display = '';
      return;
    }
    dirEl.dataset.loading = 'true';
    childrenEl.innerHTML = '<div style="padding: 6px 14px; font-size: 0.72rem; color: var(--text-muted);">Loading...</div>';
    childrenEl.style.display = '';
    try {
      var data = await apiGet(explorerApiUrl(ctx, 'path=' + encodeURIComponent(dirPath)));
      explorerState.dirCache[dirPath] = data.entries || [];
      childrenEl.innerHTML = '';
      renderExplorerEntries(data.entries || [], childrenEl, dirPath);
    } catch (e) {
      childrenEl.innerHTML = '<div style="padding: 6px 14px; font-size: 0.72rem; color: var(--danger);">Failed to load</div>';
    }
    delete dirEl.dataset.loading;
  } else {
    dirEl.classList.add('collapsed');
    childrenEl.style.display = 'none';
  }
}

function renderExplorerEntries(entries, container, parentPath) {
  var depth = parentPath ? parentPath.split('/').length : 0;
  var pad = 11 + depth * 11;

  entries.forEach(function(entry) {
    if (entry.type === 'dir') {
      var dir = document.createElement('div');
      dir.className = 'file-dir collapsed';
      dir.style.paddingLeft = pad + 'px';
      dir.innerHTML = '<span class="arrow">\u25BC</span> ' + escapeHtml(entry.name) + '/';
      dir.onclick = function(e) { e.stopPropagation(); expandExplorerDir(entry.path, dir); };
      container.appendChild(dir);

      var children = document.createElement('div');
      children.className = 'dir-children';
      children.style.display = 'none';
      container.appendChild(children);
    } else {
      var div = document.createElement('div');
      div.className = 'file-item' + (explorerState.selectedFile === entry.path ? ' active' : '');
      div.style.paddingLeft = (pad + 11) + 'px';
      div.dataset.path = entry.path;
      div.onclick = function() { selectExplorerFile(entry.path); };
      div.innerHTML = '<span>' + escapeHtml(entry.name) + '</span>';
      container.appendChild(div);
    }
  });
}

function renderExplorerLazy() {
  var container = document.getElementById('explorerFileList');
  var header = container.querySelector('.diff-file-list-header');
  var wasMobileOpen = container.classList.contains('mobile-open');
  container.innerHTML = '';
  container.appendChild(header);
  if (wasMobileOpen) container.classList.add('mobile-open');

  var countEl = document.getElementById('explorerCount');
  if (countEl) countEl.textContent = explorerState.totalFiles;
  var badgeEl = document.getElementById('explorerFileCount');
  if (badgeEl) badgeEl.textContent = explorerState.totalFiles + ' files';

  var entries = explorerState.dirCache[''] || [];
  renderExplorerEntries(entries, container, '');
}

var _explorerSearchTimeout = null;

async function filterExplorerFiles(query) {
  explorerState.filter = query.trim().toLowerCase();
  if (_explorerSearchTimeout) clearTimeout(_explorerSearchTimeout);

  if (!explorerState.filter) {
    renderExplorerLazy();
    return;
  }

  _explorerSearchTimeout = setTimeout(async function() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    try {
      var data = await apiGet(explorerApiUrl(ctx, 'search=' + encodeURIComponent(explorerState.filter)));
      var container = document.getElementById('explorerFileList');
      var header = container.querySelector('.diff-file-list-header');
      container.innerHTML = '';
      container.appendChild(header);

      var entries = data.entries || [];
      var countEl = document.getElementById('explorerCount');
      if (countEl) countEl.textContent = entries.length;
      var badgeEl = document.getElementById('explorerFileCount');
      if (badgeEl) badgeEl.textContent = entries.length + ' results';

      entries.forEach(function(entry) {
        var div = document.createElement('div');
        div.className = 'file-item' + (explorerState.selectedFile === entry.path ? ' active' : '');
        div.dataset.path = entry.path;
        div.onclick = function() { selectExplorerFile(entry.path); };
        div.innerHTML = '<span>' + escapeHtml(entry.path) + '</span>';
        container.appendChild(div);
      });
    } catch (e) {
      console.warn('Search failed:', e.message);
    }
  }, 300);
}

var _explorerFileLines = [];

async function selectExplorerFile(path, lineNumber) {
  explorerState.selectedFile = path;
  explorerState.mdMode = 'preview';
  var fileList = document.getElementById('explorerFileList');
  if (fileList) {
    fileList.querySelectorAll('.file-item').forEach(function(el) {
      if (el.dataset.path === path) {
        el.classList.add('active');
      } else {
        el.classList.remove('active');
      }
    });
  }

  var content = document.getElementById('explorerContent');
  content.innerHTML = '<div class="diff-placeholder">' + t('explorer.loading') + '</div>';

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  try {
    var data = await apiReadFile(ctx.projectId, ctx.branch, path);
    _explorerFileLines = data.lines || [];
    renderExplorerContent(path, _explorerFileLines, lineNumber);
  } catch (e) {
    content.innerHTML = '<div class="diff-placeholder">' + t('explorer.failedToLoad', {error: escapeHtml(e.message)}) + '</div>';
  }
}

function isMarkdownFile(path) {
  var ext = path.split('.').pop().toLowerCase();
  return ext === 'md' || ext === 'markdown' || ext === 'mdx';
}

function renderExplorerContent(path, lines, lineNumber) {
  if (_explorerPreviousLspFile && _explorerPreviousLspFile !== path) {
    unregisterLspProviders();
    lspDidCloseDocument(_explorerPreviousLspFile);
    _explorerPreviousLspFile = null;
  }

  var contentEl = document.getElementById('explorerContent');
  var isMd = isMarkdownFile(path);

  var header = document.createElement('div');
  header.className = 'explorer-file-header';
  header.textContent = path;

  if (isMd && typeof marked !== 'undefined') {
    var toggle = document.createElement('div');
    toggle.className = 'toggle-group md-toggle';
    toggle.style.marginLeft = '12px';

    var srcBtn = document.createElement('button');
    srcBtn.className = 'toggle-opt' + (explorerState.mdMode === 'source' ? ' active' : '');
    srcBtn.dataset.mode = 'source';
    srcBtn.textContent = t('buttons.source');
    srcBtn.onclick = function() { setExplorerMdMode('source'); };

    var prevBtn = document.createElement('button');
    prevBtn.className = 'toggle-opt' + (explorerState.mdMode === 'preview' ? ' active' : '');
    prevBtn.dataset.mode = 'preview';
    prevBtn.textContent = t('buttons.preview');
    prevBtn.onclick = function() { setExplorerMdMode('preview'); };

    toggle.appendChild(srcBtn);
    toggle.appendChild(prevBtn);
    header.appendChild(toggle);

    var copyBtn = document.createElement('button');
    copyBtn.className = 'btn btn-sm';
    copyBtn.textContent = t('buttons.copy');
    copyBtn.onclick = function() {
      safeCopyToClipboard(lines.join('\n')).then(function() {
        flashButton(copyBtn, t('actions.copied'));
      });
    };
    header.appendChild(copyBtn);

    if (explorerState.mdMode === 'source') {
      var saveBtn = document.createElement('button');
      saveBtn.className = 'btn btn-sm';
      saveBtn.textContent = t('buttons.save');
      saveBtn.disabled = true;
      saveBtn.onclick = function() { saveExplorerFile(); };
      header.appendChild(saveBtn);
      _explorerSaveBtn = saveBtn;
    } else {
      _explorerSaveBtn = null;
    }
  }

  var lineCount = document.createElement('span');
  lineCount.className = 'explorer-line-count';
  lineCount.textContent = lines.length + ' lines';
  header.appendChild(lineCount);

  if (isMd && typeof marked !== 'undefined' && explorerState.mdMode === 'preview') {
    var parsed = DOMPurify.sanitize(marked.parse(lines.join('\n'), { breaks: true, gfm: true }));
    var tmp = document.createElement('div');
    tmp.innerHTML = parsed;
    tmp.querySelectorAll('code').forEach(function(el) {
      el.innerHTML = el.innerHTML.replace(/&amp;lt;/g, '&lt;').replace(/&amp;gt;/g, '&gt;').replace(/&amp;amp;/g, '&amp;');
    });

    var mdBody = document.createElement('div');
    mdBody.className = 'explorer-file-body md-preview';
    mdBody.innerHTML = tmp.innerHTML;

    contentEl.innerHTML = '';
    contentEl.appendChild(header);
    contentEl.appendChild(mdBody);

    if (typeof hljs !== 'undefined') {
      contentEl.querySelectorAll('pre code').forEach(function(block) { hljs.highlightElement(block); });
    }
  } else {
    disposeEditor();

    var editorContainer = document.createElement('div');
    editorContainer.id = 'monaco-editor-container';
    editorContainer.style.height = '100%';
    editorContainer.style.width = '100%';

    var body = document.createElement('div');
    body.className = 'explorer-file-body monaco-body';
    body.style.height = 'calc(100% - 40px)';
    body.style.padding = '0';
    body.appendChild(editorContainer);

    contentEl.innerHTML = '';
    contentEl.appendChild(header);
    contentEl.appendChild(body);

    var fileContent = lines.join('\n');
    var language = isMd ? 'markdown' : getMonacoLanguage(path);
    var editorReadOnly = !(isMd && explorerState.mdMode === 'source');
    _explorerEditorDirty = false;
    createEditor(editorContainer, fileContent, language, path, editorReadOnly).then(function(editor) {
      lspDidOpenDocument(path, fileContent, language);
      registerLspProviders(editor, path, language);
      _explorerPreviousLspFile = path;
      if (lineNumber) {
        revealLine(lineNumber);
      }
      if (!editorReadOnly) {
        editor.onDidChangeModelContent(function() {
          var isDirty = editor.getValue() !== _explorerFileLines.join('\n');
          if (isDirty !== _explorerEditorDirty) {
            _explorerEditorDirty = isDirty;
            if (_explorerSaveBtn) _explorerSaveBtn.disabled = !isDirty;
          }
        });
      }
    });
  }
}

function setExplorerMdMode(mode) {
  if (mode === 'preview' && explorerState.mdMode === 'source' && window._monacoEditor) {
    var currentContent = window._monacoEditor.getValue();
    _explorerFileLines = currentContent.split('\n');
  }
  explorerState.mdMode = mode;
  if (_explorerFileLines.length > 0 && explorerState.selectedFile) {
    renderExplorerContent(explorerState.selectedFile, _explorerFileLines);
  }
  document.querySelectorAll('.md-toggle .toggle-opt').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
}

function saveExplorerFile() {
  var ctx = getWorkspaceContext();
  if (!ctx || !explorerState.selectedFile || !window._monacoEditor) return;

  var content = window._monacoEditor.getValue();
  if (_explorerSaveBtn) _explorerSaveBtn.disabled = true;

  apiWriteFile(ctx.projectId, ctx.branch, explorerState.selectedFile, content).then(function() {
    _explorerFileLines = content.split('\n');
    _explorerEditorDirty = false;
    showToast(t('messages.fileSaved'));
  }).catch(function(e) {
    if (_explorerSaveBtn) _explorerSaveBtn.disabled = false;
    showToast(t('messages.fileSaveFailed'));
  });
}

// Resize handle for explorer panel
makeResizable('explorerResizeHandle', 'explorerFileList');

document.addEventListener('workspace-reset', function() {
  explorerState.dirCache = {};
  explorerState.selectedFile = null;
  explorerState.totalFiles = 0;
  _explorerFileLines = [];
  _explorerSaveBtn = null;
  _explorerEditorDirty = false;
  if (_explorerPreviousLspFile) {
    unregisterLspProviders();
    lspDidCloseDocument(_explorerPreviousLspFile);
    _explorerPreviousLspFile = null;
  }
  disposeEditor();
});
