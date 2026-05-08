// ═══════════════════════════════════════════════
//  PROPOSALS
// ═══════════════════════════════════════════════
var PROPOSAL_LIST = [];
var _proposalsStatusFilter = 'pending';
var _proposalsTypeFilter = '';
var _proposalSelectedId = null;
var _proposalsInitialized = false;

function loadProposals(filterStatus, filterType) {
  if (typeof filterStatus === 'string') _proposalsStatusFilter = filterStatus;
  if (typeof filterType === 'string') _proposalsTypeFilter = filterType;

  var params = [];
  if (_proposalsStatusFilter) params.push('status=' + encodeURIComponent(_proposalsStatusFilter));
  if (_proposalsTypeFilter) params.push('type=' + encodeURIComponent(_proposalsTypeFilter));
  var url = '/api/proposals' + (params.length ? '?' + params.join('&') : '');

  apiGet(url)
    .then(function(data) {
      PROPOSAL_LIST = Array.isArray(data) ? data : [];
      renderProposalList();
      _refreshProposalsBadge();
    })
    .catch(function(e) {
      showToast('Proposal list failed: ' + (e && e.message));
    });
}

function loadProposalDetail(proposalId) {
  _proposalSelectedId = proposalId;

  document.querySelectorAll('.proposals-row').forEach(function(row) {
    row.classList.toggle('active', row.dataset.pid === String(proposalId));
  });

  var detailEl = document.getElementById('proposalsDetail');
  if (detailEl) detailEl.innerHTML = '<div class="proposals-empty">Loading...</div>';

  apiGet('/api/proposals/' + encodeURIComponent(proposalId))
    .then(function(item) {
      renderProposalDetail(item);
    })
    .catch(function(e) {
      showToast('Failed to load proposal: ' + (e && e.message));
    });
}

function approveProposal(proposalId) {
  if (!confirm('Approve this proposal?')) return;
  apiPost('/api/proposals/' + encodeURIComponent(proposalId) + '/approve', {})
    .then(function(item) {
      showToast('Proposal approved.');
      _replaceProposalInList(item);
      renderProposalList();
      renderProposalDetail(item);
    })
    .catch(function(e) {
      showToast('Approve failed: ' + (e && e.message));
    });
}

function rejectProposal(proposalId, reason) {
  var trimmed = (reason || '').trim();
  if (!trimmed) {
    showToast('Rejection reason is required.');
    return;
  }
  apiPost('/api/proposals/' + encodeURIComponent(proposalId) + '/reject', { reason: trimmed })
    .then(function(item) {
      showToast('Proposal rejected.');
      _replaceProposalInList(item);
      renderProposalList();
      renderProposalDetail(item);
    })
    .catch(function(e) {
      showToast('Reject failed: ' + (e && e.message));
    });
}

function resolveProposal(proposalId) {
  if (!confirm('Mark this proposal as resolved?')) return;
  apiPost('/api/proposals/' + encodeURIComponent(proposalId) + '/resolve', {})
    .then(function(item) {
      showToast('Proposal resolved.');
      _replaceProposalInList(item);
      renderProposalList();
      renderProposalDetail(item);
    })
    .catch(function(e) {
      showToast('Resolve failed: ' + (e && e.message));
    });
}

function _replaceProposalInList(updated) {
  var idx = -1;
  for (var i = 0; i < PROPOSAL_LIST.length; i++) {
    if (PROPOSAL_LIST[i].id === updated.id) { idx = i; break; }
  }
  var matchesStatus = !_proposalsStatusFilter || updated.status === _proposalsStatusFilter;
  var matchesType = !_proposalsTypeFilter || updated.type === _proposalsTypeFilter;
  if (idx >= 0) {
    if (matchesStatus && matchesType) {
      PROPOSAL_LIST[idx] = updated;
    } else {
      PROPOSAL_LIST.splice(idx, 1);
    }
  } else if (matchesStatus && matchesType) {
    PROPOSAL_LIST.unshift(updated);
  }
}

function _proposalStatusBadgeClass(status) {
  if (status === 'pending') return 'badge badge-warning';
  if (status === 'approved') return 'badge badge-success';
  if (status === 'executed') return 'badge badge-success';
  if (status === 'rejected') return 'badge badge-muted';
  if (status === 'failed') return 'badge badge-danger';
  return 'badge';
}

function renderProposalList() {
  var listEl = document.getElementById('proposalsList');
  if (!listEl) return;

  if (PROPOSAL_LIST.length === 0) {
    listEl.innerHTML = '<div class="proposals-empty">No proposals match the current filter.</div>';
    return;
  }

  var rows = PROPOSAL_LIST.map(function(p) {
    var idSafe = escapeHtml(String(p.id));
    var typeSafe = escapeHtml(p.type || '');
    var titleSafe = escapeHtml(p.title || '');
    var status = p.status || 'pending';
    var badgeClass = _proposalStatusBadgeClass(status);
    var created = p.created_at ? new Date(p.created_at).toLocaleString() : '';
    var isActive = String(p.id) === String(_proposalSelectedId) ? ' active' : '';
    return '<tr class="proposals-row' + isActive + '" onclick="loadProposalDetail(' + idSafe + ')" data-pid="' + idSafe + '">' +
      '<td class="proposals-col-id"><span class="proposals-id">#' + idSafe + '</span></td>' +
      '<td class="proposals-col-type"><span class="proposals-type">' + typeSafe + '</span></td>' +
      '<td class="proposals-col-title">' + titleSafe + '</td>' +
      '<td class="proposals-col-status"><span class="' + badgeClass + '">' + escapeHtml(status) + '</span></td>' +
      '<td class="proposals-col-date">' + escapeHtml(created) + '</td>' +
    '</tr>';
  }).join('');

  listEl.innerHTML = '<table class="proposals-table"><thead><tr>' +
    '<th>#</th><th>Type</th><th>Title</th><th>Status</th><th>Created</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function _renderProposalActions(p) {
  if (p.status === 'pending') {
    return '<button class="btn btn-sm btn-primary" onclick="approveProposal(' + p.id + ')" data-i18n="buttons.approve">Approve</button>' +
      '<button class="btn btn-sm btn-danger-outline" onclick="_promptRejectProposal(' + p.id + ')" data-i18n="buttons.reject">Reject</button>';
  }
  if (p.status === 'failed') {
    return '<button class="btn btn-sm btn-outline" onclick="resolveProposal(' + p.id + ')" data-i18n="buttons.resolve">Resolve</button>';
  }
  return '';
}

function _promptRejectProposal(proposalId) {
  var reason = prompt('Reason for rejection:');
  if (reason === null) return;
  rejectProposal(proposalId, reason);
}

function _renderProposalPayload(p) {
  var payload = p.payload || {};
  var hasPayload = false;
  for (var k in payload) {
    if (Object.prototype.hasOwnProperty.call(payload, k)) { hasPayload = true; break; }
  }
  if (!hasPayload) return '';

  var jsonText = '';
  try {
    jsonText = JSON.stringify(payload, null, 2);
  } catch (e) {
    jsonText = String(payload);
  }
  return '<div class="proposals-section-title" data-i18n="proposals.payload">Payload</div>' +
    '<pre class="proposals-payload"><code>' + escapeHtml(jsonText) + '</code></pre>';
}

function renderProposalDetail(p) {
  var detailEl = document.getElementById('proposalsDetail');
  if (!detailEl) return;

  if (!p) {
    detailEl.innerHTML = '<div class="proposals-empty">No content available.</div>';
    return;
  }

  var idSafe = escapeHtml(String(p.id));
  var titleSafe = escapeHtml(p.title || '');
  var typeSafe = escapeHtml(p.type || '');
  var originSafe = escapeHtml(p.origin || '');
  var status = p.status || 'pending';
  var badgeClass = _proposalStatusBadgeClass(status);
  var created = p.created_at ? new Date(p.created_at).toLocaleString() : '';
  var reviewed = p.reviewed_at ? new Date(p.reviewed_at).toLocaleString() : '';

  var bodyHtml = '';
  if (p.body) {
    var rendered = (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined')
      ? DOMPurify.sanitize(marked.parse(p.body))
      : '<pre>' + escapeHtml(p.body) + '</pre>';
    bodyHtml = '<div class="proposals-md-body">' + rendered + '</div>';
  }

  var reasonHtml = p.reason
    ? '<div class="proposals-meta-row"><span class="proposals-meta-label" data-i18n="proposals.reason">Reason:</span> ' + escapeHtml(p.reason) + '</div>'
    : '';

  detailEl.innerHTML =
    '<div class="proposals-detail-header">' +
      '<div class="proposals-detail-title">' +
        '<span class="proposals-detail-id">#' + idSafe + '</span> ' +
        '<span class="proposals-detail-type">' + typeSafe + '</span> ' +
        '<span class="' + badgeClass + '">' + escapeHtml(status) + '</span>' +
      '</div>' +
      '<div class="proposals-detail-actions">' + _renderProposalActions(p) + '</div>' +
    '</div>' +
    '<h3 class="proposals-detail-name">' + titleSafe + '</h3>' +
    '<div class="proposals-meta">' +
      '<div class="proposals-meta-row"><span class="proposals-meta-label" data-i18n="proposals.origin">Origin:</span> ' + originSafe + '</div>' +
      '<div class="proposals-meta-row"><span class="proposals-meta-label" data-i18n="proposals.created">Created:</span> ' + escapeHtml(created) + '</div>' +
      (reviewed ? '<div class="proposals-meta-row"><span class="proposals-meta-label" data-i18n="proposals.reviewed">Reviewed:</span> ' + escapeHtml(reviewed) + '</div>' : '') +
      reasonHtml +
    '</div>' +
    bodyHtml +
    _renderProposalPayload(p);
}

function _refreshProposalsBadge() {
  var badge = document.getElementById('proposalsBadge');
  if (!badge) return;
  if (_proposalsStatusFilter !== 'pending') return;
  var count = PROPOSAL_LIST.length;
  if (count > 0) {
    badge.style.display = 'inline-flex';
    badge.textContent = count > 99 ? '99+' : String(count);
  } else {
    badge.style.display = 'none';
  }
}

function initProposals() {
  if (!_proposalsInitialized) {
    var statusFilter = document.getElementById('proposalsStatusFilter');
    var typeFilter = document.getElementById('proposalsTypeFilter');
    var refreshBtn = document.getElementById('proposalsRefreshBtn');

    if (statusFilter) {
      statusFilter.value = _proposalsStatusFilter;
      statusFilter.onchange = function() {
        loadProposals(statusFilter.value, _proposalsTypeFilter);
      };
    }
    if (typeFilter) {
      typeFilter.value = _proposalsTypeFilter;
      typeFilter.onchange = function() {
        loadProposals(_proposalsStatusFilter, typeFilter.value);
      };
    }
    if (refreshBtn) {
      refreshBtn.onclick = function() { loadProposals(_proposalsStatusFilter, _proposalsTypeFilter); };
    }
    _proposalsInitialized = true;
  }

  loadProposals(_proposalsStatusFilter, _proposalsTypeFilter);
}
