// ═══════════════════════════════════════════════
//  DIAGRAM ZOOM & PAN
// ═══════════════════════════════════════════════

// Diagram zoom state
let diagramScale = 1.0;
let systemDiagramScale = 1.0;

function zoomDiagram(delta) {
  diagramScale = Math.max(0.4, Math.min(2.5, diagramScale + delta));
  const svg = document.querySelector('#planDiagram svg');
  if (svg) svg.style.transform = `scale(${diagramScale})`;
  const label = document.getElementById('diagramZoomLevel');
  if (label) label.textContent = Math.round(diagramScale * 100) + '%';
}

function zoomSystemDiagram(delta) {
  systemDiagramScale = Math.max(0.4, Math.min(2.5, systemDiagramScale + delta));
  const svg = document.querySelector('#systemDiagram svg');
  if (svg) svg.style.transform = `scale(${systemDiagramScale})`;
  const label = document.getElementById('systemDiagramZoomLevel');
  if (label) label.textContent = Math.round(systemDiagramScale * 100) + '%';
}

// Diagram pan (drag to scroll)
function makePannable(containerId, options) {
  const ignoredSelectors = (options && options.ignoreSelectors) || [];
  const useCursorStyle = (options && options.useCursorStyle) || false;
  let isDragging = false;
  let startX, startY, scrollLeft, scrollTop;

  document.addEventListener('mousedown', function(e) {
    const container = document.getElementById(containerId);
    if (!container || !container.contains(e.target)) return;
    if (e.target.closest('button')) return;
    for (let i = 0; i < ignoredSelectors.length; i++) {
      if (e.target.closest(ignoredSelectors[i])) return;
    }
    isDragging = true;
    if (useCursorStyle) {
      container.style.cursor = 'grabbing';
    } else {
      container.classList.add('dragging');
    }
    startX = e.pageX - container.offsetLeft;
    startY = e.pageY - container.offsetTop;
    scrollLeft = container.scrollLeft;
    scrollTop = container.scrollTop;
    e.preventDefault();
  });

  document.addEventListener('mousemove', function(e) {
    if (!isDragging) return;
    const container = document.getElementById(containerId);
    if (!container) return;
    const x = e.pageX - container.offsetLeft;
    const y = e.pageY - container.offsetTop;
    container.scrollLeft = scrollLeft - (x - startX);
    container.scrollTop = scrollTop - (y - startY);
  });

  document.addEventListener('mouseup', function() {
    if (!isDragging) return;
    isDragging = false;
    const container = document.getElementById(containerId);
    if (!container) return;
    if (useCursorStyle) {
      container.style.cursor = 'grab';
    } else {
      container.classList.remove('dragging');
    }
  });
}

makePannable('planDiagram', { ignoreSelectors: ['.comment-icon'] });
makePannable('systemDiagram', { ignoreSelectors: ['.comment-icon', '.comment-icon-header'] });
makePannable('diagramOverlayBody', { ignoreSelectors: ['.diagram-overlay-controls'], useCursorStyle: true });

// ═══════════════════════════════════════════════
//  SYSTEM DIAGRAM RENDER
// ═══════════════════════════════════════════════

var _lastSystemDiagramSignature = null;
var _lastMermaidDiagramSignature = null;

function _hashString(str) {
  var hash = 0;
  if (!str) return '0';
  for (var i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return String(hash);
}

async function renderSystemDiagram() {
  var container = document.getElementById('systemDiagram');
  if (!container || typeof mermaid === 'undefined') return;

  var raw = PLAN_DATA.systemDiagram;
  if (!raw || (Array.isArray(raw) && raw.length === 0)) {
    if (_lastSystemDiagramSignature !== 'empty') {
      container.innerHTML = '<div class="empty">' + t('plan.noSystemDiagram') + '</div>';
      _lastSystemDiagramSignature = 'empty';
    }
    return;
  }

  var signature = _hashString((typeof raw === 'string' ? raw : JSON.stringify(raw)) + '|' + _currentThemeName());
  if (signature === _lastSystemDiagramSignature) return;
  _lastSystemDiagramSignature = signature;

  var diagrams;
  if (typeof raw === 'string') {
    diagrams = [{ title: '', diagram: raw }];
  } else if (Array.isArray(raw)) {
    diagrams = raw;
  } else {
    container.innerHTML = '<div class="empty">' + t('plan.invalidDiagramFormat') + '</div>';
    return;
  }

  container.innerHTML = '';

  for (var idx = 0; idx < diagrams.length; idx++) {
    var entry = diagrams[idx];
    var diagramText = entry.diagram || '';
    if (!diagramText.trim()) continue;

    if (entry.title) {
      var titleEl = document.createElement('h4');
      titleEl.className = 'diagram-subtitle';
      titleEl.textContent = entry.title;
      container.appendChild(titleEl);
    }

    var diagramDiv = document.createElement('div');
    diagramDiv.className = 'diagram-section';
    diagramDiv.id = 'systemDiagram_' + idx;
    container.appendChild(diagramDiv);

    var themed = diagramText;
    if (typeof getMermaidInit === 'function') {
      themed = diagramText.replace(/%%\{init:[\s\S]*?\}%%/g, getMermaidInit());
      if (themed === diagramText && !diagramText.includes('%%{init:')) {
        themed = getMermaidInit() + '\n' + diagramText;
      }
    }

    // Replace hardcoded rect colors with theme-appropriate alternatives
    if (typeof getMermaidTheme === 'function') {
      var isDarkTheme = (localStorage.getItem('admin-panel-theme') || 'dark') === 'dark';
      var rectColors = isDarkTheme
        ? ['rgba(40, 40, 60, 0.5)', 'rgba(40, 60, 40, 0.5)', 'rgba(60, 40, 40, 0.5)']
        : ['rgba(200, 210, 230, 0.3)', 'rgba(200, 230, 210, 0.3)', 'rgba(230, 210, 200, 0.3)'];
      var colorIdx = 0;
      themed = themed.replace(/rect\s+rgb\s*\([^)]+\)/g, function() {
        var color = rectColors[colorIdx % rectColors.length];
        colorIdx++;
        return 'rect ' + color;
      });
      themed = themed.replace(/rect\s+#[0-9a-fA-F]{3,8}/g, function() {
        var color = rectColors[colorIdx % rectColors.length];
        colorIdx++;
        return 'rect ' + color;
      });
    }

    // Replace literal \n with <br/> for Mermaid line breaks
    themed = themed.replace(/\\n/g, '<br/>');

    try {
      var renderResult = await mermaid.render('sysDiag_' + idx, themed);
      diagramDiv.innerHTML = renderResult.svg;
      polishDiagramSvg(diagramDiv.querySelector('svg'));
    } catch (e) {
      console.error('System diagram render failed:', e);
      diagramDiv.innerHTML = '<pre class="diagram-error">Diagram render error: ' + escapeHtml(e.message) + '</pre>';
    }
  }
}

// ═══════════════════════════════════════════════
//  DIAGRAM THEMING AND LANE POLISH
// ═══════════════════════════════════════════════
var MIN_LANE_WIDTH = 150;
var LANE_TITLE_INSET = 10;

function _currentThemeName() {
  return localStorage.getItem('admin-panel-theme') || 'dark';
}

function _readToken(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function getDiagramNodeStyles() {
  return {
    done: 'fill:' + _readToken('--okbg') + ',stroke:' + _readToken('--ok') + ',color:' + _readToken('--oktx'),
    progress: 'fill:' + _readToken('--prbg') + ',stroke:' + _readToken('--pr') + ',color:' + _readToken('--prtx'),
    pending: 'fill:' + _readToken('--sf2') + ',stroke:' + _readToken('--ln') + ',color:' + _readToken('--tx'),
    dot: 'fill:' + _readToken('--ln') + ',stroke:' + _readToken('--dim') + ',color:' + _readToken('--ln')
  };
}

function polishDiagramSvg(svgEl) {
  if (!svgEl) return;
  svgEl.querySelectorAll('g.cluster').forEach(function(cluster) {
    var label = cluster.querySelector(':scope > .cluster-label');
    var fullTitle = label ? label.textContent.trim() : '';
    if (fullTitle && !cluster.querySelector(':scope > title')) {
      var title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = fullTitle;
      cluster.insertBefore(title, cluster.firstChild);
    }
    var rect = cluster.querySelector(':scope > rect');
    if (!rect) return;
    _widenLane(rect);
    if (label) _fitLaneTitle(label, rect);
  });
}

function _widenLane(rect) {
  var width = parseFloat(rect.getAttribute('width'));
  if (width >= MIN_LANE_WIDTH) return;
  rect.setAttribute('x', parseFloat(rect.getAttribute('x')) - (MIN_LANE_WIDTH - width) / 2);
  rect.setAttribute('width', MIN_LANE_WIDTH);
}

function _fitLaneTitle(label, rect) {
  var box = label.querySelector('foreignObject');
  var text = label.querySelector('.nodeLabel');
  if (!box || !text) return;
  var available = parseFloat(rect.getAttribute('width')) - LANE_TITLE_INSET * 2;
  var width = parseFloat(box.getAttribute('width'));
  var y = (label.getAttribute('transform').match(/translate\([^,]+,\s*([^)]+)\)/) || [])[1];
  if (width > available) {
    box.setAttribute('width', available);
    var wrapper = text.parentElement;
    wrapper.style.display = 'block';
    wrapper.style.width = available + 'px';
    text.style.display = 'block';
    text.style.overflow = 'hidden';
    text.style.textOverflow = 'ellipsis';
    width = available;
  }
  var left = parseFloat(rect.getAttribute('x')) + (parseFloat(rect.getAttribute('width')) - width) / 2;
  label.setAttribute('transform', 'translate(' + left + ',' + y + ')');
}

function attachDiagramClickToExpand(containerId) {
  var container = document.getElementById(containerId);
  if (!container) return;
  var downAt = null;
  container.addEventListener('pointerdown', function(e) { downAt = { x: e.clientX, y: e.clientY }; });
  container.addEventListener('pointerup', function(e) {
    if (!downAt || e.target.closest('button, .comment-icon, .comment-icon-header, a')) return;
    var moved = Math.abs(e.clientX - downAt.x) + Math.abs(e.clientY - downAt.y);
    downAt = null;
    if (moved < 5 && container.querySelector('svg')) expandDiagram(containerId);
  });
}

attachDiagramClickToExpand('planDiagram');
attachDiagramClickToExpand('systemDiagram');

// ═══════════════════════════════════════════════
//  PLAN RENDER
// ═══════════════════════════════════════════════

function getGroupStatus(group) {
  const done = group.tasks.filter(task => task.status === 'done').length;
  const total = group.tasks.length;
  if (done === total) return 'all-done';
  if (done > 0) return 'partial';
  return 'pending';
}

var _diagramTooltips = {};

function truncateLabel(text, maxLen) {
  if (!text || text.length <= maxLen) return text;
  return text.substring(0, maxLen - 1) + '…';
}

function buildMermaidDiagram(direction) {
  _diagramTooltips = {};
  direction = direction || 'LR';
  var colors = getDiagramNodeStyles();
  var items = PLAN_DATA.execution || PLAN_DATA.groups || [];
  if (items.length === 0) return '';

  var innerDirection = direction === 'TD' ? 'LR' : 'TB';

  var lines = [
    getMermaidInit(),
    'graph ' + direction
  ];

  var lastSubPhaseNodes = [];

  items.forEach(function(item, i) {
    var tasks = item.tasks || [];
    var subId = 'S' + (i + 1);
    var fullSubName = item.name || t('phase.phaseName', {phase: i + 1});
    var subLabel = escapeHtml(item.id || '') + ' — ' + escapeHtml(truncateLabel(fullSubName, 25));
    _diagramTooltips[subId] = (item.id || '') + ' — ' + fullSubName;

    lines.push('    subgraph ' + subId + '["' + subLabel + '"]');
    lines.push('    direction ' + innerDirection);

    if (tasks.length === 0) {
      var emptyId = subId + '_empty';
      lines.push('        ' + emptyId + '["' + t('plan.noTasks') + '"]');
      lines.push('    end');
      if (lastSubPhaseNodes.length > 0) {
        lastSubPhaseNodes.forEach(function(ln) { lines.push('    ' + ln + ' --> ' + emptyId); });
      }
      lastSubPhaseNodes = [emptyId];
      return;
    }

    // Group tasks by group field
    var groupOrder = [];
    var groupMap = {};
    tasks.forEach(function(task, j) {
      var g = task.group || ('_solo_' + j);
      if (!groupMap[g]) {
        groupMap[g] = [];
        groupOrder.push(g);
      }
      groupMap[g].push({task: task, index: j});
    });

    var lastGroupNodes = [];

    groupOrder.forEach(function(groupName, gi) {
      var members = groupMap[groupName];
      var isParallelGroup = members.length > 1;
      var groupId = subId + '_G' + gi;

      // Create task node IDs
      var taskIds = members.map(function(m) { return subId + '_T' + (m.index + 1); });

      // Render task nodes
      members.forEach(function(m, mi) {
        var tId = taskIds[mi];
        var fullTitle = m.task.title || t('plan.task', {n: m.index + 1});
        var agentBadge = m.task.agent ? '<br/>' + escapeHtml(m.task.agent) : '';
        var label = escapeHtml(truncateLabel(fullTitle, 30)) + agentBadge;
        _diagramTooltips[tId] = fullTitle + (m.task.agent ? ' (' + m.task.agent + ')' : '');
        lines.push('        ' + tId + '["' + label + '"]');
      });

      var groupFirstNodes, groupLastNodes;

      if (isParallelGroup) {
        var forkId = groupId + '_fork';
        var joinId = groupId + '_join';
        lines.push('        ' + forkId + '(( ))');
        lines.push('        ' + joinId + '(( ))');
        lines.push('    style ' + forkId + ' ' + colors.dot);
        lines.push('    style ' + joinId + ' ' + colors.dot);
        taskIds.forEach(function(tId) {
          lines.push('        ' + forkId + ' --> ' + tId);
          lines.push('        ' + tId + ' --> ' + joinId);
        });
        groupFirstNodes = [forkId];
        groupLastNodes = [joinId];
      } else {
        for (var k = 1; k < taskIds.length; k++) {
          lines.push('        ' + taskIds[k - 1] + ' --> ' + taskIds[k]);
        }
        groupFirstNodes = [taskIds[0]];
        groupLastNodes = [taskIds[taskIds.length - 1]];
      }

      // Chain from previous group
      if (lastGroupNodes.length > 0) {
        lastGroupNodes.forEach(function(ln) {
          groupFirstNodes.forEach(function(fn) {
            lines.push('    ' + ln + ' --> ' + fn);
          });
        });
      }
      lastGroupNodes = groupLastNodes;
    });

    lines.push('    end');

    // Task status styling
    tasks.forEach(function(task, j) {
      var tId = subId + '_T' + (j + 1);
      if (task.status === 'done') {
        lines.push('    style ' + tId + ' ' + colors.done);
      } else if (task.status === 'in_progress') {
        lines.push('    style ' + tId + ' ' + colors.progress);
      }
    });

    // Default style for pending tasks (ensure visibility)
    tasks.forEach(function(task, j) {
      var tId = subId + '_T' + (j + 1);
      if (!task.status || task.status === 'pending') {
        lines.push('    style ' + tId + ' ' + colors.pending);
      }
    });

    // Chain from previous sub-phase
    if (lastSubPhaseNodes.length > 0 && groupOrder.length > 0) {
      var firstGroup = groupMap[groupOrder[0]];
      var firstGroupIsParallel = firstGroup.length > 1;
      var entryNodes = firstGroupIsParallel ? [subId + '_G0_fork'] : [subId + '_T' + (firstGroup[0].index + 1)];
      lastSubPhaseNodes.forEach(function(ln) {
        entryNodes.forEach(function(en) {
          lines.push('    ' + ln + ' --> ' + en);
        });
      });
    }
    lastSubPhaseNodes = lastGroupNodes || [];
  });

  return lines.join('\n');
}

async function renderMermaidDiagram() {
  const container = document.getElementById('planDiagram');
  if (!container || typeof mermaid === 'undefined') return;

  const definition = buildMermaidDiagram('LR');
  if (!definition) {
    if (_lastMermaidDiagramSignature !== 'empty') {
      container.innerHTML = '';
      _lastMermaidDiagramSignature = 'empty';
    }
    return;
  }

  var signature = _hashString(definition + '|' + (state.phase || '') + '|' + _currentThemeName());
  if (signature === _lastMermaidDiagramSignature) return;
  _lastMermaidDiagramSignature = signature;

  try {
    const { svg } = await mermaid.render('planMermaid', definition);
    container.innerHTML = svg;
    var svgEl = container.querySelector('svg');
    diagramScale = 1;
    if (svgEl) {
      _attachNodeTooltips(svgEl);
      polishDiagramSvg(svgEl);
    }
    var label = document.getElementById('diagramZoomLevel');
    if (label) label.textContent = '100%';
  } catch (e) {
    console.error('Mermaid render failed:', e);
    container.innerHTML = '<div class="empty">' + t('plan.diagramRenderFailed') + '</div>';
  }
}

function _attachNodeTooltips(svgEl) {
  Object.keys(_diagramTooltips).forEach(function(nodeId) {
    var node = svgEl.querySelector('[id="' + nodeId + '"]') || svgEl.querySelector('[id*="-' + nodeId + '-"]');
    if (!node || node.querySelector(':scope > title')) return;
    var title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = _diagramTooltips[nodeId];
    node.insertBefore(title, node.firstChild);
  });
}

// ═══════════════════════════════════════════════
//  DIAGRAM FULLSCREEN OVERLAY
// ═══════════════════════════════════════════════

var _overlayZoom = 100;

function expandDiagram(containerId) {
  var source = document.getElementById(containerId);
  if (!source) return;

  var overlay = document.getElementById('diagramOverlay');
  var body = document.getElementById('diagramOverlayBody');
  body.innerHTML = '';

  if (containerId === 'planDiagram') {
    var definition = buildMermaidDiagram('TD');
    if (definition) {
      var wrapper = document.createElement('div');
      wrapper.className = 'diagram-overlay-diagram';
      wrapper.style.cssText = 'width: 100%; overflow: visible; cursor: grab;';
      body.appendChild(wrapper);

      // Replace literal \n with <br/> for Mermaid line breaks
      var processedDef = definition.replace(/\\n/g, '<br/>');

      mermaid.render('overlayPlanMermaid', processedDef).then(function(result) {
        wrapper.innerHTML = result.svg;
        _overlayZoom = 100;
        _applyOverlayZoom();
      });

      overlay.style.display = 'flex';
      return;
    }
  }

  var sections = source.querySelectorAll('.diagram-section');
  if (sections.length > 0) {
    // Multi-diagram: re-render each
    var titles = source.querySelectorAll('.diagram-subtitle');
    var promises = [];
    sections.forEach(function(section, i) {
      if (titles[i]) {
        body.appendChild(titles[i].cloneNode(true));
      }
      var wrapper = document.createElement('div');
      wrapper.className = 'diagram-overlay-diagram';
      wrapper.style.cssText = 'width: 100%; overflow: visible; cursor: grab;';
      body.appendChild(wrapper);

      // Get the original mermaid source from the section's data attribute or re-extract
      var origSvg = section.querySelector('svg');
      if (origSvg) {
        var clone = origSvg.cloneNode(true);
        // Give unique IDs to avoid conflicts
        var newId = 'overlay_' + containerId + '_' + i;
        _deduplicateSvgIds(clone, newId);
        wrapper.appendChild(clone);
      }
    });
  } else {
    // Single diagram
    var svg = source.querySelector('svg');
    if (svg) {
      var wrapper = document.createElement('div');
      wrapper.className = 'diagram-overlay-diagram';
      wrapper.style.cssText = 'width: 100%; overflow: visible; cursor: grab;';
      var clone = svg.cloneNode(true);
      _deduplicateSvgIds(clone, 'overlay_' + containerId);
      wrapper.appendChild(clone);
      body.appendChild(wrapper);
    }
  }

  _overlayZoom = 100;
  _applyOverlayZoom();
  overlay.style.display = 'flex';
}

function _deduplicateSvgIds(svgEl, prefix) {
  // Replace all id attributes and their references within the SVG
  var allIds = svgEl.querySelectorAll('[id]');
  var idMap = {};
  allIds.forEach(function(el) {
    var oldId = el.getAttribute('id');
    var newId = prefix + '_' + oldId;
    idMap[oldId] = newId;
    el.setAttribute('id', newId);
  });

  // Update all url(#...) references in the SVG
  var svgHtml = svgEl.innerHTML;
  Object.keys(idMap).forEach(function(oldId) {
    // Replace url(#oldId) with url(#newId)
    svgHtml = svgHtml.split('url(#' + oldId + ')').join('url(#' + idMap[oldId] + ')');
    // Replace href="#oldId" with href="#newId"
    svgHtml = svgHtml.split('href="#' + oldId + '"').join('href="#' + idMap[oldId] + '"');
    svgHtml = svgHtml.split("href='#" + oldId + "'").join("href='#" + idMap[oldId] + "'");
  });
  svgEl.innerHTML = svgHtml;

  // Fix style tags — they reference IDs
  var styles = svgEl.querySelectorAll('style');
  styles.forEach(function(styleEl) {
    var css = styleEl.textContent;
    Object.keys(idMap).forEach(function(oldId) {
      css = css.split('#' + oldId).join('#' + idMap[oldId]);
    });
    styleEl.textContent = css;
  });
}

function closeDiagramOverlay(e) {
  if (e && e.target !== document.getElementById('diagramOverlay')) return;
  document.getElementById('diagramOverlay').style.display = 'none';
}

function overlayZoom(delta) {
  _overlayZoom = Math.max(40, Math.min(300, _overlayZoom + delta));
  _applyOverlayZoom();
}

function _applyOverlayZoom() {
  var body = document.getElementById('diagramOverlayBody');
  if (body) {
    body.style.zoom = (_overlayZoom / 100);
  }
  var label = document.getElementById('overlayZoomLevel');
  if (label) label.textContent = _overlayZoom + '%';
}

function togglePlanTask(headerEl, e) {
  if (e && e.target && e.target.closest && e.target.closest('.comment-icon')) return;
  var taskDiv = headerEl && headerEl.parentElement;
  if (taskDiv) taskDiv.classList.toggle('expanded');
}

function _taskStateClass(status) {
  if (status === 'done') return ' done';
  if (status === 'in_progress') return ' run';
  return '';
}

function _buildPlanTaskHtml(item, itemIndex, task, taskIndex) {
  var commentTarget = 'task:' + task.title;
  var taskKey = (item.id || ('group' + itemIndex)) + '::' + taskIndex;
  var mark = task.status === 'done' ? cpIcon('check', 12) : '';

  var headerHtml = '<div class="task plan-task-header' + _taskStateClass(task.status) + '" onclick="togglePlanTask(this, event)">' +
    '<span class="bx">' + mark + '</span>' +
    '<span class="grow brk plan-task-title">' + escapeHtml(task.title) + '</span>' +
    (task.agent ? '<span class="tag">' + escapeHtml(task.agent) + '</span>' : '') +
    renderCommentIcon('plan', commentTarget) +
    '</div>';

  var detailHtml = '<div class="plan-task-detail">';
  if (task.description) detailHtml += '<div class="plan-task-description">' + escapeHtml(task.description) + '</div>';
  if (task.files && task.files.length > 0) detailHtml += '<div class="plan-task-files">' + task.files.map(escapeHtml).join(', ') + '</div>';
  detailHtml += '</div>';

  return '<div class="plan-task" data-task-key="' + escapeHtml(taskKey) + '">' + headerHtml + detailHtml + '</div>';
}

function _buildPlanScopeHtml(item) {
  var itemScope = (LOCK_DATA.scope || {})[item.id];
  if (!itemScope) return '';
  var entries = (itemScope.must || []).map(function(path) { return '<span class="brk"><span class="plan-scope-must">◆</span> ' + escapeHtml(path) + '</span>'; })
    .concat((itemScope.may || []).map(function(path) { return '<span class="brk"><span class="plan-scope-may">◇</span> ' + escapeHtml(path) + '</span>'; }));
  return entries.length ? '<div class="mono dim plan-group-scope">' + entries.join('') + '</div>' : '';
}

function _buildPlanGroupHtml(item, itemIndex) {
  var tasks = item.tasks || [];
  var done = tasks.filter(function(task) { return task.status === 'done'; }).length;
  var groupKey = item.id || ('group-' + itemIndex);
  var isCurrent = !!(item.id && state.phase && state.phase.startsWith(item.id + '.'));

  var headerHtml = '<div class="plan-group-header">' +
    (item.id ? '<span class="tag' + (isCurrent ? ' plan-group-current' : '') + '">' + escapeHtml(item.id) + '</span>' : '') +
    '<span class="grow brk plan-group-name">' + escapeHtml(item.name || t('plan.group')) + '</span>' +
    (item.mode ? '<span class="pill info">' + escapeHtml(item.mode) + '</span>' : '') +
    '<span class="plan-group-progress">' + t('plan.progress', {done: done, total: tasks.length}) + '</span>' +
    renderCommentIcon('plan', 'subphase:' + (item.id || '')) +
    '</div>';

  var tasksHtml = tasks.map(function(task, idx) { return _buildPlanTaskHtml(item, itemIndex, task, idx); }).join('');

  return '<div class="plan-group' + (isCurrent ? ' current' : '') + '" data-group-key="' + escapeHtml(groupKey) + '">' +
    headerHtml + _buildPlanScopeHtml(item) + tasksHtml + '</div>';
}

function renderPlanDescription() {
  var container = document.getElementById('planDescription');
  if (!container) return;
  var hasItems = ((PLAN_DATA.execution || PLAN_DATA.groups || []).length) > 0;
  var text = PLAN_DATA.description;
  morphInnerHTML(container, text
    ? '<div class="inset plan-description">' + escapeHtml(text) + (hasItems ? '<span class="plan-description-comment">' + renderCommentIcon('plan', 'plan') + '</span>' : '') + '</div>'
    : '');
}

function renderPlanGate() {
  var container = document.getElementById('planGate');
  var panel = document.getElementById('panel-plan');
  if (!container) return;

  var gate = getPendingGate();
  var isPlanGate = !!gate && gate.kind === 'plan';
  if (panel) panel.classList.toggle('has-gate', isPlanGate);
  if (!isPlanGate) {
    container.innerHTML = '';
    container.dataset.gateKey = '';
    return;
  }

  if (container.dataset.gateKey !== gate.phase) {
    container.dataset.gateKey = gate.phase;
    container.innerHTML = buildGateCardHtml(gate,
      '<button class="btn onGate lg" onclick="setPlanStatus(\'rejected\')">' + escapeHtml(t(gate.config.rejectKey)) + '</button>' +
      '<button class="btn pri lg" onclick="setPlanStatus(\'approved\')">' + cpIcon('check') + escapeHtml(t(gate.config.approveKey)) + '</button>', '');
  }
  _refreshGateCardFacts(container, gate);
}

function renderPlan() {
  const container = document.getElementById('planContent');
  if (!container) return;

  renderSystemDiagram();
  renderMermaidDiagram();
  renderPlanGate();
  renderPlanDescription();

  var items = PLAN_DATA.execution || PLAN_DATA.groups || [];
  morphInnerHTML(container, items.length
    ? items.map(function(item, itemIndex) { return _buildPlanGroupHtml(item, itemIndex); }).join('')
    : '<div class="empty">' + t('plan.noTasks') + '</div>');
}

EventBus.on('state:refreshed', renderPlan);
EventBus.on('approval:changed', renderPlanGate);

document.addEventListener('workspace-reset', function() {
  _lastSystemDiagramSignature = null;
  _lastMermaidDiagramSignature = null;
});
