// ═══════════════════════════════════════════════
//  DIFF SYNTAX HIGHLIGHTING (Shiki, highlight.js fallback)
// ═══════════════════════════════════════════════
var SHIKI_MODULE_URL = 'https://esm.sh/shiki@1.29.2';
var SHIKI_LOAD_TIMEOUT_MS = 10000;
var SHIKI_THEME_NAME = 'panel-syntax';
var SHIKI_MAX_LINE_LENGTH = 2000;
var HIGHLIGHT_SLICE_BUDGET_MS = 25;
var HIGHLIGHT_PAINT_BUDGET_MS = 10;
var HIGHLIGHT_INITIAL_SLICE_LINES = 200;
var HIGHLIGHT_MIN_SLICE_LINES = 20;
var HIGHLIGHT_MAX_SLICE_LINES = 5000;
var HIGHLIGHT_PAINT_CHUNK_CELLS = 30;
var HIGHLIGHT_PAINT_MARGIN = '800px 0px';

var SYNTAX_SCOPE_CLASSES = [
  { className: 'syn-comment', scopes: ['comment', 'punctuation.definition.comment', 'string.comment'] },
  { className: 'syn-string', scopes: ['string', 'string.regexp', 'punctuation.definition.string', 'constant.character.escape'] },
  { className: 'syn-number', scopes: ['constant', 'support.constant', 'variable.other.enummember', 'constant.other.caps'] },
  { className: 'syn-keyword', scopes: ['keyword', 'storage', 'storage.type', 'storage.modifier', 'variable.language',
    'keyword.operator.new', 'keyword.operator.expression', 'keyword.operator.logical.python', 'keyword.operator.instanceof',
    'keyword.operator.wordlike', 'entity.name.tag'] },
  { className: 'syn-function', scopes: ['entity.name.function', 'support.function', 'variable.function',
    'meta.function-call.generic', 'markup.heading'] },
  { className: 'syn-type', scopes: ['entity.name.type', 'entity.name.class', 'entity.other.inherited-class', 'support.class',
    'support.type', 'storage.type.java', 'storage.type.generic.java', 'storage.type.primitive.java', 'storage.type.object.array.java',
    'storage.type.annotation', 'storage.type.groovy', 'storage.type.cs', 'entity.other.attribute-name.class.css'] },
  { className: 'syn-property', scopes: ['variable.other.property', 'variable.other.object.property', 'variable.other.member',
    'support.variable.property', 'meta.attribute.python', 'entity.other.attribute-name', 'support.type.property-name',
    'meta.object-literal.key'] },
  { className: 'syn-param', scopes: ['variable.parameter'] },
  { className: '', scopes: ['keyword.operator', 'punctuation', 'meta.template.expression', 'meta.embedded'] }
];

var CONVENTIONAL_NAMING_LANGUAGES = new Set(['kotlin', 'java', 'scala', 'groovy', 'typescript', 'tsx', 'javascript', 'jsx',
  'python', 'dart', 'swift', 'rust']);
var CONSTANT_NAME = /^[A-Z][A-Z0-9_]*[A-Z0-9]$/;
var TYPE_NAME = /^[A-Z]\w*$/;
var CAPITALISED_WORD = /\b[A-Z]\w*\b/g;

var DIFF_LANGUAGE_BY_EXTENSION = { mjs: 'javascript', cjs: 'javascript', h: 'c', hpp: 'cpp', gradle: 'groovy', htm: 'html' };
var DIFF_LANGUAGE_BY_FILENAME = { dockerfile: 'dockerfile', makefile: 'makefile' };

var _shikiPromise = null;
var _shikiLanguagePromises = {};

function _sentinelColour(index) {
  return '#' + (0x1000000 + index).toString(16).slice(1);
}

function _buildShikiTheme() {
  return {
    name: SHIKI_THEME_NAME,
    type: 'dark',
    colors: { 'editor.foreground': _sentinelColour(0), 'editor.background': '#ffffff' },
    tokenColors: SYNTAX_SCOPE_CLASSES.map(function(rule, i) {
      return { scope: rule.scopes, settings: { foreground: _sentinelColour(i + 1) } };
    })
  };
}

function _classForSentinel(colour) {
  var rule = SYNTAX_SCOPE_CLASSES[parseInt((colour || '#0').slice(1), 16) - 1];
  return rule ? rule.className : '';
}

function _rejectAfter(ms) {
  return new Promise(function(_, reject) {
    setTimeout(function() { reject(new Error('Shiki did not load within ' + ms + ' ms')); }, ms);
  });
}

function _loadShiki() {
  if (!_shikiPromise) {
    _shikiPromise = Promise.race([import(SHIKI_MODULE_URL), _rejectAfter(SHIKI_LOAD_TIMEOUT_MS)])
      .then(function(shiki) {
        return shiki.createHighlighter({ themes: [_buildShikiTheme()], langs: [] })
          .then(function(highlighter) { return { shiki: shiki, highlighter: highlighter }; });
      });
  }
  return _shikiPromise;
}

function _shikiLanguageId(shiki, alias) {
  var info = shiki.bundledLanguagesInfo.find(function(lang) {
    return lang.id === alias || (lang.aliases || []).indexOf(alias) >= 0;
  });
  return info ? info.id : null;
}

function _loadShikiLanguage(highlighter, languageId) {
  if (!_shikiLanguagePromises[languageId]) {
    _shikiLanguagePromises[languageId] = highlighter.loadLanguage(languageId);
    _shikiLanguagePromises[languageId].catch(function() { delete _shikiLanguagePromises[languageId]; });
  }
  return _shikiLanguagePromises[languageId];
}

function _diffLanguageAlias(filePath) {
  var name = filePath.split('/').pop().toLowerCase();
  if (DIFF_LANGUAGE_BY_FILENAME[name]) return DIFF_LANGUAGE_BY_FILENAME[name];
  var extension = name.indexOf('.') >= 0 ? name.split('.').pop() : '';
  return DIFF_LANGUAGE_BY_EXTENSION[extension] || extension;
}

// ─── Tokenizers: tokenize(lines, state) returns { lines: [[{ content, className }]], state } ───

function _refineConventionalName(token) {
  if (CONSTANT_NAME.test(token.content)) return { content: token.content, className: 'syn-number' };
  if (TYPE_NAME.test(token.content)) return { content: token.content, className: 'syn-type' };
  return token;
}

function _splitCapitalisedWords(content) {
  var parts = [];
  var cursor = 0;
  content.replace(CAPITALISED_WORD, function(word, offset) {
    if (offset > cursor) parts.push({ content: content.slice(cursor, offset), className: '' });
    parts.push(_refineConventionalName({ content: word, className: '' }));
    cursor = offset + word.length;
  });
  if (cursor < content.length) parts.push({ content: content.slice(cursor), className: '' });
  return parts;
}

// Grammars leave constructor calls, static receivers and constants untagged or tagged as plain calls;
// the panel follows IDE conventions where PascalCase reads as a type and UPPER_SNAKE as a constant.
function _applyNamingConventions(token) {
  if (token.className === '') return _splitCapitalisedWords(token.content);
  if (token.className === 'syn-function' || token.className === 'syn-property') return [_refineConventionalName(token)];
  return [token];
}

function _shikiTokenizer(highlighter, languageId) {
  var followsConventions = CONVENTIONAL_NAMING_LANGUAGES.has(languageId);
  return {
    isIncremental: true,
    tokenize: function(lines, grammarState) {
      var result = highlighter.codeToTokens(lines.join('\n'), {
        lang: languageId, theme: SHIKI_THEME_NAME, grammarState: grammarState, tokenizeMaxLineLength: SHIKI_MAX_LINE_LENGTH
      });
      var tokenLines = result.tokens.map(function(line) {
        var tokens = line.map(function(t) { return { content: t.content, className: _classForSentinel(t.color) }; });
        return followsConventions ? tokens.flatMap(_applyNamingConventions) : tokens;
      });
      return { lines: tokenLines, state: result.grammarState };
    }
  };
}

function _hljsTokenLines(html) {
  var holder = document.createElement('template');
  holder.innerHTML = html;
  var lines = [[]];
  (function collect(node, className) {
    node.childNodes.forEach(function(child) {
      if (child.nodeType !== Node.TEXT_NODE) { collect(child, child.className || className); return; }
      child.data.split('\n').forEach(function(part, i) {
        if (i > 0) lines.push([]);
        if (part) lines[lines.length - 1].push({ content: part, className: className });
      });
    });
  })(holder.content, '');
  return lines;
}

function _hljsTokenizer(language) {
  return {
    isIncremental: false,
    tokenize: function(lines) {
      var html = hljs.highlight(lines.join('\n'), { language: language, ignoreIllegals: true }).value;
      return { lines: _hljsTokenLines(html), state: undefined };
    }
  };
}

function _hljsTokenizerFor(alias) {
  return typeof hljs !== 'undefined' && hljs.getLanguage(alias) ? _hljsTokenizer(alias) : null;
}

async function _diffTokenizerFor(alias) {
  if (!alias) return null;
  try {
    var loaded = await _loadShiki();
    var languageId = _shikiLanguageId(loaded.shiki, alias);
    if (!languageId) return _hljsTokenizerFor(alias);
    await _loadShikiLanguage(loaded.highlighter, languageId);
    return _shikiTokenizer(loaded.highlighter, languageId);
  } catch (e) {
    console.warn('Shiki unavailable for "' + alias + '", diff falls back to highlight.js:', e.message);
    return _hljsTokenizerFor(alias);
  }
}

// ─── Diff DOM: each hunk side becomes one tokenizable block of code cells ───

function _codeTextNodes(ctn) {
  var walker = document.createTreeWalker(ctn, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: function(node) {
      if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;
      return node.tagName === 'INS' || node.tagName === 'DEL' ? NodeFilter.FILTER_SKIP : NodeFilter.FILTER_REJECT;
    }
  });
  var nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  return nodes;
}

function _codeCell(ctn, isPainted) {
  var text = _codeTextNodes(ctn).map(function(node) { return node.data; }).join('');
  return { ctn: ctn, text: text, isPainted: isPainted };
}

function _rowSides(codeTd, tableSide) {
  if (codeTd.classList.contains('d2h-del')) return ['old'];
  if (codeTd.classList.contains('d2h-ins')) return ['new'];
  if (!codeTd.classList.contains('d2h-cntx')) return [];
  return tableSide ? [tableSide] : ['old', 'new'];
}

function _tableSide(tbody) {
  var side = tbody.closest('.d2h-file-side-diff');
  if (!side) return null;
  return side === side.parentNode.querySelector('.d2h-file-side-diff') ? 'old' : 'new';
}

// Line-by-line context rows join both hunk sides as tokenizer context but are painted once, from the new side.
function _collectTableBlocks(tbody, blocks) {
  var tableSide = _tableSide(tbody);
  var hunk = null;
  Array.prototype.forEach.call(tbody.children, function(tr, rowIndex) {
    if (tr.querySelector('td.d2h-info')) { hunk = null; return; }
    var ctn = tr.querySelector('.d2h-code-line-ctn, .d2h-code-side-line-ctn');
    if (!ctn) return;
    if (!hunk) {
      hunk = { old: { firstRow: rowIndex, cells: [] }, new: { firstRow: rowIndex, cells: [] } };
      blocks.push(hunk.old, hunk.new);
    }
    var codeTd = ctn.closest('td');
    var isSharedContext = tableSide === null && codeTd.classList.contains('d2h-cntx');
    _rowSides(codeTd, tableSide).forEach(function(side) {
      hunk[side].cells.push(_codeCell(ctn, !(isSharedContext && side === 'old')));
    });
  });
}

function _collectDiffBlocks(root) {
  var blocks = [];
  root.querySelectorAll('.d2h-diff-tbody').forEach(function(tbody) { _collectTableBlocks(tbody, blocks); });
  return blocks
    .filter(function(block) { return block.cells.length > 0; })
    .sort(function(a, b) { return a.firstRow - b.firstRow; });
}

// ─── Painting: wrap token ranges inside existing text nodes so <ins>/<del> and annotations stay intact ───

function _classRanges(tokens) {
  var ranges = [];
  var offset = 0;
  tokens.forEach(function(token) {
    if (token.className) ranges.push({ start: offset, end: offset + token.content.length, className: token.className });
    offset += token.content.length;
  });
  return ranges;
}

function _paintedFragment(text, nodeStart, ranges, firstRange) {
  var fragment = document.createDocumentFragment();
  var cursor = 0;
  for (var i = firstRange; i < ranges.length && ranges[i].start < nodeStart + text.length; i++) {
    var from = Math.max(ranges[i].start - nodeStart, 0);
    var to = Math.min(ranges[i].end - nodeStart, text.length);
    if (from > cursor) fragment.appendChild(document.createTextNode(text.slice(cursor, from)));
    var span = document.createElement('span');
    span.className = ranges[i].className;
    span.textContent = text.slice(from, to);
    fragment.appendChild(span);
    cursor = to;
  }
  if (cursor < text.length) fragment.appendChild(document.createTextNode(text.slice(cursor)));
  return fragment;
}

function _paintCell(ctn, tokens) {
  var ranges = _classRanges(tokens);
  var offset = 0;
  var rangeIndex = 0;
  _codeTextNodes(ctn).forEach(function(node) {
    var nodeStart = offset;
    offset += node.data.length;
    while (rangeIndex < ranges.length && ranges[rangeIndex].end <= nodeStart) rangeIndex++;
    if (rangeIndex >= ranges.length || ranges[rangeIndex].start >= offset) return;
    node.parentNode.replaceChild(_paintedFragment(node.data, nodeStart, ranges, rangeIndex), node);
  });
}

// ─── Pacing: work runs in time-boxed tasks so large diffs never hold the main thread for long ───

function _createPacer(budgetMs) {
  var lastYieldAt = performance.now();
  return {
    hasTimeFor: function(nextMs) { return performance.now() - lastYieldAt + nextMs <= budgetMs; },
    yieldToBrowser: function() {
      return new Promise(function(resolve) { setTimeout(resolve, 0); }).then(function() { lastYieldAt = performance.now(); });
    }
  };
}

// ─── Painting order: cells near the visible area first, then the rest in short background batches,
//     because every DOM batch relayouts the whole diff table ───

function _scrollContainer(el) {
  for (var node = el.parentElement; node && node !== document.body; node = node.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) return node;
  }
  return null;
}

function _paintCells(cells) {
  cells.forEach(function(cell) { _paintCell(cell.ctn, cell.tokens); });
}

function _chunkEdges(chunk) {
  return [chunk[0], chunk[chunk.length - 1]];
}

function _createVisibilityPainter(root) {
  var pacer = _createPacer(HIGHLIGHT_PAINT_BUDGET_MS);
  var pendingChunks = new Set();
  var chunkByCtn = new Map();
  var observer = new IntersectionObserver(function(entries) {
    if (!root.isConnected) { observer.disconnect(); return; }
    entries.forEach(function(entry) { if (entry.isIntersecting) paintChunk(chunkByCtn.get(entry.target)); });
  }, { root: _scrollContainer(root), rootMargin: HIGHLIGHT_PAINT_MARGIN });

  function paintChunk(chunk) {
    if (!chunk || !pendingChunks.delete(chunk)) return;
    _chunkEdges(chunk).forEach(function(cell) { chunkByCtn.delete(cell.ctn); observer.unobserve(cell.ctn); });
    _paintCells(chunk);
  }

  function watchChunk(chunk) {
    pendingChunks.add(chunk);
    _chunkEdges(chunk).forEach(function(cell) { chunkByCtn.set(cell.ctn, chunk); observer.observe(cell.ctn); });
  }

  return {
    watch: function(cells) {
      for (var i = 0; i < cells.length; i += HIGHLIGHT_PAINT_CHUNK_CELLS) watchChunk(cells.slice(i, i + HIGHLIGHT_PAINT_CHUNK_CELLS));
    },
    paintRemaining: async function() {
      for (var chunk of pendingChunks) {
        if (!pacer.hasTimeFor(0)) await pacer.yieldToBrowser();
        if (!root.isConnected) break;
        paintChunk(chunk);
      }
      observer.disconnect();
    },
    stop: function() { observer.disconnect(); }
  };
}

// ─── Tokenizing: adaptive slices; cells tokenized before the first yield paint at once so the opening view never flashes plain ───

function _nextSliceLines(sliceLines, elapsedMs) {
  var scaled = Math.round(sliceLines * HIGHLIGHT_SLICE_BUDGET_MS / Math.max(elapsedMs, 1));
  return Math.min(HIGHLIGHT_MAX_SLICE_LINES, Math.max(HIGHLIGHT_MIN_SLICE_LINES, scaled));
}

function _tokenizeSlice(tokenizer, cells, grammarState) {
  var result = tokenizer.tokenize(cells.map(function(cell) { return cell.text; }), grammarState);
  cells.forEach(function(cell, i) { cell.tokens = result.lines[i] || []; });
  return result.state;
}

function _deliverSlice(cells, run) {
  var paintable = cells.filter(function(cell) { return cell.isPainted; });
  if (run.paintsEagerly) _paintCells(paintable);
  else run.painter.watch(paintable);
}

async function _tokenizeBlock(root, tokenizer, cells, run) {
  var grammarState;
  var start = 0;
  while (start < cells.length) {
    if (!run.pacer.hasTimeFor(run.lastSliceMs)) {
      await run.pacer.yieldToBrowser();
      run.paintsEagerly = false;
      if (!root.isConnected) return false;
    }
    var end = tokenizer.isIncremental ? start + run.sliceLines : cells.length;
    var startedAt = performance.now();
    grammarState = _tokenizeSlice(tokenizer, cells.slice(start, end), grammarState);
    _deliverSlice(cells.slice(start, end), run);
    run.lastSliceMs = performance.now() - startedAt;
    run.sliceLines = _nextSliceLines(run.sliceLines, run.lastSliceMs);
    start = end;
  }
  return true;
}

async function highlightDiffSyntax(root, filePath) {
  var tokenizer = await _diffTokenizerFor(_diffLanguageAlias(filePath));
  if (!tokenizer || !root.isConnected) return;
  var blocks = _collectDiffBlocks(root);
  var run = {
    pacer: _createPacer(HIGHLIGHT_SLICE_BUDGET_MS),
    painter: _createVisibilityPainter(root),
    sliceLines: HIGHLIGHT_INITIAL_SLICE_LINES,
    lastSliceMs: 0,
    paintsEagerly: true
  };
  for (var i = 0; i < blocks.length; i++) {
    if (!(await _tokenizeBlock(root, tokenizer, blocks[i].cells, run))) { run.painter.stop(); return; }
  }
  await run.painter.paintRemaining();
}
