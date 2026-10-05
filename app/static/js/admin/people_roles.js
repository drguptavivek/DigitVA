// People & roles panel (digitva-nk1). Read-only: fills #panel-people-roles from
// GET /api/v1/projects/<id>/people-roles. Every server string goes in through
// textContent; the server decides what the viewer may see (names, emails,
// audit columns), this file only draws what came back.
(function () {
  'use strict';

  var panel = document.getElementById('panel-people-roles');
  if (!panel || panel.dataset.initialized) return;
  panel.dataset.initialized = '1';

  var PAGE_SIZE = 100;
  var SYMBOL = { granted: '●', hollow: '○', view_only: '◐', inactive: '⊘' };
  var COLOUR = { granted: 'text-success', hollow: 'text-danger', view_only: 'text-secondary', inactive: 'text-secondary' };
  var FLAG_LABEL = {
    exceeds_grid: 'Exceeds grid', no_cadre: 'No cadre', inactive_user: 'Inactive user',
    inactive_unit: 'Inactive unit', no_active_grant: 'No active grant', dormant: 'Dormant'
  };
  var NOT_RECORDED = 'not recorded';

  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function words(value) { return String(value).replace(/_/g, ' '); }

  var TZ = panel.dataset.userTz || 'Asia/Kolkata';
  var dateTime;
  try {
    dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: TZ });
  } catch (e) {
    dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' });
  }
  function when(iso) {
    var parsed = iso ? new Date(iso) : null;
    return parsed && !isNaN(parsed) ? dateTime.format(parsed) : null;
  }

  var state = {
    project: '', offset: 0, token: 0, timer: null,
    units: [], levels: [], byPath: {}, viewer: null
  };

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status === 404 ? 'not_found' : 'failed');
        return response.json();
      });
  }

  function showError(message) {
    var box = $('pr-error');
    box.textContent = message || '';
    box.classList.toggle('d-none', !message);
  }

  // ── filters ────────────────────────────────────────────────────────────────

  function unitPickers() { return Array.prototype.slice.call($('pr-unit-pickers').querySelectorAll('select')); }

  function chosenUnit() {
    var chosen = '';
    unitPickers().forEach(function (select) { if (select.value) chosen = select.value; });
    return chosen;
  }

  function fillSelect(select, first, options, keep) {
    select.replaceChildren();
    select.appendChild(new Option(first, ''));
    options.forEach(function (o) { select.appendChild(new Option(o[1], o[0])); });
    select.value = options.some(function (o) { return o[0] === keep; }) ? keep : '';
  }

  // One picker per level, each narrowed to the units under the nearest
  // shallower choice.
  function buildUnitPickers() {
    var host = $('pr-unit-pickers');
    var kept = unitPickers().map(function (s) { return s.value; });
    host.replaceChildren();
    state.levels.forEach(function (level, i) {
      var wrap = el('div', 'col-6 col-md-3 col-xl-2');
      var label = el('label', 'form-label small mb-0', level.level_name);
      var select = el('select', 'form-select form-select-sm');
      select.id = 'pr-unit-' + i;
      label.htmlFor = select.id;
      select.dataset.level = level.level_code;
      select.addEventListener('change', function () { refreshUnitPickers(); changed(); });
      wrap.appendChild(label);
      wrap.appendChild(select);
      host.appendChild(wrap);
    });
    refreshUnitPickers(kept);
  }

  function refreshUnitPickers(kept) {
    var ancestorPath = '';
    var byId = {};
    state.units.forEach(function (u) { byId[u.org_unit_id] = u; });
    unitPickers().forEach(function (select, i) {
      var keep = kept ? kept[i] : select.value;
      var options = state.units
        .filter(function (u) {
          return u.level_code === select.dataset.level &&
            (!ancestorPath || u.path.indexOf(ancestorPath + '.') === 0);
        })
        .map(function (u) {
          return [u.org_unit_id, u.unit_code + ' ' + u.unit_name + (u.is_active ? '' : ' (inactive)')];
        });
      fillSelect(select, 'Any', options, keep);
      if (select.value && byId[select.value]) ancestorPath = byId[select.value].path;
    });
    $('pr-mode').disabled = !chosenUnit();
  }

  function query(extra) {
    var params = new URLSearchParams();
    var set = function (name, value) { if (value) params.set(name, value); };
    set('level', $('pr-level').value);
    var unit = chosenUnit();
    set('unit', unit);
    if (unit) set('mode', $('pr-mode').value);
    set('cadre', $('pr-cadre').value);
    set('capability', $('pr-capability').value);
    if (state.viewer && state.viewer.identity) set('status', $('pr-status').value);
    set('q', $('pr-q').value.trim());
    Object.keys(extra || {}).forEach(function (k) { params.set(k, extra[k]); });
    return params.toString();
  }

  function projectUrl(template, qs) {
    return template.replace('__PROJECT__', encodeURIComponent(state.project)) + (qs ? '?' + qs : '');
  }

  function changed() {
    state.offset = 0;
    load();
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  function pathCodes(path) {
    var labels = String(path || '').split('.');
    return labels.map(function (label, i) {
      var unit = state.byPath[labels.slice(0, i + 1).join('.')];
      return unit ? unit.unit_code : label;
    }).join(' > ');
  }

  function locationCell(loc) {
    var cell = el('td');
    if (loc.kind === 'unit') {
      cell.appendChild(el('div', 'fw-semibold', pathCodes(loc.path)));
      var name = el('div', 'text-muted', loc.unit_name);
      name.title = loc.level_name;
      cell.appendChild(name);
    } else if (loc.kind === 'site') {
      cell.appendChild(el('div', 'fw-semibold', loc.site_name));
      cell.appendChild(el('div', 'text-muted', loc.site_id));
    } else {
      cell.appendChild(el('div', 'fw-semibold', loc.kind === 'platform' ? 'Platform' : 'Whole project'));
    }
    return cell;
  }

  function personCell(person, grants) {
    var cell = el('td');
    var line = el('div', 'fw-semibold', person.name);
    if (!person.active) line.appendChild(el('span', 'badge text-bg-secondary ms-1', 'Deactivated'));
    cell.appendChild(line);
    if (person.email) cell.appendChild(el('div', 'text-muted', person.email));
    if (person.job_title) cell.appendChild(el('div', 'text-muted', person.job_title));
    var held = grants.map(function (g) { return words(g.role) + (g.status === 'active' ? '' : ' (deactivated)'); });
    if (held.length) cell.appendChild(el('div', 'text-muted fst-italic', held.join(', ')));
    return cell;
  }

  // Colour is never the only signal: a symbol, a title and an aria-label.
  function capabilityCell(column, cell) {
    var td = el('td', 'text-center');
    if (cell.state === 'blank') return td;
    var roles = (cell.roles || []).map(words).join(', ');
    var text = {
      granted: 'granted' + (roles ? ' by ' + roles : ''),
      hollow: 'may be given for this cadre at this level, not granted',
      view_only: 'view only' + (roles ? ' (' + roles + ' above the coding level)' : ''),
      inactive: 'inactive' + (roles ? ' (' + roles + ')' : '')
    }[cell.state] || cell.state;
    var mark = el('span', 'fw-bold ' + (COLOUR[cell.state] || ''), SYMBOL[cell.state] || '?');
    var label = column.label + ': ' + text;
    mark.title = label;
    mark.setAttribute('role', 'img');
    mark.setAttribute('aria-label', label);
    td.appendChild(mark);
    return td;
  }

  function auditCells(row, tr, dormantDays) {
    var audit = row.audit;
    if (!audit) {
      var empty = el('td', 'text-muted', '—');
      empty.colSpan = 3;
      tr.appendChild(empty);
      return;
    }
    var granted = el('td');
    granted.appendChild(el('div', null, when(audit.granted_at) || NOT_RECORDED));
    granted.appendChild(el('div', 'text-muted', audit.granted_by ? 'by ' + audit.granted_by : 'by ' + NOT_RECORDED));
    tr.appendChild(granted);
    tr.appendChild(el('td', null, when(audit.last_sign_in_at) || NOT_RECORDED));
    var flags = el('td');
    (audit.flags || []).forEach(function (flag) {
      var text = FLAG_LABEL[flag] || words(flag);
      if (flag === 'dormant') text += ' (' + dormantDays + ' days)';
      flags.appendChild(el('span', 'badge text-bg-warning me-1', text));
    });
    tr.appendChild(flags);
  }

  function renderHead(data, audit) {
    var tr = el('tr');
    ['Person', 'Cadre', 'Unit / site', 'Units below'].forEach(function (text) { tr.appendChild(el('th', null, text)); });
    data.columns.forEach(function (column) {
      var th = el('th', 'text-center');
      th.appendChild(el('div', null, column.label));
      var count = el('span', 'badge text-bg-light border', String(column.people));
      count.title = column.people + ' people have this; ' + column.hollow + ' more may be given it';
      th.appendChild(count);
      tr.appendChild(th);
    });
    if (audit) {
      ['Granted', 'Last sign-in', 'Flags'].forEach(function (text) { tr.appendChild(el('th', null, text)); });
    }
    $('pr-head').replaceChildren(tr);
  }

  function renderRows(data, audit) {
    var body = $('pr-rows');
    body.replaceChildren();
    if (!data.rows.length) {
      var tr = el('tr');
      var cell = el('td', 'text-muted', 'No one matches.');
      cell.colSpan = 4 + data.columns.length + (audit ? 3 : 0);
      tr.appendChild(cell);
      body.appendChild(tr);
      return;
    }
    data.rows.forEach(function (row) {
      var tr = el('tr');
      if (!row.person.active) tr.classList.add('table-secondary');
      tr.appendChild(personCell(row.person, row.grants || []));
      var cadre = row.cadre ? row.cadre.code + ' ' + row.cadre.name : '';
      tr.appendChild(el('td', cadre ? null : 'text-muted', cadre || '—'));
      tr.appendChild(locationCell(row.location));
      tr.appendChild(el('td', 'text-end', row.covered_below === null || row.covered_below === undefined ? '' : String(row.covered_below)));
      data.columns.forEach(function (column) { tr.appendChild(capabilityCell(column, row.cells[column.key])); });
      if (audit) auditCells(row, tr, data.dormant_days);
      body.appendChild(tr);
    });
  }

  function renderPaging(data) {
    var from = data.total ? data.offset + 1 : 0;
    var to = data.offset + data.rows.length;
    $('pr-count').textContent = 'Showing ' + from + '–' + to + ' of ' + data.total;
    $('pr-prev').disabled = data.offset <= 0;
    $('pr-next').disabled = to >= data.total;
    $('pr-truncated').classList.toggle('d-none', !data.truncated);
    $('pr-csv').href = projectUrl(panel.dataset.csvUrl, query());
  }

  // units, levels and cadres come only with the first page (offset 0); the
  // pickers are rebuilt from them then and kept across paging. Current choices
  // survive a rebuild.
  function fillStaticFilters(data) {
    state.units = data.units.units;
    state.levels = data.units.levels.slice().sort(function (a, b) { return a.depth - b.depth; });
    state.byPath = {};
    state.units.forEach(function (u) { state.byPath[u.path] = u; });
    fillSelect($('pr-level'), 'Any', state.levels.map(function (l) { return [l.level_code, l.level_name]; }), $('pr-level').value);
    fillSelect($('pr-capability'), 'Anyone',
      data.columns.map(function (c) { return [c.key, c.label]; }), $('pr-capability').value);
    fillSelect($('pr-cadre'), 'Any',
      (data.cadres || []).map(function (c) { return [c.code, c.code + ' ' + c.name]; }), $('pr-cadre').value);
    buildUnitPickers();
  }

  function render(data) {
    state.viewer = data.viewer;
    if (data.units) fillStaticFilters(data);
    $('pr-status-wrap').classList.toggle('d-none', !data.viewer.identity);
    var audit = data.viewer.audit !== 'none';
    renderHead(data, audit);
    renderRows(data, audit);
    renderPaging(data);
  }

  // ── loading ────────────────────────────────────────────────────────────────

  function load() {
    if (!state.project) return;
    var token = ++state.token;
    var qs = query({ limit: PAGE_SIZE, offset: state.offset });
    getJson(projectUrl(panel.dataset.apiUrl, qs)).then(function (data) {
      if (token !== state.token) return;
      showError('');
      $('pr-body').classList.remove('d-none');
      render(data);
    }).catch(function (err) {
      if (token !== state.token) return;
      $('pr-body').classList.add('d-none');
      showError(err.message === 'not_found'
        ? 'This project was not found, or you hold no grant in it.'
        : 'Could not load people and roles. Try again.');
    });
  }

  function resetFilters() {
    ['pr-level', 'pr-cadre', 'pr-capability', 'pr-q'].forEach(function (id) { $(id).value = ''; });
    $('pr-status').value = 'active';
    $('pr-mode').value = 'granted_here';
    state.viewer = null;
  }

  function openProject(projectId) {
    state.project = projectId;
    state.offset = 0;
    resetFilters();
    load();
  }

  ['pr-level', 'pr-cadre', 'pr-capability', 'pr-status', 'pr-mode'].forEach(function (id) {
    $(id).addEventListener('change', changed);
  });
  $('pr-q').addEventListener('input', function () {
    clearTimeout(state.timer);
    state.timer = setTimeout(changed, 300);
  });
  $('pr-prev').addEventListener('click', function () {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    load();
  });
  $('pr-next').addEventListener('click', function () {
    state.offset += PAGE_SIZE;
    load();
  });

  var locked = panel.dataset.lockedProject;
  if (locked) {
    openProject(locked);
    return;
  }
  getJson(panel.dataset.projectsUrl).then(function (data) {
    var projects = data.projects || [];
    if (!projects.length) {
      $('pr-project').parentNode.classList.add('d-none');
      $('pr-empty').classList.remove('d-none');
      return;
    }
    var select = $('pr-project');
    projects.forEach(function (p) { select.appendChild(new Option(p.project_name + ' (' + p.project_id + ')', p.project_id)); });
    var wanted = new URLSearchParams(window.location.search).get('project');
    if (wanted && projects.some(function (p) { return p.project_id === wanted; })) select.value = wanted;
    select.addEventListener('change', function () { openProject(select.value); });
    openProject(select.value);
  }).catch(function () {
    showError('Could not load your projects. Try again.');
  });
}());
