// ═══════════════════════════════════════════════
//  CHECKPOINT ICONS
//  Stroke icons on a 20x20 grid, drawn in currentColor.
// ═══════════════════════════════════════════════
var CP_ICON_PATHS = {
  back: 'M12.5 4.5 7 10l5.5 5.5',
  bell: 'M5.5 14V9a4.5 4.5 0 0 1 9 0v5l1.5 1.5H4zM8.5 17.5h3',
  changes: 'M7 6l-4 4 4 4M13 6l4 4-4 4',
  x: 'M5 5l10 10M15 5L5 15',
  comment: 'M4 5.5C4 4.7 4.7 4 5.5 4h9c.8 0 1.5.7 1.5 1.5v6c0 .8-.7 1.5-1.5 1.5H9l-3 3v-3h-.5C4.7 13 4 12.3 4 11.5z',
  flag: 'M5 17V3.5M5 4h9l-2 3 2 3H5',
  expand: 'M12 4h4v4M8 16H4v-4M16 4l-5 5M4 16l5-5',
  trash: 'M4 6h12M8 6V4h4v2M6 6l.7 10h6.6L14 6',
  check: 'M4 10.5 8 14.5 16 5.5',
  chevronDown: 'M4 7.5l6 6 6-6',
  chevronRight: 'M7.5 4l6 6-6 6',
  folder: 'M3 6.5A1.5 1.5 0 0 1 4.5 5H8l1.5 2h6A1.5 1.5 0 0 1 17 8.5v6a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z',
  list: 'M5 5h10M5 10h10M5 15h6',
  moon: 'M15.5 11.5A6 6 0 0 1 8.5 4.5a6 6 0 1 0 7 7z',
  more: 'M10 4.5h.01M10 10h.01M10 15.5h.01',
  overview: 'M4 4h5v5H4zM11 4h5v5h-5zM4 11h5v5H4zM11 11h5v5h-5z',
  play: 'M6.5 4.5v11l9-5.5z',
  plus: 'M10 4v12M4 10h12',
  servers: 'M4 4.5h12v4.5H4zM4 11h12v4.5H4zM6.5 6.8h.01M6.5 13.3h.01',
  setup: 'M4 6h8M15 6h1M4 14h1M8 14h8M12 4.5v3M8 12.5v3',
  split: 'M3.5 4.5h13v11h-13zM10.5 4.5v11',
  sun: 'M10 2.5v1.5M10 16v1.5M2.5 10H4M16 10h1.5M4.7 4.7l1 1M14.3 14.3l1 1M4.7 15.3l1-1M14.3 5.7l1-1M10 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z',
  terminal: 'M4 6l4 4-4 4M10.5 14.5H16'
};

function cpIcon(name, size) {
  var px = size || 16;
  var path = CP_ICON_PATHS[name];
  if (!path) throw new Error('Unknown icon: ' + name);
  var strokeWidth = name === 'more' ? 3.2 : 2;
  return '<svg class="ico" width="' + px + '" height="' + px + '" viewBox="0 0 20 20" aria-hidden="true" style="stroke-width:' + strokeWidth + '">' +
    '<path d="' + path + '"/></svg>';
}

function cpGateIcon(size) {
  var px = size || 20;
  return '<svg width="' + px + '" height="' + px + '" viewBox="0 0 20 20" aria-hidden="true">' +
    '<rect x="4.5" y="3.5" width="4" height="13" rx="1" fill="currentColor"/>' +
    '<rect x="11.5" y="3.5" width="4" height="13" rx="1" fill="currentColor"/></svg>';
}

function hydrateStaticIcons(root) {
  (root || document).querySelectorAll('[data-icon]').forEach(function(el) {
    if (el.querySelector('svg')) return;
    el.insertAdjacentHTML('afterbegin', cpIcon(el.dataset.icon, Number(el.dataset.iconSize) || 16));
  });
}
