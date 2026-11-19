// ═══════════════════════════════════════════════
//  CONTEXT TAB
// ═══════════════════════════════════════════════
var CONTEXT_DATA = AppState.context;

function renderContext() {
  var idInput = document.getElementById('contextTicketId');
  var nameInput = document.getElementById('contextTicketName');
  var textArea = document.getElementById('contextText');

  if (idInput) idInput.value = CONTEXT_DATA.ticket_id || LOCK_DATA.branch || '';
  if (nameInput) nameInput.value = CONTEXT_DATA.ticket_name || '';
  if (textArea) textArea.value = CONTEXT_DATA.context || '';

  renderContextRefs();
  renderContextRaw();
}

function renderContextRaw() {
  var pre = document.getElementById('contextRaw');
  if (pre) {
    pre.textContent = JSON.stringify(CONTEXT_DATA, null, 2);
  }
}

function saveContext() {
  var nameInput = document.getElementById('contextTicketName');
  var textArea = document.getElementById('contextText');

  CONTEXT_DATA.ticket_name = nameInput ? nameInput.value : '';
  CONTEXT_DATA.context = textArea ? textArea.value : '';

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiPut('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context', {
    ticket_name: CONTEXT_DATA.ticket_name,
    context: CONTEXT_DATA.context,
    refs: CONTEXT_DATA.refs || []
  }).then(function() {
    renderContextRaw();
    showToast(t('messages.contextSaved'));
  }).catch(function(e) {
    showToast(t('messages.failedToSave', {error: e.message}));
  });
}

function resolveDiscussion(discussionId, unresolve) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiPut('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context/discussions/' + discussionId, {
    status: unresolve ? 'open' : 'resolved'
  }).then(function() {
    var d = CONTEXT_DATA.discussions.find(function(d) { return d.id === discussionId; });
    if (d) d.status = unresolve ? 'open' : 'resolved';
    renderContextRaw();
    EventBus.emit('discussions:changed');
    showToast(t('messages.discussionResolved'));
  }).catch(function(e) {
    showToast(t('messages.failedToResolve', {error: e.message}));
  });
}

function refreshContext() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;
  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context')
    .then(function(data) {
      if (data) {
        AppState.context = data;
        CONTEXT_DATA = AppState.context;
        renderContext();
        EventBus.emit('context:refreshed', data);
      }
    });
}

function renderContextRefs() {
  var list = document.getElementById('contextRefsList');
  if (!list) return;
  var refs = CONTEXT_DATA.refs || [];
  list.innerHTML = refs.map(function(ref, i) {
    var icon = ref.endsWith('/') ? '📁' : '📄';
    return '<span class="ref-chip">' + icon + ' ' + escapeHtml(ref) + '<span class="ref-remove" onclick="removeContextRef(' + i + ')">&times;</span></span>';
  }).join('');
}

var _refSearchTimeout = null;

function searchContextRefs(query) {
  var dropdown = document.getElementById('contextRefDropdown');
  clearTimeout(_refSearchTimeout);
  if (!query || query.length < 2) {
    dropdown.style.display = 'none';
    return;
  }
  _refSearchTimeout = setTimeout(function() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/search-paths?q=' + encodeURIComponent(query))
      .then(function(data) {
        if (!data || !data.results || data.results.length === 0) {
          dropdown.style.display = 'none';
          return;
        }
        var existing = {};
        (CONTEXT_DATA.refs || []).forEach(function(r) { existing[r] = true; });
        var filtered = data.results.filter(function(r) { return !existing[r]; });
        if (filtered.length === 0) {
          dropdown.style.display = 'none';
          return;
        }
        dropdown.innerHTML = filtered.map(function(r) {
          var icon = r.endsWith('/') ? '📁' : '📄';
          return '<div class="ref-dropdown-item" onclick="addContextRef(\'' + r.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')"><span class="ref-icon">' + icon + '</span>' + escapeHtml(r) + '</div>';
        }).join('');
        dropdown.style.display = 'block';
      }).catch(function() {
        dropdown.style.display = 'none';
      });
  }, 200);
}

function addContextRef(path) {
  if (!CONTEXT_DATA.refs) CONTEXT_DATA.refs = [];
  if (!CONTEXT_DATA.refs.includes(path)) {
    CONTEXT_DATA.refs.push(path);
    renderContextRefs();
    renderContextRaw();
  }
  var search = document.getElementById('contextRefSearch');
  var dropdown = document.getElementById('contextRefDropdown');
  if (search) search.value = '';
  if (dropdown) dropdown.style.display = 'none';
}

function addManualContextRef(path) {
    path = path.trim();
    if (!path) return;
    if (CONTEXT_DATA.refs.includes(path)) return;
    CONTEXT_DATA.refs.push(path);
    renderContextRefs();
    renderContextRaw();
    document.getElementById('contextRefSearch').value = '';
    document.getElementById('contextRefDropdown').style.display = 'none';
}

function removeContextRef(index) {
  if (!CONTEXT_DATA.refs) return;
  CONTEXT_DATA.refs.splice(index, 1);
  renderContextRefs();
  renderContextRaw();
}

document.addEventListener('click', function(e) {
  var dropdown = document.getElementById('contextRefDropdown');
  var search = document.getElementById('contextRefSearch');
  if (dropdown && search && !search.contains(e.target) && !dropdown.contains(e.target)) {
    dropdown.style.display = 'none';
  }
});

