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
    .catch(function(e) { showToast(t('reflection.listFailed', {error: e && e.message})); });
}

function renderReflectionList() {
  var listEl = document.getElementById('reflectionList');
  if (!listEl) return;

  if (REFLECTION_LIST.length === 0) {
    listEl.innerHTML = '<div class="reflection-empty">' + t('reflection.empty') + '</div>';
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
    '<th>' + t('reflection.colNumber') + '</th><th>' + t('reflection.colSummary') + '</th><th>' + t('reflection.colCreated') + '</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function loadReflectionDetail(rid) {
  var ctx = getWorkspaceContext();
  if (!ctx) return;

  document.querySelectorAll('.reflection-row').forEach(function(row) {
    row.classList.toggle('active', row.dataset.rid === String(rid));
  });

  var detailEl = document.getElementById('reflectionDetail');
  if (detailEl) detailEl.innerHTML = '<div class="reflection-loading">' + t('reflection.loading') + '</div>';

  apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/reflections/' + encodeURIComponent(rid))
    .then(function(r) {
      renderReflectionDetail(r);
    })
    .catch(function(e) { showToast(t('reflection.loadFailed', {error: e && e.message})); });
}

function renderReflectionDetail(r) {
  var detailEl = document.getElementById('reflectionDetail');
  if (!detailEl) return;

  var html = '';
  if (r && r.content_md) {
    var rendered = DOMPurify.sanitize(marked.parse(r.content_md));
    html = '<div class="reflection-md-body">' + rendered + '</div>';
  } else {
    html = '<div class="reflection-empty">' + t('reflection.noContent') + '</div>';
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
    btn.textContent = t('reflection.running');
  }

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/reflections', {})
    .then(function(r) {
      if (btn) { btn.disabled = false; btn.textContent = t('buttons.runReflection'); }
      showToast(t('reflection.complete'));
      REFLECTION_LIST.unshift(r);
      renderReflectionList();
      if (r && r.id) loadReflectionDetail(r.id);
      if (r && Array.isArray(r.proposal_ids) && r.proposal_ids.length > 0) {
        showReflectionProposalsBanner(r.proposal_ids.length, ctx.projectId, ctx.branch);
      }
    })
    .catch(function(e) {
      if (btn) { btn.disabled = false; btn.textContent = t('buttons.runReflection'); }
      if (e && e.status === 503) {
        showToast(t('reflection.runLlmNotConfigured'));
      } else if (e && e.status === 409) {
        showToast(t('reflection.runNoSession'));
      } else {
        showToast(t('reflection.runFailed', {error: e && e.message}));
      }
    });
}

function showReflectionProposalsBanner(count, projectId, branch) {
  var detailEl = document.getElementById('reflectionDetail');
  if (!detailEl) return;

  var banner = document.createElement('div');
  banner.className = 'reflection-proposals-banner';
  var noun = count === 1 ? t('reflection.proposalNoun') : t('reflection.proposalsNoun');
  banner.innerHTML = t('reflection.proposalsBanner', {count: count, noun: noun}) +
    '<a href="#" class="reflection-proposals-link">' + t('reflection.proposalsBannerLink') + '</a>';
  banner.querySelector('.reflection-proposals-link').onclick = function(e) {
    e.preventDefault();
    switchTab('proposals');
    EventBus.emit('proposals:filter', { origin: 'reflection', workspace_id: getWorkspaceContext() && getWorkspaceContext().workspaceId });
  };
  detailEl.insertBefore(banner, detailEl.firstChild);
}

function initReflection() {
  var runBtn = document.getElementById('reflectionRunBtn');
  if (runBtn) {
    runBtn.onclick = function() { runReflection(); };
  }
  loadReflections();
}
