// Interview supervision page (/intake/supervision): cases in the caller's
// supervisor scope over GET /intake/api/supervision/cases, with resolve flag,
// mark duplicate, cancel and reopen (digitva-vzk.8, policy
// docs/policy/web-intake.md, "Supervisors").
//
// Path A rules (docs/policy/field-data-collection.md): no case data in URLs
// or browser storage; localStorage holds only the chosen tab and state.
// Every DOM write of server data goes through textContent / Option, never
// innerHTML. The server is the authority for every action shown here.
(function () {
  var ROOT = document.getElementById('sup-list');
  var CSRF = ROOT.dataset.csrf || '';
  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function stored(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) {}
    return null;
  }
  function api(url, method, body) {
    var headers = { 'X-CSRFToken': CSRF };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(url, { method: method || 'GET', headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json()
          .catch(function () { return { error: 'Unexpected response from the server (HTTP ' + r.status + ').' }; })
          .then(function (d) { return { ok: r.ok, data: d || {} }; });
      })
      .catch(function () { return { ok: false, data: { error: 'Could not reach the server.' } }; });
  }
  function alertBox(kind, msg) {
    var box = $('sup-alert');
    if (!msg) { box.classList.add('d-none'); return; }
    box.className = 'alert alert-' + kind + ' small py-2';
    box.textContent = msg;
  }

  var STATE_LABELS = [
    ['draft_identity', 'Details pending'], ['registered', 'Registered'], ['scheduled', 'Scheduled'],
    ['in_progress', 'In progress'], ['paused', 'Paused'], ['not_reachable', 'Not reachable'],
    ['refused', 'Refused'], ['submitted', 'Submitted'], ['duplicate', 'Duplicate'], ['cancelled', 'Cancelled']
  ];
  var STATE_NAME = {};
  STATE_LABELS.forEach(function (s) { STATE_NAME[s[0]] = s[1]; });
  // Mirror TRANSITIONS / TERMINAL_STATES / _FLAGGABLE in
  // app/services/case_transition_service.py, only to decide which buttons
  // to show.
  var CANCELLABLE = ['draft_identity', 'registered', 'scheduled', 'in_progress', 'paused'];
  var TERMINAL = ['submitted', 'duplicate', 'cancelled'];
  var DUPLICABLE = ['registered', 'scheduled', 'in_progress', 'paused', 'submitted'];
  var REASON_MAX = 200;
  var REASON_WARNING = 'No names, phone numbers or addresses in the reason.';

  var TAB = stored('supervision.tab') === 'all' ? 'all' : 'flags';
  var STATE = stored('supervision.state') || '';
  var NEXT_CURSOR = null, LIST_TOKEN = 0;
  var TZ = ROOT.dataset.userTz || 'Asia/Kolkata';
  var dateTimeFormat;
  try {
    dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: TZ });
  } catch (e) {
    dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' });
  }
  function formatWhen(iso) {
    var parsed = iso ? new Date(iso) : null;
    return parsed && !isNaN(parsed) ? dateTimeFormat.format(parsed) : '—';
  }

  function init() {
    var select = $('sup-state');
    select.add(new Option('Any state', ''));
    STATE_LABELS.forEach(function (s) { select.add(new Option(s[1], s[0])); });
    if (!STATE_NAME[STATE]) STATE = '';
    select.value = STATE;
    select.addEventListener('change', function () {
      STATE = select.value;
      stored('supervision.state', STATE);
      load(true);
    });
    Array.prototype.forEach.call(document.querySelectorAll('#sup-tabs [data-tab]'), function (btn) {
      btn.addEventListener('click', function () {
        TAB = btn.dataset.tab;
        stored('supervision.tab', TAB);
        load(true);
      });
    });
    $('sup-load-more').addEventListener('click', function () { load(false); });
    load(true);
  }

  function listUrl(cursor) {
    var url = '/intake/api/supervision/cases?';
    url += TAB === 'flags' ? 'flagged=true' : 'state=' + encodeURIComponent(STATE);
    return url + (cursor ? '&cursor=' + encodeURIComponent(cursor) : '');
  }

  function load(reset) {
    var token = ++LIST_TOKEN;
    var rows = $('sup-rows'), more = $('sup-load-more'), empty = $('sup-empty');
    Array.prototype.forEach.call(document.querySelectorAll('#sup-tabs [data-tab]'), function (btn) {
      var active = btn.dataset.tab === TAB;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $('sup-state-wrap').classList.toggle('d-none', TAB !== 'all');
    if (reset) { NEXT_CURSOR = null; rows.replaceChildren(); }
    more.disabled = true;
    api(listUrl(NEXT_CURSOR)).then(function (res) {
      if (token !== LIST_TOKEN) return;
      more.disabled = false;
      if (!res.ok) {
        empty.textContent = res.data.error || 'Could not load the cases.';
        empty.classList.remove('d-none');
        return;
      }
      var counts = res.data.counts || {};
      var inScope = Object.keys(counts).reduce(function (sum, k) { return sum + counts[k]; }, 0);
      empty.textContent = !inScope ? 'No cases in your supervision scope yet.'
        : TAB === 'flags' ? 'No flags waiting for you.' : 'No cases here.';
      (res.data.cases || []).forEach(function (row) { rows.appendChild(renderRow(row)); });
      NEXT_CURSOR = res.data.next_cursor || null;
      more.classList.toggle('d-none', !NEXT_CURSOR);
      empty.classList.toggle('d-none', rows.children.length > 0);
    });
  }

  function renderRow(row) {
    var item = el('li', 'list-group-item px-2 py-2');
    var head = el('div', 'd-flex justify-content-between align-items-start gap-2');
    head.appendChild(el('strong', 'text-break', row.details_pending ? 'New interview · details pending' : (row.deceased_name || '—')));
    head.appendChild(el('span', 'badge text-bg-secondary flex-shrink-0', STATE_NAME[row.state] || row.state));
    item.appendChild(head);
    item.appendChild(el('div', 'small text-break', [
      row.unique_id,
      row.deceased_sex || '—',
      row.age_years != null ? row.age_years + ' y' : 'age —',
      'died ' + (row.date_of_death || '—'),
      row.unit_name || 'no unit'
    ].join(' · ')));
    item.appendChild(el('div', 'small text-muted text-break',
      'Registered by ' + (row.registered_by_name || '—') + ' · started by ' + (row.started_by_name || '—')
      + ' · updated ' + formatWhen(row.updated_at)));
    if (row.pending_flag) {
      item.appendChild(el('div', 'small mt-1')).appendChild(el('span', 'badge text-bg-warning',
        row.pending_flag === 'duplicate' ? 'Duplicate flag waiting' : 'Cancel flag waiting'));
    }

    var actions = el('div', 'd-flex flex-wrap gap-2 mt-2');
    var panel = el('div', 'mt-2 d-none');
    if (row.pending_flag) {
      actions.appendChild(button('Confirm flag', 'btn-warning', function () {
        openForm(panel, row, 'Confirm flag', 'resolve-flag', false, { confirm: true }, 'Flag confirmed');
      }));
      actions.appendChild(button('Reject flag', 'btn-outline-secondary', function () {
        openForm(panel, row, 'Reject flag', 'resolve-flag', false, { confirm: false }, 'Flag rejected');
      }));
    } else if (DUPLICABLE.indexOf(row.state) !== -1) {
      actions.appendChild(button('Mark duplicate', 'btn-outline-secondary', function () { duplicateForm(panel, row); }));
    }
    if (CANCELLABLE.indexOf(row.state) !== -1) {
      actions.appendChild(button('Cancel case', 'btn-outline-danger', function () {
        openForm(panel, row, 'Cancel case', 'cancel', true, {}, 'Case cancelled');
      }));
    }
    if (TERMINAL.indexOf(row.state) !== -1) {
      actions.appendChild(button('Reopen', 'btn-outline-primary', function () {
        openForm(panel, row, 'Reopen case', 'reopen', true, {}, 'Case reopened');
      }));
    }
    if (actions.children.length) item.appendChild(actions);
    item.appendChild(panel);
    return item;
  }

  function button(text, style, onClick) {
    var b = el('button', 'btn btn-sm ' + style, text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  // Inline form under the row (no modal: easier on a phone). `extra(form)`
  // may add fields and returns a function giving more body fields.
  function openForm(panel, row, submitText, path, required, fixed, done, extra) {
    panel.replaceChildren();
    panel.classList.remove('d-none');
    var form = el('form', 'border rounded p-2 bg-light');
    var more = extra ? extra(form) : null;
    form.appendChild(el('label', 'form-label small mb-1', required ? 'Reason' : 'Reason (optional)'));
    var reason = el('input', 'form-control form-control-sm');
    reason.type = 'text';
    reason.maxLength = REASON_MAX;
    reason.required = required;
    reason.autocomplete = 'off';
    form.appendChild(reason);
    form.appendChild(el('div', 'form-text text-danger mb-2', REASON_WARNING));
    var buttons = el('div', 'd-flex flex-wrap gap-2');
    var submit = el('button', 'btn btn-sm btn-primary', submitText);
    submit.type = 'submit';
    buttons.appendChild(submit);
    buttons.appendChild(button('Close', 'btn-outline-secondary', function () {
      panel.replaceChildren(); panel.classList.add('d-none');
    }));
    form.appendChild(buttons);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var body = Object.assign({ reason: reason.value.trim() }, fixed, more ? more() : {});
      submit.disabled = true;
      api('/intake/api/supervision/cases/' + encodeURIComponent(row.death_id) + '/' + path, 'POST', body).then(function (res) {
        submit.disabled = false;
        if (!res.ok) { alertBox('danger', res.data.error || 'Could not save.'); return; }
        var waiting = res.data.death && res.data.death.pending_flag;
        alertBox(waiting ? 'warning' : 'success', waiting
          ? 'Case ' + row.unique_id + ' is already coded: the duplicate waits for a supervisor who is also its data manager.'
          : done + ' for case ' + row.unique_id + '.');
        load(true);
      });
    });
    panel.appendChild(form);
  }

  // The kept case comes from supervised cases of the same project; the
  // server checks both cases again.
  function duplicateForm(panel, row) {
    openForm(panel, row, 'Mark duplicate', 'duplicate', false, {}, 'Marked as duplicate', function (form) {
      form.appendChild(el('label', 'form-label small mb-1', 'Same death as case'));
      var picker = el('select', 'form-select form-select-sm mb-2');
      picker.required = true;
      picker.add(new Option('Loading cases…', ''));
      form.appendChild(picker);
      if (row.state === 'submitted') {
        form.appendChild(el('div', 'form-text text-warning mb-2',
          'This case is submitted: if it is the one already coded, keep it and mark the other case instead.'));
      }
      loadKeptOptions(picker, row);
      return function () { return { duplicate_of: picker.value }; };
    });
  }

  // ponytail: first 200 supervised cases by recent activity (the API's page
  // cap); a server-side search by case id is the upgrade when scopes grow.
  function loadKeptOptions(picker, row) {
    api('/intake/api/supervision/cases?limit=200').then(function (res) {
      picker.replaceChildren();
      if (!res.ok) { picker.add(new Option(res.data.error || 'Could not load cases.', '')); return; }
      var options = (res.data.cases || []).filter(function (c) {
        return c.death_id !== row.death_id && c.project_id === row.project_id
          && ['duplicate', 'cancelled', 'draft_identity'].indexOf(c.state) === -1;
      });
      picker.add(new Option(options.length ? 'Choose the case to keep' : 'No other case in this project', ''));
      options.forEach(function (c) {
        picker.add(new Option([c.unique_id, c.deceased_name || '—', c.date_of_death || '—'].join(' — '), c.death_id));
      });
    });
  }

  init();
}());
