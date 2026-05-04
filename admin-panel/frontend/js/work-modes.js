// ═══════════════════════════════════════════════
//  WORK MODES
// ═══════════════════════════════════════════════
var WORK_MODE_LIST = [];
var _workModeSelectedId = null;
var _workModeEditorState = null;
var _workModeProjectsCache = [];
var _workModesInitialized = false;

function initWorkModes() {
  if (!_workModesInitialized) {
    var newBtn = document.getElementById('workModeNewBtn');
    if (newBtn) newBtn.onclick = startNewWorkMode;
    var refreshBtn = document.getElementById('workModeAssignmentsRefreshBtn');
    if (refreshBtn) refreshBtn.onclick = loadWorkspaceAssignments;
    _workModesInitialized = true;
  }
  loadWorkModes();
  loadWorkspaceAssignments();
}

function loadWorkModes() {
  apiGet('/api/work-modes')
    .then(function(data) {
      WORK_MODE_LIST = Array.isArray(data) ? data : [];
      renderWorkModeList();
      if (_workModeSelectedId !== null) {
        var still = _findWorkMode(_workModeSelectedId);
        if (!still) {
          _workModeSelectedId = null;
          renderWorkModeEditor(null);
        }
      }
    })
    .catch(function(e) { showToast('Work modes load failed: ' + (e && e.message)); });
}

function _findWorkMode(modeId) {
  for (var i = 0; i < WORK_MODE_LIST.length; i++) {
    if (String(WORK_MODE_LIST[i].id) === String(modeId)) return WORK_MODE_LIST[i];
  }
  return null;
}

function renderWorkModeList() {
  var listEl = document.getElementById('workModesList');
  if (!listEl) return;

  if (WORK_MODE_LIST.length === 0) {
    listEl.innerHTML = '<div class="work-modes-empty">No modes defined yet.</div>';
    return;
  }

  var rows = WORK_MODE_LIST.map(function(m) {
    var idSafe = escapeHtml(String(m.id));
    var nameSafe = escapeHtml(m.name || '');
    var descSafe = escapeHtml(m.description || '');
    var origin = m.origin === 'system' ? 'system' : 'user';
    var originSafe = escapeHtml(origin);
    var usedBy = typeof m.used_by_count === 'number' ? m.used_by_count : 0;
    var isActive = String(m.id) === String(_workModeSelectedId) ? ' active' : '';
    return '<div class="work-modes-row' + isActive + '" data-mode-id="' + idSafe + '" onclick="selectWorkMode(' + idSafe + ')">' +
      '<div class="work-modes-row-head">' +
        '<span class="work-modes-row-name">' + nameSafe + '</span>' +
        '<span class="work-modes-origin work-modes-origin--' + originSafe + '">' + originSafe + '</span>' +
      '</div>' +
      (descSafe ? '<div class="work-modes-row-desc">' + descSafe + '</div>' : '') +
      '<div class="work-modes-row-meta">' +
        '<span class="work-modes-used-by">Used by: ' + usedBy + '</span>' +
      '</div>' +
    '</div>';
  }).join('');

  listEl.innerHTML = rows;
}

function selectWorkMode(modeId) {
  _workModeSelectedId = modeId;
  document.querySelectorAll('.work-modes-row').forEach(function(row) {
    row.classList.toggle('active', String(row.dataset.modeId) === String(modeId));
  });

  apiGet('/api/work-modes/' + encodeURIComponent(modeId))
    .then(function(mode) { renderWorkModeEditor(mode); })
    .catch(function(e) { showToast('Failed to load mode: ' + (e && e.message)); });
}

function startNewWorkMode() {
  _workModeSelectedId = null;
  document.querySelectorAll('.work-modes-row').forEach(function(row) {
    row.classList.remove('active');
  });
  renderWorkModeEditor({
    id: null,
    name: '',
    description: '',
    phases: [],
    origin: 'user',
    used_by_count: 0
  });
}

function renderWorkModeEditor(mode) {
  var el = document.getElementById('workModesEditor');
  if (!el) return;

  if (!mode) {
    el.innerHTML = '<div class="work-modes-empty">Select a mode to edit, or create a new one.</div>';
    _workModeEditorState = null;
    return;
  }

  _workModeEditorState = {
    id: mode.id || null,
    name: mode.name || '',
    description: mode.description || '',
    phases: (mode.phases || []).map(function(p) {
      return {
        phase_id: p.phase_id || p.id || '',
        enabled: p.enabled !== false
      };
    }),
    origin: mode.origin === 'system' ? 'system' : 'user'
  };

  var isSystem = _workModeEditorState.origin === 'system';
  var isNew = _workModeEditorState.id === null;
  var disabledAttr = isSystem ? ' disabled' : '';

  var nameSafe = escapeHtml(_workModeEditorState.name);
  var descSafe = escapeHtml(_workModeEditorState.description);
  var originSafe = escapeHtml(_workModeEditorState.origin);

  var phaseRows = _workModeEditorState.phases.map(function(p, idx) {
    var phaseSafe = escapeHtml(p.phase_id);
    var checked = p.enabled ? ' checked' : '';
    return '<li class="work-modes-phase-row" draggable="' + (isSystem ? 'false' : 'true') + '" data-phase-idx="' + idx + '">' +
      '<span class="work-modes-drag-handle" title="Drag to reorder">⋮⋮</span>' +
      '<input type="text" class="context-input work-modes-phase-input" value="' + phaseSafe + '" data-idx="' + idx + '" oninput="onWorkModePhaseInput(' + idx + ', this.value)"' + disabledAttr + ' />' +
      '<label class="work-modes-phase-toggle">' +
        '<input type="checkbox"' + checked + ' onchange="onWorkModePhaseToggle(' + idx + ', this.checked)"' + disabledAttr + '/>' +
        '<span data-i18n="workModes.enabled">Enabled</span>' +
      '</label>' +
      (isSystem ? '' : '<button class="btn btn-sm btn-outline work-modes-phase-remove" onclick="removeWorkModePhase(' + idx + ')" title="Remove">×</button>') +
    '</li>';
  }).join('');

  var systemNote = isSystem
    ? '<div class="work-modes-system-note" data-i18n="workModes.systemNote">System modes are read-only. Duplicate to customize.</div>'
    : '';

  var deleteBtn = (!isSystem && !isNew)
    ? '<button class="btn btn-sm btn-danger-outline" id="workModeDeleteBtn" data-i18n="buttons.delete">Delete</button>'
    : '';

  el.innerHTML =
    '<div class="work-modes-editor-header">' +
      '<div class="work-modes-editor-title">' +
        (isNew ? '<span data-i18n="workModes.newTitle">New mode</span>' : '<span>' + nameSafe + '</span>') +
        ' <span class="work-modes-origin work-modes-origin--' + originSafe + '">' + originSafe + '</span>' +
      '</div>' +
      '<div class="work-modes-editor-actions">' +
        deleteBtn +
        (isSystem ? '' : '<button class="btn btn-sm btn-primary" id="workModeSaveBtn" data-i18n="buttons.save">Save</button>') +
      '</div>' +
    '</div>' +
    systemNote +
    '<div class="work-modes-editor-field">' +
      '<label data-i18n="workModes.fieldName">Name</label>' +
      '<input type="text" id="workModeFieldName" class="context-input" value="' + nameSafe + '"' + disabledAttr + '/>' +
    '</div>' +
    '<div class="work-modes-editor-field">' +
      '<label data-i18n="workModes.fieldDescription">Description</label>' +
      '<textarea id="workModeFieldDescription" class="context-textarea"' + disabledAttr + '>' + descSafe + '</textarea>' +
    '</div>' +
    '<div class="work-modes-editor-field">' +
      '<label data-i18n="workModes.fieldPhases">Phases (drag to reorder)</label>' +
      '<ul class="work-modes-phase-list" id="workModePhaseList">' + phaseRows + '</ul>' +
      (isSystem ? '' : '<button class="btn btn-sm btn-outline" onclick="addWorkModePhase()" data-i18n="workModes.addPhase">Add phase</button>') +
    '</div>';

  _wireWorkModeEditorEvents();
  _wirePhaseDragAndDrop();
  applyI18nToDOM();
}

function _wireWorkModeEditorEvents() {
  var nameField = document.getElementById('workModeFieldName');
  var descField = document.getElementById('workModeFieldDescription');
  if (nameField) {
    nameField.oninput = function() {
      if (_workModeEditorState) _workModeEditorState.name = nameField.value;
    };
  }
  if (descField) {
    descField.oninput = function() {
      if (_workModeEditorState) _workModeEditorState.description = descField.value;
    };
  }
  var saveBtn = document.getElementById('workModeSaveBtn');
  if (saveBtn) saveBtn.onclick = saveCurrentWorkMode;
  var delBtn = document.getElementById('workModeDeleteBtn');
  if (delBtn) delBtn.onclick = deleteCurrentWorkMode;
}

function onWorkModePhaseInput(idx, value) {
  if (!_workModeEditorState || !_workModeEditorState.phases[idx]) return;
  _workModeEditorState.phases[idx].phase_id = value;
}

function onWorkModePhaseToggle(idx, enabled) {
  if (!_workModeEditorState || !_workModeEditorState.phases[idx]) return;
  _workModeEditorState.phases[idx].enabled = !!enabled;
}

function addWorkModePhase() {
  if (!_workModeEditorState) return;
  _workModeEditorState.phases.push({ phase_id: '', enabled: true });
  renderWorkModeEditor(_workModeEditorState);
}

function removeWorkModePhase(idx) {
  if (!_workModeEditorState || !_workModeEditorState.phases[idx]) return;
  _workModeEditorState.phases.splice(idx, 1);
  renderWorkModeEditor(_workModeEditorState);
}

var _phaseDragSourceIdx = null;

function _wirePhaseDragAndDrop() {
  var listEl = document.getElementById('workModePhaseList');
  if (!listEl) return;

  var rows = listEl.querySelectorAll('.work-modes-phase-row');
  rows.forEach(function(row) {
    row.ondragstart = function(e) {
      _phaseDragSourceIdx = parseInt(row.dataset.phaseIdx, 10);
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', String(_phaseDragSourceIdx)); } catch (err) {}
      row.classList.add('work-modes-phase-row--dragging');
    };
    row.ondragend = function() {
      row.classList.remove('work-modes-phase-row--dragging');
      _phaseDragSourceIdx = null;
    };
    row.ondragover = function(e) {
      if (_phaseDragSourceIdx === null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      row.classList.add('work-modes-phase-row--drop-target');
    };
    row.ondragleave = function() {
      row.classList.remove('work-modes-phase-row--drop-target');
    };
    row.ondrop = function(e) {
      e.preventDefault();
      row.classList.remove('work-modes-phase-row--drop-target');
      if (_phaseDragSourceIdx === null) return;
      var targetIdx = parseInt(row.dataset.phaseIdx, 10);
      if (targetIdx === _phaseDragSourceIdx) return;
      _moveWorkModePhase(_phaseDragSourceIdx, targetIdx);
    };
  });
}

function _moveWorkModePhase(fromIdx, toIdx) {
  if (!_workModeEditorState) return;
  var phases = _workModeEditorState.phases;
  if (fromIdx < 0 || fromIdx >= phases.length || toIdx < 0 || toIdx >= phases.length) return;
  var moved = phases.splice(fromIdx, 1)[0];
  phases.splice(toIdx, 0, moved);
  renderWorkModeEditor(_workModeEditorState);
}

function _normalizedPhasesPayload() {
  if (!_workModeEditorState) return [];
  return _workModeEditorState.phases
    .map(function(p) {
      return { phase_id: (p.phase_id || '').trim(), enabled: p.enabled !== false };
    })
    .filter(function(p) { return p.phase_id.length > 0; });
}

function saveCurrentWorkMode() {
  if (!_workModeEditorState) return;
  var name = (_workModeEditorState.name || '').trim();
  if (!name) {
    showToast('Mode name is required.');
    return;
  }

  var payload = {
    name: name,
    description: _workModeEditorState.description || '',
    phases: _normalizedPhasesPayload()
  };

  var request;
  if (_workModeEditorState.id === null) {
    request = apiPost('/api/work-modes', payload);
  } else {
    request = apiPatch('/api/work-modes/' + encodeURIComponent(_workModeEditorState.id), payload);
  }

  request
    .then(function(mode) {
      showToast('Mode saved.');
      _workModeSelectedId = mode.id;
      loadWorkModes();
      loadWorkspaceAssignments();
      apiGet('/api/work-modes/' + encodeURIComponent(mode.id))
        .then(function(fresh) { renderWorkModeEditor(fresh); })
        .catch(function() { renderWorkModeEditor(mode); });
    })
    .catch(function(e) { showToast('Save failed: ' + (e && e.message)); });
}

function deleteCurrentWorkMode() {
  if (!_workModeEditorState || _workModeEditorState.id === null) return;
  var modeId = _workModeEditorState.id;
  if (!confirm('Delete this work mode? Workspaces using it will need to be reassigned.')) return;

  apiDelete('/api/work-modes/' + encodeURIComponent(modeId))
    .then(function() {
      showToast('Mode deleted.');
      _workModeSelectedId = null;
      _workModeEditorState = null;
      renderWorkModeEditor(null);
      loadWorkModes();
      loadWorkspaceAssignments();
    })
    .catch(function(e) {
      var msg = e && e.message ? e.message : 'unknown';
      if (e && e.status === 409) {
        showToast('System modes cannot be deleted: ' + msg);
      } else {
        showToast('Delete failed: ' + msg);
      }
    });
}

function loadWorkspaceAssignments() {
  apiGet('/api/projects')
    .then(function(data) {
      _workModeProjectsCache = (data && data.projects) || [];
      var promises = _workModeProjectsCache.map(function(p) {
        return apiGet('/api/projects/' + encodeURIComponent(p.id) + '/workspaces')
          .then(function(d) { return { project: p, workspaces: (d && d.workspaces) || [] }; })
          .catch(function() { return { project: p, workspaces: [] }; });
      });
      return Promise.all(promises);
    })
    .then(function(perProject) {
      renderWorkspaceAssignments(perProject || []);
    })
    .catch(function(e) { showToast('Workspace list failed: ' + (e && e.message)); });
}

function _modeOptionsHtml(currentModeId) {
  var opts = '<option value=""' + (currentModeId == null ? ' selected' : '') + '>(none)</option>';
  opts += WORK_MODE_LIST.map(function(m) {
    var idSafe = escapeHtml(String(m.id));
    var nameSafe = escapeHtml(m.name || '');
    var sel = String(m.id) === String(currentModeId) ? ' selected' : '';
    var origin = m.origin === 'system' ? ' [system]' : '';
    return '<option value="' + idSafe + '"' + sel + '>' + nameSafe + origin + '</option>';
  }).join('');
  return opts;
}

function renderWorkspaceAssignments(perProject) {
  var el = document.getElementById('workModeAssignments');
  if (!el) return;

  var totalCount = 0;
  perProject.forEach(function(g) { totalCount += g.workspaces.length; });

  if (totalCount === 0) {
    el.innerHTML = '<div class="work-modes-empty">No workspaces registered yet.</div>';
    return;
  }

  var rows = [];
  perProject.forEach(function(g) {
    g.workspaces.forEach(function(ws) {
      var wsId = ws.workspace_id != null ? ws.workspace_id : ws.id;
      var wsIdSafe = escapeHtml(String(wsId));
      var projectSafe = escapeHtml(g.project.name || g.project.id || '');
      var branchSafe = escapeHtml(ws.branch || '');
      var phaseSafe = escapeHtml(ws.phase || '');
      var statusSafe = escapeHtml(ws.status || '');
      var currentModeId = ws.work_mode_id != null ? ws.work_mode_id : null;
      var currentModeName = '';
      if (currentModeId !== null) {
        var found = _findWorkMode(currentModeId);
        currentModeName = found ? found.name : '#' + currentModeId;
      }
      rows.push('<tr class="work-modes-assign-row" data-ws-id="' + wsIdSafe + '">' +
        '<td>' + projectSafe + '</td>' +
        '<td><span class="work-modes-branch">' + branchSafe + '</span></td>' +
        '<td>' + phaseSafe + '</td>' +
        '<td>' + statusSafe + '</td>' +
        '<td>' +
          '<select class="context-input work-modes-assign-select" id="workModeAssignSelect_' + wsIdSafe + '">' +
            _modeOptionsHtml(currentModeId) +
          '</select>' +
        '</td>' +
        '<td class="work-modes-assign-actions">' +
          '<button class="btn btn-sm" onclick="assignModeFromRow(' + wsIdSafe + ')" data-i18n="workModes.assignBtn">Assign</button>' +
          '<button class="btn btn-sm btn-primary" onclick="applyMode(' + wsIdSafe + ')" data-i18n="workModes.applyBtn">Apply</button>' +
        '</td>' +
      '</tr>');
    });
  });

  el.innerHTML = '<table class="work-modes-assign-table">' +
    '<thead><tr>' +
      '<th data-i18n="workModes.colProject">Project</th>' +
      '<th data-i18n="workModes.colBranch">Branch</th>' +
      '<th data-i18n="workModes.colPhase">Phase</th>' +
      '<th data-i18n="workModes.colStatus">Status</th>' +
      '<th data-i18n="workModes.colMode">Mode</th>' +
      '<th></th>' +
    '</tr></thead>' +
    '<tbody>' + rows.join('') + '</tbody>' +
  '</table>';
  applyI18nToDOM();
}

function assignModeFromRow(workspaceId) {
  var sel = document.getElementById('workModeAssignSelect_' + workspaceId);
  if (!sel) return;
  var raw = sel.value;
  if (raw === '' || raw == null) {
    showToast('Select a mode before assigning.');
    return;
  }
  var modeId = parseInt(raw, 10);
  if (isNaN(modeId)) return;
  assignMode(workspaceId, modeId);
}

function assignMode(workspaceId, modeId) {
  apiPut('/api/workspaces/' + encodeURIComponent(workspaceId) + '/work-mode', { mode_id: modeId })
    .then(function(result) {
      var modeName = result && result.mode_name ? result.mode_name : '#' + modeId;
      showToast('Mode "' + modeName + '" assigned. Click Apply to re-resolve phases.');
      loadWorkspaceAssignments();
      loadWorkModes();
    })
    .catch(function(e) { showToast('Assign failed: ' + (e && e.message)); });
}

function applyMode(workspaceId) {
  apiPost('/api/workspaces/' + encodeURIComponent(workspaceId) + '/work-mode/apply', {})
    .then(function(result) {
      var modeName = result && result.mode_name ? result.mode_name : '';
      var phases = (result && result.effective_phases) || [];
      var phasesText = phases.length > 0 ? phases.map(function(p) {
        return (p.phase_id || p.id || '') + (p.enabled === false ? ' (off)' : '');
      }).join(', ') : '(no phases enabled)';
      showToast('Applied "' + modeName + '". Effective phases: ' + phasesText);
      loadWorkspaceAssignments();
    })
    .catch(function(e) { showToast('Apply failed: ' + (e && e.message)); });
}
