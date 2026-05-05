// ═══════════════════════════════════════════════
//  MEMORY
// ═══════════════════════════════════════════════
var MEMORY_LIST = [];
var _memoryScopeKind = 'project';
var _memorySelectedId = null;

function _memoryBaseUrl() {
  var ctx = getWorkspaceContext();
  if (!ctx) return null;
  return '/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/memory';
}

function loadMemoryList(scopeKind) {
  _memoryScopeKind = scopeKind || _memoryScopeKind;
  var base = _memoryBaseUrl();
  if (!base) return;

  var ctx = getWorkspaceContext();
  var scope_filter = encodeURIComponent(JSON.stringify({
    kind: _memoryScopeKind,
    project_id: ctx ? ctx.projectId : null
  }));
  var url = base + '?scope_filter=' + scope_filter;

  apiGet(url)
    .then(function(data) {
      MEMORY_LIST = Array.isArray(data) ? data : (data.items || []);
      renderMemoryList();
    })
    .catch(function(e) {
      if (e && e.status === 503) {
        showToast(t('memory.noProviderTitle') + ' ' + t('memory.noProviderHint'));
      } else {
        showToast('Memory list failed: ' + (e && e.message));
      }
    });
}

function searchMemory(query, scopeKind) {
  var base = _memoryBaseUrl();
  if (!base) return;

  var scope = scopeKind || _memoryScopeKind;
  var ctx = getWorkspaceContext();
  var body = {
    query: query && query.trim() ? query.trim() : '',
    scope_filter: [{
      kind: scope,
      project_id: ctx ? ctx.projectId : null
    }],
    limit: 20
  };

  apiPost(base + '/search', body)
    .then(function(data) {
      MEMORY_LIST = Array.isArray(data) ? data : (data.items || []);
      renderMemoryList();
    })
    .catch(function(e) {
      if (e && e.status === 503) {
        showToast(t('memory.noProviderTitle') + ' ' + t('memory.noProviderHint'));
      } else {
        showToast('Memory search failed: ' + (e && e.message));
      }
    });
}

function loadMemoryDetail(memoryId) {
  var base = _memoryBaseUrl();
  if (!base) return;

  _memorySelectedId = memoryId;

  document.querySelectorAll('.memory-row').forEach(function(row) {
    row.classList.toggle('active', row.dataset.mid === String(memoryId));
  });

  var detailEl = document.getElementById('memoryDetail');
  if (detailEl) detailEl.innerHTML = '<div class="memory-empty">Loading...</div>';

  apiGet(base + '/' + encodeURIComponent(memoryId))
    .then(function(item) {
      renderMemoryDetail(item);
    })
    .catch(function(e) {
      if (e && e.status === 503) {
        showToast(t('memory.noProviderTitle') + ' ' + t('memory.noProviderHint'));
      } else {
        showToast('Failed to load memory: ' + (e && e.message));
      }
    });
}

function deleteMemory(memoryId) {
  var base = _memoryBaseUrl();
  if (!base) return;

  if (!confirm('Delete this memory entry?')) return;

  apiDelete(base + '/' + encodeURIComponent(memoryId))
    .then(function() {
      showToast('Memory deleted.');
      _memorySelectedId = null;
      var detailEl = document.getElementById('memoryDetail');
      if (detailEl) detailEl.innerHTML = '<div class="memory-empty">Select a memory entry to view details.</div>';
      loadMemoryList(_memoryScopeKind);
    })
    .catch(function(e) {
      if (e && e.status === 503) {
        showToast(t('memory.noProviderTitle') + ' ' + t('memory.noProviderHint'));
      } else {
        showToast('Delete failed: ' + (e && e.message));
      }
    });
}

function renderMemoryList() {
  var listEl = document.getElementById('memoryList');
  if (!listEl) return;

  if (MEMORY_LIST.length === 0) {
    listEl.innerHTML = '<div class="memory-empty">No memory entries found.</div>';
    return;
  }

  var rows = MEMORY_LIST.map(function(item) {
    var mid = escapeHtml(String(item.memory_id || item.id || ''));
    var snippet = escapeHtml((item.content || '').substring(0, 120));
    var tags = (item.tags || []).map(function(t) {
      return '<span class="memory-tag">' + escapeHtml(t) + '</span>';
    }).join('');
    var created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
    var isActive = String(item.memory_id || item.id) === String(_memorySelectedId) ? ' active' : '';
    return '<tr class="memory-row' + isActive + '" onclick="loadMemoryDetail(\'' + mid + '\')" data-mid="' + mid + '">' +
      '<td class="memory-col-id"><span class="memory-id">' + mid + '</span></td>' +
      '<td class="memory-col-content"><div class="memory-snippet">' + snippet + '</div>' +
        (tags ? '<div class="memory-tags">' + tags + '</div>' : '') +
      '</td>' +
      '<td class="memory-col-date">' + escapeHtml(created) + '</td>' +
    '</tr>';
  }).join('');

  listEl.innerHTML = '<table class="memory-table"><thead><tr>' +
    '<th>ID</th><th>Content</th><th>Created</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function renderMemoryDetail(item) {
  var detailEl = document.getElementById('memoryDetail');
  if (!detailEl) return;

  if (!item) {
    detailEl.innerHTML = '<div class="memory-empty">No content available.</div>';
    return;
  }

  var mid = escapeHtml(String(item.memory_id || item.id || ''));
  var content = escapeHtml(item.content || '');
  var scope = escapeHtml(item.scope_kind || '');
  var scopeId = escapeHtml(item.scope_id || '');
  var created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
  var tags = (item.tags || []).map(function(t) {
    return '<span class="memory-tag">' + escapeHtml(t) + '</span>';
  }).join('');

  detailEl.innerHTML =
    '<div class="memory-detail-header">' +
      '<span class="memory-detail-id">Memory #' + mid + '</span>' +
      '<button class="btn btn-sm btn-danger-outline" onclick="deleteMemory(\'' + mid + '\')">Delete</button>' +
    '</div>' +
    '<div class="memory-detail-meta">' +
      '<span class="memory-meta-item"><span class="memory-meta-label">Scope:</span> ' + scope + (scopeId ? ' / ' + scopeId : '') + '</span>' +
      '<span class="memory-meta-item"><span class="memory-meta-label">Created:</span> ' + escapeHtml(created) + '</span>' +
    '</div>' +
    (tags ? '<div class="memory-detail-tags">' + tags + '</div>' : '') +
    '<div class="memory-detail-content"><pre>' + content + '</pre></div>';
}

function _setMemoryScopeTab(kind) {
  _memoryScopeKind = kind;
  document.querySelectorAll('.memory-scope-tab').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.scope === kind);
  });
  var detailEl = document.getElementById('memoryDetail');
  if (detailEl) detailEl.innerHTML = '<div class="memory-empty">Select a memory entry to view details.</div>';
  _memorySelectedId = null;
  loadMemoryList(kind);
}

function initMemory() {
  var projectTab = document.querySelector('.memory-scope-tab[data-scope="project"]');
  var ticketTab = document.querySelector('.memory-scope-tab[data-scope="ticket"]');
  if (projectTab) projectTab.onclick = function() { _setMemoryScopeTab('project'); };
  if (ticketTab) ticketTab.onclick = function() { _setMemoryScopeTab('ticket'); };

  var searchInput = document.getElementById('memorySearchInput');
  var searchBtn = document.getElementById('memorySearchBtn');
  if (searchBtn) {
    searchBtn.onclick = function() {
      searchMemory(searchInput ? searchInput.value : '', _memoryScopeKind);
    };
  }
  if (searchInput) {
    searchInput.onkeydown = function(e) {
      if (e.key === 'Enter') { searchMemory(searchInput.value, _memoryScopeKind); }
    };
  }

  _setMemoryScopeTab(_memoryScopeKind);
}
