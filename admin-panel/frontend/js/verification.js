// ═══════════════════════════════════════════════
//  VERIFICATION PROFILES
// ═══════════════════════════════════════════════

var VERIFICATION_PROFILES = [];
var WORKSPACE_VERIFICATION = [];
var VERIFICATION_RESULTS = null;

async function loadVerificationData() {
    var ctx = getWorkspaceContext();
    try {
        var allProfiles = await apiGet('/api/verification/profiles');
        VERIFICATION_PROFILES = allProfiles.profiles || [];
    } catch(e) {
        console.warn('Failed to load verification profiles:', e.message);
        if (typeof showToast === 'function') showToast('Failed to load verification profiles: ' + e.message);
    }

    if (ctx) {
        try {
            var wsProfiles = await apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/verification/profiles');
            WORKSPACE_VERIFICATION = wsProfiles.profiles || [];
        } catch(e) {
            console.warn('Failed to load workspace verification profiles:', e.message);
            WORKSPACE_VERIFICATION = [];
        }
    }

    renderVerification();
}

async function loadVerificationResults() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    try {
        var results = await apiGet('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/verification/results');
        VERIFICATION_RESULTS = results.steps ? results : null;
        renderVerificationResults();
    } catch(e) {
        console.warn('Failed to load verification results:', e.message);
    }
}

function renderVerification() {
    renderAssignedProfiles();
    renderProfileSelector();
}

function renderAssignedProfiles() {
    var container = document.getElementById('verificationAssigned');
    if (!container) return;
    container.innerHTML = '';

    if (WORKSPACE_VERIFICATION.length === 0) {
        container.innerHTML = '<div class="no-items-msg">' + t('verification.noProfiles') + '</div>';
        return;
    }

    WORKSPACE_VERIFICATION.forEach(function(profile) {
        var el = document.createElement('div');
        el.className = 'verification-profile-card';

        var stepsHtml = (profile.steps || []).map(function(step) {
            var statusClass = step.enabled ? 'step-enabled' : 'step-disabled';
            var severityBadge = step.fail_severity === 'blocking'
                ? '<span class="severity-badge severity-blocking">blocking</span>'
                : '<span class="severity-badge severity-warning">warning</span>';
            return '<div class="verification-step ' + statusClass + '">'
                + '<label class="step-toggle">'
                + '<input type="checkbox" ' + (step.enabled ? 'checked' : '') + ' onchange="toggleVerificationStep(' + step.id + ', this.checked)">'
                + '<span class="step-name">' + escapeHtml(step.name) + '</span>'
                + '</label>'
                + severityBadge
                + '<code class="step-command">' + escapeHtml(step.command) + '</code>'
                + '</div>';
        }).join('');

        var subpathNote = profile.subpath !== '.' ? ' <span class="subpath-badge">' + escapeHtml(profile.subpath) + '</span>' : '';

        el.innerHTML = '<div class="verification-profile-header">'
            + '<span class="verification-profile-name">' + escapeHtml(profile.name) + subpathNote + '</span>'
            + '<button class="btn btn-sm btn-outline" onclick="unassignVerificationProfile(' + profile.assignment_id + ')">' + t('verification.remove') + '</button>'
            + '</div>'
            + '<div class="verification-steps">' + stepsHtml + '</div>';

        container.appendChild(el);
    });
}

function renderProfileSelector() {
    var select = document.getElementById('verificationProfileSelect');
    if (!select) return;

    var assignedIds = WORKSPACE_VERIFICATION.map(function(p) { return p.id; });
    var available = VERIFICATION_PROFILES.filter(function(p) { return assignedIds.indexOf(p.id) === -1; });

    select.innerHTML = '<option value="">' + t('verification.selectProfile') + '</option>';
    available.forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name + ' (' + p.language + ')';
        select.appendChild(opt);
    });
}

var VERIFICATION_STEP_PILLS = { passed: 'ok', failed: 'bad', error: 'bad', warning: 'warn' };

function _buildVerificationStepHtml(step) {
    var pillClass = VERIFICATION_STEP_PILLS[step.status] || '';
    var durationStr = step.duration_ms ? ' (' + (step.duration_ms / 1000).toFixed(1) + 's)' : '';
    var statusLabel = t('verification.status.' + step.status);
    var outputHtml = step.output ? '<pre class="step-output">' + escapeHtml(step.output) + '</pre>' : '';
    return '<div class="verification-result-step result-' + escapeHtml(step.status) + '">'
        + '<div class="result-step-header">'
        + '<span class="pill ' + pillClass + ' result-step-status">' + escapeHtml(statusLabel) + '</span>'
        + '<span class="result-step-name">' + escapeHtml(step.profile_name) + ' / ' + escapeHtml(step.step_name) + durationStr + '</span>'
        + '</div>'
        + outputHtml
        + '</div>';
}

function _renderVerificationMeta(run) {
    var meta = document.getElementById('verificationMeta');
    if (!meta) return;
    if (!run) { meta.textContent = ''; return; }
    var when = run.completed_at || run.started_at;
    meta.textContent = t('verification.runMeta', {phase: run.phase, when: when ? formatRelativeDate(when) : ''}).replace(/ · $/, '');
}

function renderVerificationResults() {
    var container = document.getElementById('verificationResults');
    if (!container) return;
    renderOverviewVerificationSummary();

    if (!VERIFICATION_RESULTS || !VERIFICATION_RESULTS.steps) {
        _renderVerificationMeta(null);
        container.innerHTML = '<div class="empty">' + t('verification.noRuns') + '</div>';
        return;
    }

    _renderVerificationMeta(VERIFICATION_RESULTS);
    container.innerHTML = '<div class="verification-run run-' + escapeHtml(VERIFICATION_RESULTS.status) + '">'
        + (VERIFICATION_RESULTS.steps || []).map(_buildVerificationStepHtml).join('')
        + '</div>';
}

async function assignVerificationProfile() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    var select = document.getElementById('verificationProfileSelect');
    var subpathInput = document.getElementById('verificationSubpath');
    var profileId = select ? parseInt(select.value) : 0;
    if (!profileId) return;
    var subpath = subpathInput ? subpathInput.value.trim() || '.' : '.';

    try {
        await apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/verification/assign', {
            profile_id: profileId,
            subpath: subpath
        });
        if (subpathInput) subpathInput.value = '';
        await loadVerificationData();
    } catch(e) {
        if (typeof showToast === 'function') showToast('Failed to assign: ' + e.message);
    }
}

async function unassignVerificationProfile(assignmentId) {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    try {
        await apiDelete('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/verification/unassign/' + assignmentId);
        await loadVerificationData();
    } catch(e) {
        if (typeof showToast === 'function') showToast('Failed to remove: ' + e.message);
    }
}

async function toggleVerificationStep(stepId, enabled) {
    try {
        await apiPut('/api/verification/steps/' + stepId, {enabled: enabled});
        await loadVerificationData();
    } catch(e) {
        if (typeof showToast === 'function') showToast('Failed to update step: ' + e.message);
        await loadVerificationData();
    }
}

async function runVerificationManual() {
    var ctx = getWorkspaceContext();
    if (!ctx) return;
    var btn = document.getElementById('runVerificationBtn');
    if (btn) { btn.disabled = true; btn.lastElementChild.textContent = t('verification.running'); }
    try {
        var resp = await apiPost('/api/ws/' + encodeURIComponent(ctx.projectId) + '/' + encodeURIComponent(ctx.branch) + '/verification/run', {});
        VERIFICATION_RESULTS = resp.steps ? resp : null;
        renderVerificationResults();
        if (typeof showToast === 'function') {
            var status = resp.status || resp.message || 'done';
            showToast(status === 'passed' ? t('verification.runPassed') : status === 'failed' ? t('verification.runFailed') : status);
        }
    } catch(e) {
        if (typeof showToast === 'function') showToast(t('verification.runError') + ': ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.lastElementChild.textContent = t('verification.run'); }
    }
}
