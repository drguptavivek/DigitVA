/*
 * WHO VA cause definitions viewer: a filter box over the list from
 * GET /api/v1/va-definitions. Used by the coder/reviewer "VA Definitions"
 * modal (app/templates/va_form_partials/_va_definitions_modal.html) and the
 * help page (app/templates/help/pages/va-definitions.html).
 *
 * Markup: a root element holding input.va-def-filter, .va-def-status and
 * .va-def-list. DigitVADefinitions.mount(root) loads the flat, code-ordered
 * list once per page
 * (shared by every root) and filters client-side as the user types, on code,
 * title and definition text, like the API's ?q=. Code and title are set as
 * text; definition_html is inserted as HTML because the server stores it
 * sanitized (app/utils/rich_text.py).
 */
(function () {
  if (window.DigitVADefinitions) return;

  var API_URL = '/api/v1/va-definitions';
  var _load = null;

  function load() {
    if (!_load) {
      _load = fetch(API_URL, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .catch(function (err) { _load = null; throw err; });
    }
    return _load;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function searchText(item) {
    return (item.va_code + ' ' + (item.title || '') + ' ' + (item.definition_text || '')).toLowerCase();
  }

  function renderEntry(item, cls) {
    var entry = el('div', cls);
    var head = el('div', 'd-flex gap-2 align-items-baseline');
    head.appendChild(el('span', 'badge text-bg-light border font-monospace', item.va_code));
    head.appendChild(el('span', 'fw-semibold', item.title || ''));
    entry.appendChild(head);
    if (item.definition_html) {
      var body = el('div', 'va-def-body small mt-1');
      body.innerHTML = item.definition_html;
      entry.appendChild(body);
    }
    return entry;
  }

  function render(list, data) {
    list.textContent = '';
    return (data.definitions || []).map(function (item) {
      var entry = renderEntry(item, 'va-def-cause px-2 py-2 border-bottom');
      list.appendChild(entry);
      return { el: entry, text: searchText(item) };
    });
  }

  function applyFilter(entries, raw, status) {
    var needle = (raw || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
    var shown = 0;
    entries.forEach(function (entry) {
      var hit = !needle || entry.text.indexOf(needle) !== -1;
      entry.el.classList.toggle('d-none', !hit);
      if (hit) shown += 1;
    });
    if (status) status.textContent = needle ? shown + ' matching cause(s)' : '';
  }

  function mount(root) {
    if (!root || root.dataset.vaDefMounted) return;
    root.dataset.vaDefMounted = '1';
    var input = root.querySelector('.va-def-filter');
    var list = root.querySelector('.va-def-list');
    var status = root.querySelector('.va-def-status');
    list.textContent = 'Loading VA definitions…';
    load().then(function (data) {
      var entries = render(list, data);
      if (!entries.length) list.textContent = 'No VA definitions are available.';
      input.addEventListener('input', function () { applyFilter(entries, input.value, status); });
      applyFilter(entries, input.value, status);
    }).catch(function () {
      delete root.dataset.vaDefMounted;
      list.textContent = 'Could not load VA definitions. Close and reopen to retry.';
    });
  }

  window.DigitVADefinitions = { mount: mount };
})();
