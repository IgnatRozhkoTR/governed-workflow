// ═══════════════════════════════════════════════
//  SCRATCHPADS (agent-authored markdown notes, per repo)
// ═══════════════════════════════════════════════

var spState = {
  sections: [],                 // [{repo: string|null, label: string, files: [...]}]
  isMultiRepo: false,
  selectedRepo: null,
  selectedName: null,
  mode: 'preview',               // 'preview' | 'source'
  content: '',
  updatedAt: null
};
var _spSaveBtn = null;

async function loadScratchpads() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  spState.isMultiRepo = LOCK_DATA.project_type === 'multi';
  spState.sections = [];

  try {
    var rootData = await apiGetScratchpads(ctx.projectId, ctx.branch);
    spState.sections.push({ repo: null, label: t('scratchpads.rootLabel'), files: rootData.files || [] });
  } catch (e) {
    console.warn('Failed to load scratchpads:', e.message);
    spState.sections.push({ repo: null, label: t('scratchpads.rootLabel'), files: [] });
  }

  if (spState.isMultiRepo) {
    try {
      var reposData = await apiGetRepos(ctx.projectId, ctx.branch);
      var repos = reposData.repos || [];
      for (var i = 0; i < repos.length; i++) {
        var repo = repos[i];
        try {
          var repoData = await apiGetScratchpads(ctx.projectId, ctx.branch, repo.path);
          spState.sections.push({ repo: repo.path, label: repo.name, files: repoData.files || [] });
        } catch (e) {
          spState.sections.push({ repo: repo.path, label: repo.name, files: [] });
        }
      }
    } catch (e) {
      console.warn('Failed to load scratchpad repos:', e.message);
    }
  }

  renderScratchpadSections();
}

function _spTotalFileCount() {
  return spState.sections.reduce(function(sum, section) { return sum + section.files.length; }, 0);
}

function _spBuildFileItem(section, file) {
  var isActive = spState.selectedRepo === section.repo && spState.selectedName === file.name;
  var div = document.createElement('div');
  div.className = 'file-item sp-file-item' + (isActive ? ' active' : '');
  div.dataset.repo = section.repo || '';
  div.dataset.name = file.name;
  div.onclick = function() { selectScratchpad(section.repo, file.name); };
  div.innerHTML =
    '<span class="sp-file-title">' + escapeHtml(file.title || file.name) + '</span>' +
    '<span class="sp-file-meta">' + formatRelativeDate(file.updated_at) + '</span>';
  return div;
}

function _spAppendSection(container, section) {
  if (spState.isMultiRepo) {
    var sectionHeader = document.createElement('div');
    sectionHeader.className = 'sp-section-header';
    sectionHeader.textContent = section.label;
    container.appendChild(sectionHeader);
  }

  if (!section.files.length) {
    var empty = document.createElement('div');
    empty.className = 'sp-empty-section';
    empty.textContent = t('scratchpads.empty');
    container.appendChild(empty);
    return;
  }

  section.files.forEach(function(file) {
    container.appendChild(_spBuildFileItem(section, file));
  });
}

function renderScratchpadSections() {
  var container = document.getElementById('scratchpadsList');
  if (!container) return;
  var header = container.querySelector('.diff-file-list-header');
  container.innerHTML = '';
  container.appendChild(header);

  spState.sections.forEach(function(section) { _spAppendSection(container, section); });

  var total = _spTotalFileCount();
  var countEl = document.getElementById('scratchpadsCount');
  if (countEl) countEl.textContent = total;
  var badgeEl = document.getElementById('scratchpadsFileCount');
  if (badgeEl) badgeEl.textContent = total + ' files';
}

function _spExtractTitle(content, fallbackName) {
  var lines = (content || '').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (line.indexOf('# ') === 0) return line.slice(2).trim();
  }
  return fallbackName;
}

async function selectScratchpad(repo, name) {
  spState.selectedRepo = repo || null;
  spState.selectedName = name;
  spState.mode = 'preview';

  document.querySelectorAll('#scratchpadsList .sp-file-item').forEach(function(el) {
    var elRepo = el.dataset.repo || null;
    el.classList.toggle('active', elRepo === (repo || null) && el.dataset.name === name);
  });

  var content = document.getElementById('scratchpadsContent');
  content.innerHTML = '<div class="diff-placeholder">' + t('explorer.loading') + '</div>';

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  try {
    var data = await apiGetScratchpadContent(ctx.projectId, ctx.branch, name, repo);
    spState.content = data.content || '';
    spState.updatedAt = data.updated_at || null;
    renderScratchpadContent();
  } catch (e) {
    content.innerHTML = '<div class="diff-placeholder">' + t('explorer.failedToLoad', {error: escapeHtml(e.message)}) + '</div>';
  }
}

function renderScratchpadContent() {
  var contentEl = document.getElementById('scratchpadsContent');
  if (!contentEl || !spState.selectedName) return;

  var header = document.createElement('div');
  header.className = 'explorer-file-header';
  header.textContent = spState.selectedName;

  var toggle = document.createElement('div');
  toggle.className = 'toggle-group md-toggle';
  toggle.style.marginLeft = '12px';

  var srcBtn = document.createElement('button');
  srcBtn.className = 'toggle-opt' + (spState.mode === 'source' ? ' active' : '');
  srcBtn.dataset.mode = 'source';
  srcBtn.textContent = t('buttons.source');
  srcBtn.onclick = function() { setScratchpadMode('source'); };

  var prevBtn = document.createElement('button');
  prevBtn.className = 'toggle-opt' + (spState.mode === 'preview' ? ' active' : '');
  prevBtn.dataset.mode = 'preview';
  prevBtn.textContent = t('buttons.preview');
  prevBtn.onclick = function() { setScratchpadMode('preview'); };

  toggle.appendChild(srcBtn);
  toggle.appendChild(prevBtn);
  header.appendChild(toggle);

  var copyBtn = document.createElement('button');
  copyBtn.className = 'btn btn-sm';
  copyBtn.textContent = t('buttons.copy');
  copyBtn.onclick = function() {
    var textarea = document.querySelector('#scratchpadsContent .sp-source-editor');
    var text = (textarea && textarea.value !== spState.content) ? textarea.value : spState.content;
    safeCopyToClipboard(text).then(function() {
      flashButton(copyBtn, t('actions.copied'));
    });
  };
  header.appendChild(copyBtn);

  if (spState.mode === 'source') {
    var saveBtn = document.createElement('button');
    saveBtn.className = 'btn btn-sm';
    saveBtn.textContent = t('buttons.save');
    saveBtn.disabled = true;
    saveBtn.onclick = function() { saveScratchpad(); };
    header.appendChild(saveBtn);
    _spSaveBtn = saveBtn;
  } else {
    _spSaveBtn = null;
  }

  if (spState.updatedAt) {
    var updated = document.createElement('span');
    updated.className = 'explorer-line-count';
    updated.textContent = formatRelativeDate(spState.updatedAt);
    header.appendChild(updated);
  }

  contentEl.innerHTML = '';
  contentEl.appendChild(header);

  if (spState.mode === 'preview') {
    var parsed = DOMPurify.sanitize(marked.parse(spState.content, { breaks: true, gfm: true }));
    var tmp = document.createElement('div');
    tmp.innerHTML = parsed;
    tmp.querySelectorAll('code').forEach(function(el) {
      el.innerHTML = el.innerHTML.replace(/&amp;lt;/g, '&lt;').replace(/&amp;gt;/g, '&gt;').replace(/&amp;amp;/g, '&amp;');
    });

    var mdBody = document.createElement('div');
    mdBody.className = 'explorer-file-body md-preview';
    mdBody.innerHTML = tmp.innerHTML;
    mdBody.tabIndex = -1;
    mdBody.addEventListener('keydown', function(e) {
      var isCopyShortcut = (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.key === 'c' || e.key === 'C');
      if (!isCopyShortcut || window.getSelection().toString() !== '') return;
      e.preventDefault();
      safeCopyToClipboard(spState.content).then(function() {
        flashButton(copyBtn, t('actions.copied'));
      });
    });
    contentEl.appendChild(mdBody);
    mdBody.focus({ preventScroll: true });

    if (typeof hljs !== 'undefined') {
      contentEl.querySelectorAll('pre code').forEach(function(block) { hljs.highlightElement(block); });
    }
    renderMermaidBlocks(mdBody);
  } else {
    var textarea = document.createElement('textarea');
    textarea.className = 'context-textarea sp-source-editor';
    textarea.value = spState.content;
    textarea.oninput = function() {
      if (_spSaveBtn) _spSaveBtn.disabled = textarea.value === spState.content;
    };
    contentEl.appendChild(textarea);
  }
}

function setScratchpadMode(mode) {
  if (mode === 'preview' && spState.mode === 'source') {
    var textarea = document.querySelector('#scratchpadsContent .sp-source-editor');
    if (textarea) spState.content = textarea.value;
  }
  spState.mode = mode;
  renderScratchpadContent();
}

function saveScratchpad() {
  var ctx = getWorkspaceContext();
  var textarea = document.querySelector('#scratchpadsContent .sp-source-editor');
  if (!ctx || !spState.selectedName || !textarea) return;

  var content = textarea.value;
  if (_spSaveBtn) _spSaveBtn.disabled = true;

  apiSaveScratchpadContent(ctx.projectId, ctx.branch, spState.selectedName, content, spState.selectedRepo)
    .then(function(result) {
      spState.content = content;
      spState.updatedAt = result.updated_at || spState.updatedAt;
      _spUpdateFileEntry(spState.selectedRepo, spState.selectedName, content, spState.updatedAt);
      renderScratchpadSections();
      renderScratchpadContent();
      showToast(t('messages.fileSaved'));
    })
    .catch(function(e) {
      if (_spSaveBtn) _spSaveBtn.disabled = false;
      showToast(t('messages.fileSaveFailed'));
    });
}

function _spUpdateFileEntry(repo, name, content, updatedAt) {
  var section = spState.sections.find(function(s) { return s.repo === (repo || null); });
  if (!section) return;
  var file = section.files.find(function(f) { return f.name === name; });
  if (!file) return;
  file.title = _spExtractTitle(content, name);
  file.updated_at = updatedAt;
  section.files.sort(function(a, b) { return new Date(b.updated_at) - new Date(a.updated_at); });
}

// Resize handle for scratchpads panel
makeResizable('scratchpadsResizeHandle', 'scratchpadsList');

document.addEventListener('workspace-reset', function() {
  spState.sections = [];
  spState.selectedRepo = null;
  spState.selectedName = null;
  spState.mode = 'preview';
  spState.content = '';
  spState.updatedAt = null;
  _spSaveBtn = null;
});
