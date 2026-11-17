// ═══════════════════════════════════════════════
//  CODE ANNOTATIONS (agent-written notes on line ranges)
// ═══════════════════════════════════════════════

var ANNOTATION_PREVIEW_MAX_CHARS = 120;

var _annotationCache = {};
var _annotationExpanded = {};

function _annotationCacheKey(filePath, repo, ref) {
  return [repo || '', ref || '', filePath].join('\u0000');
}

function invalidateAnnotations() {
  _annotationCache = {};
}

function loadAnnotations(filePath, repo, ref) {
  var ctx = getWorkspaceContext();
  if (!ctx) return Promise.resolve([]);
  var key = _annotationCacheKey(filePath, repo, ref);
  if (!_annotationCache[key]) {
    _annotationCache[key] = apiGetAnnotations(ctx.projectId, ctx.branch, filePath, repo, ref)
      .then(function(data) { return data.annotations || []; })
      .catch(function(e) {
        delete _annotationCache[key];
        console.warn('Annotations unavailable:', e.message);
        return [];
      });
  }
  return _annotationCache[key];
}

function annotationPreviewText(ann) {
  var firstLine = String(ann.text || '').split('\n').filter(function(l) { return l.trim(); })[0] || '';
  var plain = firstLine.replace(/[`*_#>]/g, '').trim();
  return plain.length > ANNOTATION_PREVIEW_MAX_CHARS ? plain.slice(0, ANNOTATION_PREVIEW_MAX_CHARS) + '…' : plain;
}

function annotationEndLine(ann) {
  return ann.line_end || ann.line_start;
}

function _renderAnnotationMarkdown(text) {
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    return escapeHtml(text);
  }
  return DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
}

function _annotationButton(label, className, onClick) {
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-sm ' + className;
  btn.textContent = label;
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    onClick();
  });
  return btn;
}

async function _runAnnotationRequest(request, onChanged) {
  try {
    await request();
    invalidateAnnotations();
    onChanged();
  } catch (e) {
    showToast(t('annotation.failed', { error: e.message }));
  }
}

function _buildAnnotationMeta(ann) {
  var meta = document.createElement('div');
  meta.className = 'ann-meta';
  var when = ann.updated_at || ann.created_at;
  var parts = [ann.author || '', when ? formatRelativeDate(when) : '', t('annotation.lines', { start: ann.line_start, end: annotationEndLine(ann) })];
  meta.textContent = parts.filter(Boolean).join(' · ');
  if (when) meta.title = new Date(when).toLocaleString();
  return meta;
}

function _buildAnnotationEditor(ann, handlers) {
  var wrap = document.createElement('div');
  var area = document.createElement('textarea');
  area.className = 'ann-textarea';
  area.value = ann.text || '';
  area.placeholder = t('annotation.textPlaceholder');
  area.rows = 4;
  area.addEventListener('keydown', function(e) { e.stopPropagation(); });
  var actions = document.createElement('div');
  actions.className = 'ann-actions';
  actions.appendChild(_annotationButton(t('annotation.save'), 'ann-save', function() {
    var text = area.value.trim();
    if (text) handlers.onSave(text);
  }));
  actions.appendChild(_annotationButton(t('annotation.cancel'), 'ann-cancel', handlers.onCancel));
  wrap.appendChild(area);
  wrap.appendChild(actions);
  setTimeout(function() { area.focus(); }, 0);
  return wrap;
}

function buildAnnotationBlock(ann, onChanged, onLayout) {
  var ctx = getWorkspaceContext();
  var block = document.createElement('div');
  block.className = 'ann-block' + (ann.stale ? ' ann-stale' : '');
  block.dataset.annotationId = ann.id;

  function showView() {
    block.textContent = '';
    var body = document.createElement('div');
    body.className = 'ann-body';
    body.innerHTML = _renderAnnotationMarkdown(ann.text || '');
    var actions = document.createElement('div');
    actions.className = 'ann-actions';
    actions.appendChild(_annotationButton(t('annotation.edit'), 'ann-edit', showEdit));
    actions.appendChild(_annotationButton(t('annotation.delete'), 'ann-delete', removeAnnotation));
    block.appendChild(body);
    block.appendChild(_buildAnnotationMeta(ann));
    block.appendChild(actions);
    onLayout();
  }

  function showEdit() {
    block.textContent = '';
    block.appendChild(_buildAnnotationEditor(ann, {
      onSave: function(text) {
        _runAnnotationRequest(function() {
          return apiUpdateAnnotation(ctx.projectId, ctx.branch, ann.id, { text: text });
        }, onChanged);
      },
      onCancel: showView
    }));
    onLayout();
  }

  function removeAnnotation() {
    if (!confirm(t('annotation.confirmDelete'))) return;
    _runAnnotationRequest(function() {
      return apiDeleteAnnotation(ctx.projectId, ctx.branch, ann.id);
    }, onChanged);
  }

  showView();
  return block;
}

// ─── Diff view (diff2html DOM) ───

function _isNewSideTable(table) {
  var sides = table.closest('.d2h-file-wrapper').querySelectorAll('.d2h-file-side-diff');
  return sides.length < 2 || sides[sides.length - 1].contains(table);
}

function _diffNewSideRows(container) {
  var rows = [];
  container.querySelectorAll('tbody').forEach(function(tbody) {
    if (tbody.closest('.d2h-file-side-diff') && !_isNewSideTable(tbody)) return;
    Array.prototype.forEach.call(tbody.children, function(tr) {
      var line = _newSideLineNumber(tr);
      if (line) rows.push({ tr: tr, line: line, tbody: tbody });
    });
  });
  return rows;
}

function _newSideLineNumber(tr) {
  var inlineNum = tr.querySelector('td.d2h-code-linenumber .line-num2');
  if (inlineNum) return parseInt(inlineNum.textContent, 10) || 0;
  var sideNum = tr.querySelector('td.d2h-code-side-linenumber');
  return sideNum ? parseInt(sideNum.textContent, 10) || 0 : 0;
}

function _oldSidePeer(newTr) {
  var newBody = newTr.parentNode;
  var side = newBody.closest('.d2h-file-side-diff');
  var oldSide = side && side.previousElementSibling;
  var oldBody = oldSide && oldSide.querySelector('tbody');
  if (!oldBody) return null;
  return oldBody.children[Array.prototype.indexOf.call(newBody.children, newTr)] || null;
}

function _clearDiffAnnotations(container) {
  container.querySelectorAll('.ann-row, .ann-inline').forEach(function(el) { el.remove(); });
  container.querySelectorAll('.ann-gutter').forEach(function(el) {
    el.classList.remove('ann-gutter', 'ann-gutter-stale');
  });
}

function _makeInlineAnnotationButton(ann, onToggle) {
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ann-inline' + (ann.stale ? ' ann-stale' : '');
  btn.dataset.annotationId = ann.id;
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-label', t('annotation.expand'));
  btn.title = ann.stale ? t('annotation.staleTooltip') : annotationPreviewText(ann);
  if (ann.stale) {
    var tag = document.createElement('span');
    tag.className = 'ann-stale-tag';
    tag.textContent = t('annotation.stale');
    btn.appendChild(tag);
  }
  var label = document.createElement('span');
  label.className = 'ann-inline-text';
  label.textContent = annotationPreviewText(ann);
  btn.appendChild(label);
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    onToggle(btn);
  });
  return btn;
}

function _markDiffGutter(rows, ann) {
  var end = annotationEndLine(ann);
  rows.forEach(function(row) {
    if (row.line < ann.line_start || row.line > end) return;
    var cell = row.tr.querySelector('td.d2h-code-linenumber, td.d2h-code-side-linenumber');
    cell.classList.add('ann-gutter');
    if (ann.stale) cell.classList.add('ann-gutter-stale');
  });
}

function _expandDiffAnnotation(ann, row, btn, redecorate) {
  var anchor = row.tr;
  while (anchor.nextElementSibling && anchor.nextElementSibling.classList.contains('line-comment-row')) {
    anchor = anchor.nextElementSibling;
  }
  var peer = _oldSidePeer(row.tr);
  var spacer = peer ? _createAnnotationRow(peer, null) : null;
  var annRow = _createAnnotationRow(row.tr, ann);
  var block = buildAnnotationBlock(ann, redecorate, function() {
    if (spacer) spacer.firstChild.style.height = annRow.firstChild.offsetHeight + 'px';
  });
  annRow.firstChild.appendChild(block);
  anchor.parentNode.insertBefore(annRow, anchor.nextSibling);
  if (spacer) {
    peer.parentNode.insertBefore(spacer, peer.nextSibling);
    spacer.firstChild.style.height = annRow.firstChild.offsetHeight + 'px';
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(function() {
        spacer.firstChild.style.height = annRow.firstChild.offsetHeight + 'px';
      }).observe(annRow.firstChild);
    }
    annRow._spacer = spacer;
  }
  btn.setAttribute('aria-expanded', 'true');
  btn.setAttribute('aria-label', t('annotation.collapse'));
  _annotationExpanded[ann.id] = true;
}

function _createAnnotationRow(referenceTr, ann) {
  var tr = document.createElement('tr');
  tr.className = 'ann-row';
  if (ann) tr.dataset.annotationId = ann.id;
  var td = document.createElement('td');
  td.setAttribute('colspan', referenceTr.querySelectorAll('td').length);
  td.className = 'ann-cell';
  tr.appendChild(td);
  return tr;
}

function _collapseDiffAnnotation(ann, row, btn) {
  var annRow = row.tr.parentNode.querySelector('.ann-row[data-annotation-id="' + ann.id + '"]');
  if (annRow) {
    if (annRow._spacer) annRow._spacer.remove();
    annRow.remove();
  }
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-label', t('annotation.expand'));
  delete _annotationExpanded[ann.id];
}

function _decorateDiffContainer(container, annotations, redecorate) {
  _clearDiffAnnotations(container);
  var rows = _diffNewSideRows(container);
  annotations.forEach(function(ann) {
    var endRow = rows.filter(function(r) { return r.line === annotationEndLine(ann); })[0];
    if (!endRow) return;
    _markDiffGutter(rows, ann);
    var host = endRow.tr.querySelector('.d2h-code-line, .d2h-code-side-line');
    if (!host) return;
    var btn = _makeInlineAnnotationButton(ann, function(button) {
      if (button.getAttribute('aria-expanded') === 'true') {
        _collapseDiffAnnotation(ann, endRow, button);
      } else {
        _expandDiffAnnotation(ann, endRow, button, redecorate);
      }
    });
    host.appendChild(btn);
    if (_annotationExpanded[ann.id]) _expandDiffAnnotation(ann, endRow, btn, redecorate);
  });
}

function currentDiffAnnotationRef() {
  var data = (typeof DIFF_DATA !== 'undefined' && DIFF_DATA) || {};
  return data.mode === 'commit' && data.commit ? data.commit : '';
}

function currentDiffAnnotationRepo() {
  return state.diffRepo && state.diffRepo !== '.' ? state.diffRepo : '';
}

async function decorateDiffAnnotations(container, filePath) {
  var repo = currentDiffAnnotationRepo();
  var ref = currentDiffAnnotationRef();
  async function redecorate() {
    var annotations = await loadAnnotations(filePath, repo, ref);
    if (container.isConnected) _decorateDiffContainer(container, annotations, redecorate);
  }
  await redecorate();
}

// ─── File view (Monaco) ───

function _monacoDecorationFor(ann, model) {
  var end = annotationEndLine(ann);
  var maxColumn = model.getLineMaxColumn(end);
  var prefix = ann.stale ? '[' + t('annotation.stale') + '] ' : '';
  var cls = ann.stale ? ' ann-monaco-stale' : '';
  return [
    {
      range: new monaco.Range(ann.line_start, 1, end, 1),
      options: { linesDecorationsClassName: 'ann-monaco-bar' + cls }
    },
    {
      range: new monaco.Range(end, maxColumn, end, maxColumn),
      options: {
        hoverMessage: ann.stale ? { value: t('annotation.staleTooltip') } : null,
        after: {
          content: '   ▸ ' + prefix + annotationPreviewText(ann),
          inlineClassName: 'ann-monaco-after' + cls,
          attachedData: ann.id
        }
      }
    }
  ];
}

function _attachMonacoAnnotations(editor, annotations, controller) {
  var model = editor.getModel();
  var lineCount = model.getLineCount();
  var visible = annotations.filter(function(a) { return annotationEndLine(a) <= lineCount && a.line_start >= 1; });
  var decorations = [];
  visible.forEach(function(ann) { decorations = decorations.concat(_monacoDecorationFor(ann, model)); });
  controller.annotations = visible;
  controller.decorations.set(decorations);
  visible.forEach(function(ann) {
    if (_annotationExpanded[ann.id]) _expandMonacoAnnotation(editor, controller, ann);
  });
}

function _collapseMonacoAnnotation(editor, controller, ann) {
  var zone = controller.zones[ann.id];
  if (!zone) return;
  zone.observer.disconnect();
  editor.changeViewZones(function(accessor) { accessor.removeZone(zone.id); });
  delete controller.zones[ann.id];
  delete _annotationExpanded[ann.id];
}

function _expandMonacoAnnotation(editor, controller, ann) {
  if (controller.zones[ann.id]) return;
  var domNode = document.createElement('div');
  domNode.className = 'ann-monaco-zone';
  var zone = { id: null, observer: null };
  var block = buildAnnotationBlock(ann, controller.refresh, function() {});
  domNode.appendChild(block);
  zone.observer = new ResizeObserver(function() {
    editor.changeViewZones(function(accessor) {
      var current = controller.zoneSpecs[ann.id];
      current.heightInPx = block.offsetHeight + 8;
      accessor.layoutZone(zone.id);
    });
  });
  var spec = { afterLineNumber: annotationEndLine(ann), heightInPx: 80, domNode: domNode, suppressMouseDown: true };
  controller.zoneSpecs[ann.id] = spec;
  editor.changeViewZones(function(accessor) { zone.id = accessor.addZone(spec); });
  zone.observer.observe(block);
  controller.zones[ann.id] = zone;
  _annotationExpanded[ann.id] = true;
}

function _toggleMonacoAnnotation(editor, controller, annotationId) {
  var ann = controller.annotations.filter(function(a) { return a.id === annotationId; })[0];
  if (!ann) return;
  if (controller.zones[ann.id]) {
    _collapseMonacoAnnotation(editor, controller, ann);
  } else {
    _expandMonacoAnnotation(editor, controller, ann);
  }
}

function _clearMonacoZones(editor, controller) {
  Object.keys(controller.zones).forEach(function(id) {
    controller.zones[id].observer.disconnect();
    var zoneId = controller.zones[id].id;
    editor.changeViewZones(function(accessor) { accessor.removeZone(zoneId); });
  });
  controller.zones = {};
  controller.zoneSpecs = {};
}

function _bindMonacoAnnotationInput(editor, controller) {
  editor.onMouseDown(function(e) {
    var injected = e.target.detail && e.target.detail.injectedText;
    var id = injected && injected.options && injected.options.attachedData;
    if (id != null) _toggleMonacoAnnotation(editor, controller, id);
  });
  editor.addAction({
    id: 'governed.toggleAnnotation',
    label: t('annotation.toggleAtCursor'),
    keybindings: [monaco.KeyMod.Alt | monaco.KeyCode.Enter],
    run: function() {
      var line = editor.getPosition().lineNumber;
      var ann = controller.annotations.filter(function(a) { return annotationEndLine(a) === line; })[0];
      if (ann) _toggleMonacoAnnotation(editor, controller, ann.id);
    }
  });
}

async function attachEditorAnnotations(editor, filePath) {
  var controller = { annotations: [], zones: {}, zoneSpecs: {}, decorations: editor.createDecorationsCollection([]) };
  controller.refresh = async function() {
    var annotations = await loadAnnotations(filePath, '', '');
    if (window._monacoEditor !== editor) return;
    _clearMonacoZones(editor, controller);
    _attachMonacoAnnotations(editor, annotations, controller);
  };
  _bindMonacoAnnotationInput(editor, controller);
  await controller.refresh();
}

document.addEventListener('workspace-reset', function() {
  invalidateAnnotations();
  _annotationExpanded = {};
});
