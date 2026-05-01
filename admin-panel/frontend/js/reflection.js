// ═══════════════════════════════════════════════
//  REFLECTION
// ═══════════════════════════════════════════════
var REFLECTION_LIST = [];

function loadReflections() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/reflections')
    .then(function(data) {
      REFLECTION_LIST = Array.isArray(data) ? data : [];
      renderReflectionList();
    })
    .catch(function(e) { showToast('Reflection list failed: ' + (e && e.message)); });
}

function renderReflectionList() {
  var listEl = document.getElementById('reflectionList');
  if (!listEl) return;

  if (REFLECTION_LIST.length === 0) {
    listEl.innerHTML = '<div class="reflection-empty">No reflections yet. Run one after completing a task.</div>';
    return;
  }

  var rows = REFLECTION_LIST.map(function(r) {
    var created = r.created_at ? new Date(r.created_at).toLocaleString() : '';
    var summarySafe = escapeHtml(r.summary || '');
    var idSafe = escapeHtml(String(r.id));
    return '<tr class="reflection-row" onclick="loadReflectionDetail(\'' + idSafe + '\')" data-rid="' + idSafe + '">' +
      '<td class="reflection-col-id"><span class="reflection-id">#' + idSafe + '</span></td>' +
      '<td class="reflection-col-summary">' + summarySafe + '</td>' +
      '<td class="reflection-col-date">' + escapeHtml(created) + '</td>' +
    '</tr>';
  }).join('');

  listEl.innerHTML = '<table class="reflection-table"><thead><tr>' +
    '<th>#</th><th>Summary</th><th>Created</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function loadReflectionDetail(rid) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  document.querySelectorAll('.reflection-row').forEach(function(row) {
    row.classList.toggle('active', row.dataset.rid === String(rid));
  });

  var detailEl = document.getElementById('reflectionDetail');
  if (detailEl) detailEl.innerHTML = '<div class="reflection-loading">Loading...</div>';

  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/reflections/' + encodeURIComponent(rid))
    .then(function(r) {
      renderReflectionDetail(r);
    })
    .catch(function(e) { showToast('Failed to load reflection: ' + (e && e.message)); });
}

function renderReflectionDetail(r) {
  var detailEl = document.getElementById('reflectionDetail');
  if (!detailEl) return;

  var html = '';
  if (r && r.content_md) {
    var rendered = DOMPurify.sanitize(marked.parse(r.content_md));
    html = '<div class="reflection-md-body">' + rendered + '</div>';
  } else {
    html = '<div class="reflection-empty">No content available.</div>';
  }

  detailEl.innerHTML = html;

  detailEl.querySelectorAll('pre code').forEach(function(block) {
    if (typeof hljs !== 'undefined') hljs.highlightElement(block);
  });
}

function runReflection() {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  var btn = document.getElementById('reflectionRunBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
  }

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/reflections', {})
    .then(function(r) {
      if (btn) { btn.disabled = false; btn.textContent = 'Run Reflection'; }
      showToast('Reflection complete.');
      REFLECTION_LIST.unshift(r);
      renderReflectionList();
      if (r && r.id) loadReflectionDetail(r.id);
    })
    .catch(function(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Run Reflection'; }
      if (e && e.status === 503) {
        showToast('LLM not configured — set up an AI provider in Configuration before running a reflection.');
      } else if (e && e.status === 409) {
        showToast('No active session found. Start a Claude session before running a reflection.');
      } else {
        showToast('Reflection failed: ' + (e && e.message));
      }
    });
}

function initReflection() {
  var runBtn = document.getElementById('reflectionRunBtn');
  if (runBtn) {
    runBtn.onclick = function() { runReflection(); };
  }
  loadReflections();
}
