// ═══════════════════════════════════════════════
//  MONACO EDITOR
// ═══════════════════════════════════════════════

var _monacoExtensionMap = {
  py: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  jsx: 'javascript',
  tsx: 'typescript',
  java: 'java',
  rb: 'ruby',
  go: 'go',
  rs: 'rust',
  cpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  c: 'c',
  h: 'c',
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  less: 'less',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  md: 'markdown',
  markdown: 'markdown',
  xml: 'xml',
  svg: 'xml',
  sql: 'sql',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  kt: 'kotlin',
  kts: 'kotlin',
  swift: 'swift',
  dart: 'dart',
  php: 'php',
  cs: 'csharp',
  r: 'r',
  lua: 'lua',
  perl: 'perl',
  pl: 'perl',
  vue: 'html',
  svelte: 'html',
  graphql: 'graphql',
  gql: 'graphql',
  toml: 'ini',
  ini: 'ini',
  cfg: 'ini',
  dockerfile: 'dockerfile',
  makefile: 'makefile'
};

function getMonacoLanguage(filePath) {
  var name = filePath.split('/').pop().toLowerCase();
  if (name === 'dockerfile') return 'dockerfile';
  if (name === 'makefile' || name === 'gnumakefile') return 'makefile';

  var ext = name.split('.').pop();
  if (ext === name) return 'plaintext';
  return _monacoExtensionMap[ext] || 'plaintext';
}

function initMonaco() {
  require.config({
    paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs' }
  });

  window._monacoReady = new Promise(function(resolve) {
    require(['vs/editor/editor.main'], function() {
      monaco.editor.registerEditorOpener({
        openCodeEditor: function(source, resource, selectionOrPosition) {
          // Only in-document jumps are supported: the target URI must match the open
          // model's URI (Monaco auto-assigns it as `inmemory://model/N`).
          var currentEditor = window._monacoEditor;
          var currentModel = currentEditor && currentEditor.getModel();
          if (currentModel && resource.toString() === currentModel.uri.toString()) {
            if (selectionOrPosition) {
              var line = selectionOrPosition.startLineNumber || selectionOrPosition.lineNumber;
              var column = selectionOrPosition.startColumn || selectionOrPosition.column || 1;
              if (typeof line === 'number') {
                currentEditor.setPosition({ lineNumber: line, column: column });
                currentEditor.revealLineInCenter(line);
                currentEditor.focus();
              }
            }
            return true;
          }

          return false;
        }
      });

      resolve();
    });
  });
}

function _themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function _themeRule(token, name, fontStyle) {
  var rule = { token: token, foreground: _themeColor(name).replace('#', '') };
  if (fontStyle) rule.fontStyle = fontStyle;
  return rule;
}

function defineCheckpointTheme(theme) {
  var name = theme === 'dark' ? 'checkpoint-dark' : 'checkpoint-light';
  monaco.editor.defineTheme(name, {
    base: theme === 'dark' ? 'vs-dark' : 'vs',
    inherit: true,
    rules: [
      _themeRule('', '--tx'),
      _themeRule('comment', '--dim', 'italic'),
      _themeRule('keyword', '--pr'),
      _themeRule('string', '--ok'),
      _themeRule('number', '--warn'),
      _themeRule('type', '--prtx'),
      _themeRule('delimiter', '--dim'),
      _themeRule('tag', '--pr'),
      _themeRule('attribute.name', '--prtx'),
      _themeRule('attribute.value', '--ok')
    ],
    colors: {
      'editor.background': _themeColor('--sf'),
      'editor.foreground': _themeColor('--tx'),
      'editorLineNumber.foreground': _themeColor('--dim'),
      'editorLineNumber.activeForeground': _themeColor('--tx'),
      'editor.lineHighlightBackground': _themeColor('--sf2'),
      'editor.selectionBackground': _themeColor('--prbg'),
      'editorCursor.foreground': _themeColor('--pr'),
      'editorIndentGuide.background1': _themeColor('--ln'),
      'editorWidget.background': _themeColor('--sf2'),
      'editorWidget.border': _themeColor('--ln'),
      'minimap.background': _themeColor('--sf'),
      'scrollbarSlider.background': _themeColor('--sf3'),
      'editorGutter.background': _themeColor('--sf')
    }
  });
  return name;
}

function createEditor(container, content, language, filePath, readOnly) {
  if (readOnly === undefined) readOnly = true;
  return window._monacoReady.then(function() {
    if (window._monacoEditor) {
      window._monacoEditor.dispose();
      window._monacoEditor = null;
    }

    var editor = monaco.editor.create(container, {
      value: content,
      language: language,
      readOnly: readOnly,
      theme: defineCheckpointTheme(state.theme),
      automaticLayout: true,
      minimap: { enabled: !PHONE_LAYOUT_QUERY.matches },
      scrollBeyondLastLine: false,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      lineNumbers: 'on',
      renderWhitespace: 'selection',
      wordWrap: 'on'
    });

    window._monacoEditor = editor;
    window._monacoCurrentFile = filePath;

    return editor;
  });
}

function disposeEditor() {
  if (window._monacoEditor) {
    window._monacoEditor.dispose();
    window._monacoEditor = null;
  }
}

function updateEditorTheme(theme) {
  if (typeof monaco !== 'undefined') {
    monaco.editor.setTheme(defineCheckpointTheme(theme));
  }
}

function revealLine(lineNumber) {
  if (window._monacoEditor) {
    window._monacoEditor.revealLineInCenter(lineNumber);
    window._monacoEditor.setPosition({ lineNumber: lineNumber, column: 1 });
  }
}
