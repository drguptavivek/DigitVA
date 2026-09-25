/*
 * Read-only tree-table over the vendored Wunderbaum (static/vendor/wunderbaum).
 *
 * Markup:
 *   <div class="tree-table" data-tree-table data-tree-data="ID"
 *        data-wb-js="..." data-wb-css="..." style="height:60vh"></div>
 *   <script type="application/json" id="ID">{"columns": [...], "nodes": [...]}</script>
 *
 * columns: [{id, title, width?}], the first is the tree column.
 * nodes: a flat list [{id, parent_id, title, expanded?, cells?: {colId: cell}}],
 * parents listed before their children. A node whose parent_id is unknown is
 * shown at the top level rather than dropped. A cell is a string, or
 * {badge, tone, note} with tone one of TONES. Every value is set as text, so
 * the data is never parsed as HTML.
 *
 * Expand/collapse all: any element with data-tree-action="expand" or
 * "collapse" and data-tree-target="<tree element id>" (one delegated listener).
 *
 * config.expand_subtree (opt-in, per table): when true, clicking a node's own
 * expander toggles its whole subtree in one action instead of one level.
 * Other tables keep Wunderbaum's default one-level toggle.
 *
 * Tables mount on page load and after an htmx swap, so the same markup works
 * in an admin panel injected after load. Wunderbaum is loaded from data-wb-js
 * / data-wb-css when it is not already on window.
 */
(function () {
  'use strict';
  if (window.DigitvaTreeTable) return;

  var TONES = { success: 1, info: 1, warning: 1, secondary: 1, danger: 1, primary: 1 };
  var loads = {};

  function loadCss(href) {
    if (!href || document.querySelector('link[href="' + href + '"]')) return;
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function loadWunderbaum(src) {
    if (window.mar10 && window.mar10.Wunderbaum) return Promise.resolve();
    if (!src) return Promise.reject(new Error('Wunderbaum is not loaded'));
    if (!loads[src]) {
      loads[src] = new Promise(function (resolve, reject) {
        var el = document.createElement('script');
        el.src = src;
        el.onload = resolve;
        el.onerror = function () { delete loads[src]; el.remove(); reject(new Error('load failed: ' + src)); };
        document.head.appendChild(el);
      });
    }
    return loads[src];
  }

  // Flat nodes -> Wunderbaum's nested source, keeping input order.
  function toSource(nodes) {
    var byId = {}, roots = [];
    nodes.forEach(function (n) {
      byId[n.id] = { key: String(n.id), title: String(n.title == null ? '' : n.title),
        expanded: !!n.expanded, cells: n.cells || {} };
    });
    nodes.forEach(function (n) {
      var node = byId[n.id], parent = n.parent_id != null ? byId[n.parent_id] : null;
      if (parent && parent !== node) (parent.children = parent.children || []).push(node);
      else roots.push(node);
    });
    return roots;
  }

  function fillCell(elem, cell) {
    elem.textContent = '';
    if (cell == null) return;
    if (typeof cell !== 'object') { elem.textContent = String(cell); return; }
    if (cell.badge) {
      var badge = document.createElement('span');
      badge.className = 'badge text-bg-' + (TONES[cell.tone] ? cell.tone : 'secondary');
      badge.textContent = String(cell.badge);
      elem.appendChild(badge);
    }
    if (cell.note) {
      var note = document.createElement('span');
      note.className = 'text-muted ms-1';
      note.textContent = String(cell.note);
      elem.appendChild(note);
    }
  }

  function render(e) {
    var node = e.node, row = e.nodeElem;
    // Wunderbaum sets no ARIA; give each row its level and open state.
    row.setAttribute('role', 'row');
    row.setAttribute('aria-level', String(node.getLevel()));
    if (node.children && node.children.length) row.setAttribute('aria-expanded', String(!!node.expanded));
    else row.removeAttribute('aria-expanded');
    var cells = node.data.cells || {};
    Object.keys(e.renderColInfosById).forEach(function (colId) {
      fillCell(e.renderColInfosById[colId].elem, cells[colId]);
    });
  }

  function mount(el) {
    if (el._treeTable || el.dataset.treeMounting) return;
    var dataEl = document.getElementById(el.dataset.treeData || '');
    if (!dataEl) return;
    var config = JSON.parse(dataEl.textContent);
    el.dataset.treeMounting = '1';
    loadCss(el.dataset.wbCss);
    loadWunderbaum(el.dataset.wbJs).then(function () {
      var columns = config.columns.map(function (col, index) {
        return { id: index === 0 ? '*' : col.id, title: col.title,
          width: col.width || (index === 0 ? '*' : '160px'), minWidth: index === 0 ? '240px' : undefined };
      });
      el.setAttribute('role', 'treegrid');
      el._treeTable = new window.mar10.Wunderbaum({
        element: el,
        id: el.id || undefined,
        source: toSource(config.nodes || []),
        columns: columns,
        iconMap: 'fontawesome6',
        icon: false,
        navigationModeOption: 'row',
        render: render,
        // Opt-in (config.expand_subtree): clicking a node's expander toggles
        // its whole subtree at once. Returning nothing (not `false`) for any
        // other click leaves Wunderbaum's own one-level toggle in place.
        click: function (e) {
          if (!config.expand_subtree || e.info.region !== 'expander') return undefined;
          var flag = !e.node.isExpanded();
          // visit() takes an options object, not includeSelf: toggle the
          // clicked node explicitly, then every descendant that has children.
          e.node.setExpanded(flag, { noAnimation: true });
          e.node.visit(function (n) {
            if (n.children && n.children.length) n.setExpanded(flag, { noAnimation: true });
          });
          return false;
        }
      });
    }).catch(function () {
      el.textContent = 'The table did not load. Reload the page.';
    }).then(function () { delete el.dataset.treeMounting; });
  }

  function mountAll(root) {
    (root || document).querySelectorAll('[data-tree-table]').forEach(mount);
  }

  document.addEventListener('click', function (ev) {
    var button = ev.target.closest('[data-tree-action]');
    if (!button) return;
    var el = document.getElementById(button.dataset.treeTarget || '');
    if (el && el._treeTable) el._treeTable.expandAll(button.dataset.treeAction === 'expand');
  });
  document.addEventListener('htmx:afterSettle', function (ev) { mountAll(ev.target); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  else mountAll();

  window.DigitvaTreeTable = { mountAll: mountAll, toSource: toSource };
})();
