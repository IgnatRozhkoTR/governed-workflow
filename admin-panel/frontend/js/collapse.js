// ═══════════════════════════════════════════════
//  COLLAPSIBLE DESKTOP PANELS
//  The workspace sidebar and the terminal sessions
//  list fold into thin rails. Each panel remembers
//  its state per browser; phones ignore it.
// ═══════════════════════════════════════════════
var COLLAPSE_TRANSITION_MS = 200;

function initCollapsiblePanel(panel) {
  _applyPanelCollapsed(panel, _loadPanelCollapsed(panel));
}

function togglePanelCollapsed(panel) {
  var isCollapsed = !_isPanelCollapsed(panel);
  _savePanelCollapsed(panel, isCollapsed);
  _applyPanelCollapsed(panel, isCollapsed);
  setTimeout(panel.onSettled, COLLAPSE_TRANSITION_MS);
}

function _isPanelCollapsed(panel) {
  return document.getElementById(panel.hostId).classList.contains(panel.hostClass);
}

function _applyPanelCollapsed(panel, isCollapsed) {
  document.getElementById(panel.hostId).classList.toggle(panel.hostClass, isCollapsed);
  var toggle = document.getElementById(panel.toggleId);
  var labelKey = isCollapsed ? panel.expandKey : panel.collapseKey;
  toggle.setAttribute('aria-expanded', String(!isCollapsed));
  toggle.dataset.i18nTitle = labelKey;
  toggle.dataset.i18nAriaLabel = labelKey;
  toggle.title = t(labelKey);
  toggle.setAttribute('aria-label', t(labelKey));
}

function _loadPanelCollapsed(panel) {
  try {
    var stored = localStorage.getItem(panel.storageKey);
    return stored === null ? panel.collapsedByDefault : stored === '1';
  } catch (e) {
    console.warn('Panel state unavailable for ' + panel.storageKey + ':', e.message);
    return panel.collapsedByDefault;
  }
}

function _savePanelCollapsed(panel, isCollapsed) {
  try {
    localStorage.setItem(panel.storageKey, isCollapsed ? '1' : '0');
  } catch (e) {
    console.warn('Panel state not saved for ' + panel.storageKey + ':', e.message);
  }
}
