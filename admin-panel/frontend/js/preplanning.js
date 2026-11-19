// ═══════════════════════════════════════════════
//  PRE-PLANNING TAB
// ═══════════════════════════════════════════════

function renderPreplanning() {
  _attachDiscussionSubmitKey();
  renderPPResearchSummaries();
  renderPPImpactAnalysis();
  renderPPDiscussions();
  renderPPGateActions();
}

function _attachDiscussionSubmitKey() {
  var input = document.getElementById('ppNewDiscussionInput');
  if (!input || input.dataset.submitKey) return;
  input.dataset.submitKey = '1';
  attachSubmitKey(input, addPPDiscussion);
}

// ═══════════════════════════════════════════════
//  RESEARCH SUMMARIES
// ═══════════════════════════════════════════════

function navigateToResearchEntryById(entryId) {
  if (!RESEARCH_DATA) return;
  for (var i = 0; i < RESEARCH_DATA.length; i++) {
    if (RESEARCH_DATA[i].id === entryId) {
      navigateToResearchEntry(RESEARCH_DATA[i]);
      return;
    }
  }
}

function renderPPResearchSummaries() {
  var container = document.getElementById('ppResearchList');
  if (!container) return;

  if (!RESEARCH_DATA || RESEARCH_DATA.length === 0) {
    morphInnerHTML(container, '<div class="empty">' + t('preplanning.noResearch') + '</div>');
    _renderPPResearchTally();
    return;
  }

  var html = RESEARCH_DATA.map(function(entry) {
    var topicName = entry.topic || t('research.untitledResearch');
    var summary = entry.summary || '';
    var proven = entry.proven;
    var badgeClass = proven === 1 ? 'ok' : proven === -1 ? 'bad' : 'warn';
    var badgeText = proven === 1 ? t('badges.verified') : proven === -1 ? t('badges.rejected') : t('badges.pending');

    var bodyHtml = '<div class="grow pp-research-card-body" onclick="if(!event.target.closest(\'.pp-comment-btn,.pp-inline-comment-form\'))navigateToResearchEntryById(' + entry.id + ')">' +
      '<div class="ti pp-research-topic">' + escapeHtml(topicName) + '</div>' +
      (summary ? '<div class="sm dim pp-research-summary">' + escapeHtml(summary) + '</div>' : '') +
      '</div>';

    var actionsHtml = '<div class="hs pp-research-actions">' +
      '<span class="pill ' + badgeClass + '">' + badgeText + '</span>' +
      '<button class="btn ic xs pp-comment-btn" onclick="event.stopPropagation(); togglePPInlineComment(this, \'research\', ' + entry.id + ')" title="' + t('comments.addComment') + '">' + cpIcon('comment', 14) + '</button>' +
      '</div>';

    return '<div class="row top pp-research-card" id="pp-research-card-' + entry.id + '" data-entry-id="' + entry.id + '">' +
      bodyHtml + actionsHtml +
      '</div>';
  }).join('');

  morphInnerHTML(container, html);
  _renderPPResearchTally();
}

function _renderPPResearchTally() {
  var tally = document.getElementById('ppResearchTally');
  if (!tally) return;
  var total = (RESEARCH_DATA || []).length;
  var verified = (RESEARCH_DATA || []).filter(function(e) { return e.proven === 1; }).length;
  var rejected = (RESEARCH_DATA || []).filter(function(e) { return e.proven === -1; }).length;
  tally.textContent = !total ? '' : rejected > 0
    ? t('research.verifiedRejectedCount', {verified: verified, total: total, rejected: rejected})
    : t('research.verifiedCount', {verified: verified, total: total});
}

async function navigateToResearchEntry(entry) {
  await switchTab('research');
  var groups = document.querySelectorAll('.research-group');
  groups.forEach(function(g) {
    var titleEl = g.querySelector('.research-group-title');
    if (titleEl && titleEl.textContent === (entry.topic || '')) {
      g.classList.remove('collapsed');
      g.scrollIntoView({ behavior: 'smooth', block: 'center' });
      g.style.outline = '2px solid var(--accent)';
      setTimeout(function() { g.style.outline = ''; }, 3000);
    }
  });
}

// ═══════════════════════════════════════════════
//  IMPACT ANALYSIS
// ═══════════════════════════════════════════════

function renderPPImpactAnalysis() {
  var container = document.getElementById('ppImpactContent');
  if (!container) return;

  var data = AppState.impactAnalysis;
  if (!data) {
    morphInnerHTML(container, '<div class="empty">' + t('preplanning.noImpactAnalysis') + '</div>');
    return;
  }

  var sections = [
    { key: 'affected_flows', label: t('impact.affectedFlows') },
    { key: 'api_changes', label: t('impact.apiChanges') },
    { key: 'data_flow_changes', label: t('impact.dataFlowChanges') },
    { key: 'external_dependencies', label: t('impact.externalDeps') },
    { key: 'ticket_gaps', label: t('impact.ticketGaps') },
    { key: 'open_questions', label: t('impact.openQuestions') },
  ];

  var parts = [];
  sections.forEach(function(s) {
    var text = data[s.key];
    if (!text) return;
    parts.push(
      '<div class="inset pp-impact-section" id="pp-impact-section-' + s.key + '" data-key="' + s.key + '">' +
        '<div class="hs between pp-impact-label">' +
          '<span class="cap">' + s.label + '</span>' +
          '<button class="btn ic xs pp-comment-btn" onclick="togglePPInlineComment(this, \'impact\', \'' + s.key + '\')" title="' + t('comments.addComment') + '">' + cpIcon('comment', 14) + '</button>' +
        '</div>' +
        '<div class="pp-impact-text">' + (typeof marked !== 'undefined' ? DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true })) : escapeHtml(text)) + '</div>' +
      '</div>'
    );
  });

  if (parts.length === 0) {
    morphInnerHTML(container, '<div class="empty">' + t('preplanning.noImpactAnalysis') + '</div>');
    return;
  }

  morphInnerHTML(container, '<div class="pp-impact-grid">' + parts.join('') + '</div>');
  renderMermaidBlocks(container);
}

// ═══════════════════════════════════════════════
//  DISCUSSIONS
// ═══════════════════════════════════════════════

var ppShowResolved = false;
var ppShowProven = false;

function togglePPResolved() {
  ppShowResolved = !ppShowResolved;
  var btn = document.getElementById('ppToggleResolved');
  if (btn) btn.textContent = ppShowResolved ? t('discussions.hideResolved') : t('discussions.showResolved');
  if (btn) btn.classList.toggle('on', ppShowResolved);
  renderPPDiscussions();
}

function togglePPProven() {
  ppShowProven = !ppShowProven;
  var btn = document.getElementById('ppToggleProven');
  if (btn) btn.textContent = ppShowProven ? t('discussions.hideProven') : t('discussions.showProven');
  if (btn) btn.classList.toggle('on', ppShowProven);
  renderPPDiscussions();
}

function isResearchProven(discussionId) {
  if (!RESEARCH_DATA) return false;
  for (var i = 0; i < RESEARCH_DATA.length; i++) {
    if (RESEARCH_DATA[i].discussion_id === discussionId) {
      return RESEARCH_DATA[i].proven === 1;
    }
  }
  return false;
}

function renderPPDiscussions() {
  var container = document.getElementById('ppDiscussionsList');
  if (!container) return;

  var discussions = CONTEXT_DATA.discussions || [];

  var badge = document.getElementById('ppDiscussionsBadge');
  if (badge) {
    var openCount = discussions.filter(function(d) { return d.status === 'open'; }).length;
    badge.textContent = openCount > 0 ? openCount : discussions.length;
    badge.className = 'pill ' + (openCount > 0 ? 'warn' : 'ok');
  }

  var researchBadge = document.getElementById('ppResearchDiscBadge');
  if (researchBadge) {
    var researchPending = discussions.filter(function(d) { return d.type === 'research' && !isResearchProven(d.id); }).length;
    if (researchPending > 0) {
      researchBadge.textContent = t('badges.researchCount', {count: researchPending});
      researchBadge.style.display = '';
    } else {
      researchBadge.style.display = 'none';
    }
  }

  if (discussions.length === 0) {
    morphInnerHTML(container, '<div class="empty">' + t('discussions.noItems') + '</div>');
    return;
  }

  var sorted = discussions.slice().sort(function(a, b) {
    if (a.status === 'open' && b.status !== 'open') return -1;
    if (a.status !== 'open' && b.status === 'open') return 1;
    return 0;
  });

  var parts = [];
  sorted.forEach(function(d) {
    var isResearch = d.type === 'research';
    var isResolved = d.status === 'resolved';
    var proven = isResearch ? isResearchProven(d.id) : false;

    if (isResearch && proven && !ppShowProven) return;
    if (!isResearch && isResolved && !ppShowResolved) return;

    var author = d.author || 'user';
    var isAgent = author === 'agent';
    var typeLabel = isResearch ? t('badges.research') : t('discussionType.general');
    var statusLabel = isResearch ? (proven ? t('badges.verified') : t('badges.pending')) : (isResolved ? t('badges.resolved') : t('badges.open'));

    var resolveBtn = isResolved
      ? '<button class="btn xs" onclick="resolveDiscussion(' + d.id + ', true)">' + t('buttons.unresolve') + '</button>'
      : '<button class="btn xs" onclick="resolveDiscussion(' + d.id + ')">' + t('buttons.resolve') + '</button>';

    var repliesHtml = (d.replies || []).map(function(reply) {
      var replyAuthor = reply.author === 'agent' ? t('author.agent') : t('author.user');
      return '<div class="pp-reply"><span class="cap">' + escapeHtml(replyAuthor) + '</span> ' + escapeHtml(reply.text) + '</div>';
    }).join('');

    var replyFormHtml = isResolved ? '' :
      '<div class="hs pp-reply-form">' +
        '<input type="text" class="inp" id="ppReplyInput' + d.id + '" placeholder="' + t('placeholders.reply') + '" onkeydown="if(event.key===\'Enter\'){event.preventDefault();ppReplyToDiscussion(' + d.id + ');}">' +
        '<button class="btn xs" onclick="ppReplyToDiscussion(' + d.id + ')">' + t('buttons.reply') + '</button>' +
      '</div>';

    parts.push(
      '<div class="cmt pp-discussion-item' + (isResolved || proven ? ' pp-resolved' : '') + '" id="pp-discussion-' + d.id + '" data-discussion-id="' + d.id + '">' +
        '<span class="av ' + (isAgent ? 'ag' : '') + '">' + escapeHtml(isAgent ? 'A' : 'I') + '</span>' +
        '<div class="grow vs g4">' +
          '<div class="hs wrap"><b>' + escapeHtml(isAgent ? t('author.agent') : t('author.user')) + '</b>' +
            '<span class="sm dim">' + escapeHtml(typeLabel) + ' · ' + escapeHtml(statusLabel) + ' · #' + d.id + '</span></div>' +
          '<div class="brk pp-discussion-text">' + escapeHtml(d.text) + '</div>' +
          repliesHtml +
          '<div class="hs wrap">' + resolveBtn + '</div>' +
          replyFormHtml +
        '</div>' +
      '</div>'
    );
  });

  morphInnerHTML(container, parts.join(''));
}

function addPPDiscussion() {
  var input = document.getElementById('ppNewDiscussionInput');
  if (!input || !input.value.trim()) return;

  var text = input.value.trim();
  input.value = '';

  var typeSelect = document.getElementById('ppNewDiscussionType');
  var type = typeSelect ? typeSelect.value : 'general';

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context/discussions', {
    text: text,
    type: type
  }).then(function(res) {
    CONTEXT_DATA.discussions.push({
      id: res.id,
      text: text,
      type: type,
      replies: [],
      author: 'user',
      status: 'open',
      hidden: 0,
      created_at: new Date().toISOString()
    });
    EventBus.emit('discussions:changed');
  }).catch(function(e) {
    showToast(t('messages.failedToAddDiscussion', { error: e.message }));
  });
}

// ═══════════════════════════════════════════════
//  GATE APPROVE / REJECT (Phase 1.4)
// ═══════════════════════════════════════════════

function renderPPGateActions() {
  var container = document.getElementById('ppGateActions');
  if (!container) return;

  var gate = getPendingGate();
  if (!gate || gate.phase !== '1.4') {
    container.innerHTML = '';
    container.dataset.gateKey = '';
    return;
  }

  if (container.dataset.gateKey !== gate.phase) {
    container.dataset.gateKey = gate.phase;
    container.innerHTML = buildGateCardHtml(gate,
      '<button class="btn onGate lg" onclick="ppReject()">' + escapeHtml(t(gate.config.rejectKey)) + '</button>' +
      '<button class="btn pri lg" onclick="ppApprove()">' + cpIcon('check') + escapeHtml(t(gate.config.approveKey)) + '</button>',
      '<div class="wide"><label class="lbl">' + escapeHtml(t('gate.feedbackLabel')) +
        '<textarea class="ta" id="ppRejectFeedback" placeholder="' + escapeHtml(t('placeholders.feedbackForChanges')) + '"></textarea></label></div>');
    attachSubmitKey(container.querySelector('#ppRejectFeedback'), ppReject);
  }
  _refreshGateCardFacts(container, gate);
}

async function ppApprove() {
  var ctx = getWorkspaceContext();
  if (!ctx) { showToast(t('errors.workspaceNotSelected')); return; }

  if (!isUserGate(state.phase)) { showToast(t('errors.noApprovalGateActive')); return; }

  try {
    var result = await apiApprove(ctx.projectId, ctx.branch, '');
    showToast(t('messages.approved', { phase: result.phase }));
    await refreshState();
  } catch (e) {
    showToast(t('messages.approveFailed', { error: e.message }));
  }
}

async function ppReject() {
  var ctx = getWorkspaceContext();
  if (!ctx) { showToast(t('errors.workspaceNotSelected')); return; }

  if (!isUserGate(state.phase)) { showToast(t('errors.noApprovalGateActive')); return; }

  var feedback = '';
  var textarea = document.getElementById('ppRejectFeedback');
  if (textarea) feedback = textarea.value.trim();

  try {
    var result = await apiReject(ctx.projectId, ctx.branch, feedback);
    showToast(t('messages.rejected', { phase: result.phase }));
    await refreshState();
  } catch (e) {
    showToast(t('messages.rejectFailed', { error: e.message }));
  }
}

// ═══════════════════════════════════════════════
//  INLINE COMMENTING
// ═══════════════════════════════════════════════

function togglePPInlineComment(btn, scope, targetId) {
  var card = btn.closest('.pp-research-card, .pp-impact-section, .card-body, #ppImpactContent');
  if (!card) card = btn.parentElement;

  var existingForm = card.querySelector('.pp-inline-comment-form');
  if (existingForm) {
    existingForm.remove();
    return;
  }

  document.querySelectorAll('.pp-inline-comment-form').forEach(function(el) { el.remove(); });

  var form = document.createElement('div');
  form.className = 'pp-inline-comment-form';
  form.onclick = function(e) { e.stopPropagation(); };

  var target = scope + ':' + targetId;

  form.innerHTML =
    '<input type="text" placeholder="' + t('comments.addComment') + '" ' +
      'onkeydown="if(event.key===\'Enter\'){event.preventDefault();submitPPComment(this, \'' + escapeAttr(scope) + '\', \'' + escapeAttr(String(targetId)) + '\');}">' +
    '<button class="btn btn-sm" onclick="submitPPComment(this.previousElementSibling, \'' + escapeAttr(scope) + '\', \'' + escapeAttr(String(targetId)) + '\')">' + t('comments.save') + '</button>';

  card.appendChild(form);
  form.querySelector('input').focus();
}

function submitPPComment(inputEl, scope, targetId) {
  var text = inputEl.value.trim();
  if (!text) return;

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context/discussions', {
    text: text,
    type: scope,
    scope: scope,
    target: targetId
  }).then(function(res) {
    CONTEXT_DATA.discussions.push({
      id: res.id,
      text: text,
      type: scope,
      scope: scope,
      target: targetId,
      replies: [],
      author: 'user',
      status: 'open',
      hidden: 0,
      created_at: new Date().toISOString()
    });
    EventBus.emit('discussions:changed');
    inputEl.value = '';
    var form = inputEl.closest('.pp-inline-comment-form');
    if (form) form.remove();
    showToast(t('preplanning.commentAdded'));
  }).catch(function(e) {
    showToast(t('messages.failedToAddDiscussion', { error: e.message }));
  });
}

function ppReplyToDiscussion(discussionId) {
  var input = document.getElementById('ppReplyInput' + discussionId);
  if (!input) return;
  var text = input.value.trim();
  if (!text) return;

  var ctx = getWorkspaceContext();
  if (!ctx) return;

  apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/context/discussions/' + discussionId + '/reply', {
    text: text
  }).then(function(res) {
    var discussions = CONTEXT_DATA.discussions || [];
    for (var i = 0; i < discussions.length; i++) {
      if (discussions[i].id === discussionId) {
        if (!discussions[i].replies) discussions[i].replies = [];
        discussions[i].replies.push({ text: text, author: 'user' });
        break;
      }
    }
    EventBus.emit('discussions:changed');
  }).catch(function(e) {
    showToast(t('messages.failedToAddDiscussion', { error: e.message }));
  });
}

EventBus.on('state:refreshed', renderPreplanning);
EventBus.on('discussions:changed', renderPPDiscussions);

EventBus.on('research:changed', function() {
  renderPPResearchSummaries();
  renderPPDiscussions();
});
