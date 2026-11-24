// ═══════════════════════════════════════════════
//  HIGHLIGHT.JS GRAMMAR EXTENSIONS
// ═══════════════════════════════════════════════
var KOTLIN_PASCAL_CASE_TYPE = { scope: 'type', match: /\b[A-Z][a-z0-9]\w*\b/ };
var _kotlinTypeHighlighters = new WeakSet();

function extendKotlinTypeNames(highlighter) {
  if (_kotlinTypeHighlighters.has(highlighter)) return;
  var kotlin = highlighter.getLanguage('kotlin');
  if (!kotlin) return;
  var baseDefinition = kotlin.rawDefinition;
  highlighter.registerLanguage('kotlin', function() {
    var language = baseDefinition();
    language.contains = language.contains.concat(KOTLIN_PASCAL_CASE_TYPE);
    return language;
  });
  _kotlinTypeHighlighters.add(highlighter);
}

if (typeof hljs !== 'undefined') extendKotlinTypeNames(hljs);
