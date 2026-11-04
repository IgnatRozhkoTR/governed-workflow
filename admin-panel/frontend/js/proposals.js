// ═══════════════════════════════════════════════
//  REFLECTION PROPOSALS TAB
// ═══════════════════════════════════════════════

var PROPOSALS = [];
var _proposalsShowResolved = false;

async function loadProposals() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    try {
        var data = await apiListProposals(ctx.projectId, ctx.branch);
        PROPOSALS = data.proposals || [];
        renderProposalsTab();
        updateProposalsBadge();
    } catch (e) {
        console.warn('Failed to load proposals:', e.message);
    }
}

function renderProposalsTab() {
    var container = document.getElementById('proposalsList');
    if (!container) return;

    var filtered = _proposalsShowResolved
        ? PROPOSALS
        : PROPOSALS.filter(function(p) { return p.status === 'proposed'; });

    if (filtered.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'no-items-msg';
        empty.textContent = t('proposals.empty');
        container.innerHTML = '';
        container.appendChild(empty);
        return;
    }

    var html = filtered.map(buildProposalCardHtml).join('');
    morphInnerHTML(container, html);
    renderMermaidBlocks(container);
}

function buildProposalCardHtml(p) {
    var bodyHtml = DOMPurify.sanitize(marked.parse(p.body || '', { breaks: true, gfm: true }));
    var payloadHtml = buildPayloadHtml(p.payload_json);
    var actionsHtml = p.status === 'proposed' ? buildProposalActionsHtml(p.id) : '';
    var reasonHtml = p.reason
        ? '<div class="proposal-reason"><span class="proposal-reason__label">' + t('proposals.reason') + '</span> ' + escapeHtml(p.reason) + '</div>'
        : '';

    return '<div class="proposal-card">' +
        '<div class="proposal-card__header">' +
            '<span class="proposal-card__title">' + escapeHtml(p.title) + '</span>' +
            '<div class="proposal-card__badges">' +
                '<span class="badge">' + escapeHtml(t('proposals.type.' + p.type)) + '</span>' +
                '<span class="badge">' + escapeHtml(t('proposals.kind.' + p.implementation_kind)) + '</span>' +
                '<span class="badge proposal-status--' + escapeHtml(p.status) + '">' + escapeHtml(t('proposals.status.' + p.status)) + '</span>' +
            '</div>' +
        '</div>' +
        '<div class="proposal-card__body">' + bodyHtml + '</div>' +
        reasonHtml +
        payloadHtml +
        '<div class="proposal-card__footer">' +
            '<span class="proposal-card__date">' + escapeHtml(p.created_at) + '</span>' +
            actionsHtml +
        '</div>' +
    '</div>';
}

function buildPayloadHtml(payloadJson) {
    if (!payloadJson || payloadJson === '{}' || payloadJson.trim() === '') return '';
    var formatted;
    try {
        formatted = JSON.stringify(JSON.parse(payloadJson), null, 2);
    } catch (_) {
        formatted = payloadJson;
    }
    return '<details class="proposal-payload">' +
        '<summary>' + t('proposals.payload') + '</summary>' +
        '<pre>' + escapeHtml(formatted) + '</pre>' +
    '</details>';
}

function buildProposalActionsHtml(id) {
    return '<div class="proposal-card__actions">' +
        '<button class="btn btn-sm" onclick="resolveProposalAction(' + id + ', \'executed\')">' + t('proposals.markApplied') + '</button>' +
        '<button class="btn btn-sm" onclick="resolveProposalAction(' + id + ', \'rejected\')">' + t('proposals.reject') + '</button>' +
    '</div>';
}

async function resolveProposalAction(id, status) {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    try {
        await apiResolveProposal(ctx.projectId, ctx.branch, id, status, null);
        await loadProposals();
    } catch (e) {
        showToast(t('messages.failedToResolve', { error: e.message }));
    }
}

function updateProposalsBadge() {
    var badge = document.getElementById('reflectionBadge');
    if (!badge) return;
    var openCount = PROPOSALS.filter(function(p) { return p.status === 'proposed'; }).length;
    if (openCount > 0) {
        badge.textContent = openCount;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
}

function toggleProposalsResolved() {
    _proposalsShowResolved = !_proposalsShowResolved;
    var btn = document.getElementById('proposalsShowResolvedBtn');
    if (btn) {
        btn.textContent = _proposalsShowResolved
            ? t('proposals.hideResolved')
            : t('proposals.showResolved');
    }
    renderProposalsTab();
}
