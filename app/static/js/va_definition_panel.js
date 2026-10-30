/*
 * Floating VA definition reference for the coding screens.
 *
 * When a coder or reviewer picks an ICD code in one of the cause-of-death
 * Select2 fields, this looks up the VA cause it maps to
 * (GET /api/v1/va-definitions/for-icd?code=...; the server infers ICD-10 or
 * ICD-11 from the code) and shows that cause's definition in a small panel
 * fixed at the bottom right. The panel has no backdrop and takes no focus, so
 * the page stays usable; closing it hides it until the next selection. The
 * ICD-11 answer is the VA cause bucket: its section, "VA cause: <label>
 * (<code>)" and the WHO definition when the bucket has one. An ICD-11 code
 * with no bucket (404) shows "VA cause: not mapped"; an ICD-10 404 shows
 * nothing. Information only: the panel never gates selection or submit. The
 * DORIS pickers call lookup() directly when a cause is picked or confirmed,
 * with classification 'icd11'.
 *
 * Included once per page by app/templates/va_form_partials/_va_definitions_modal.html.
 * Code and title are set as text; definition_html is sanitized server-side
 * (app/utils/rich_text.py).
 */
(function () {
  if (window.DigitVADefinitionPanel) return;

  var API_URL = '/api/v1/va-definitions/for-icd';
  var FIELDS = {
    'immediate-cod-select': 'Immediate cause',
    'antecedent-cod-select': 'Antecedent cause',
    'conclusive-cod-select': 'Conclusive cause',
    'reviewer-immediate-cod-select': 'Immediate cause',
    'reviewer-antecedent-cod-select': 'Antecedent cause',
    'reviewer-conclusive-cod-select': 'Conclusive cause'
  };
  var SELECTOR = Object.keys(FIELDS).map(function (id) { return '#' + id; }).join(', ');
  var panel = null;
  var requestSeq = 0;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = el('aside', 'va-def-float card shadow d-none');
    panel.setAttribute('aria-live', 'polite');
    panel.setAttribute('aria-label', 'VA definition for the selected ICD code');
    panel.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:1045;'
      + 'width:min(420px, calc(100vw - 32px));max-height:45vh;display:flex;flex-direction:column;';
    var header = el('div', 'card-header py-1 px-2 d-flex align-items-start gap-2');
    var heading = el('div', 'flex-grow-1 small');
    heading.appendChild(el('div', 'text-muted va-def-float-context'));
    heading.appendChild(el('div', 'text-muted va-def-float-section d-none'));
    var title = el('div', 'fw-semibold');
    title.appendChild(el('span', 'badge text-bg-light border font-monospace me-1 va-def-float-code'));
    title.appendChild(el('span', 'va-def-float-title'));
    heading.appendChild(title);
    var close = el('button', 'btn-close btn-sm');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close VA definition');
    close.addEventListener('click', hide);
    header.appendChild(heading);
    header.appendChild(close);
    panel.appendChild(header);
    panel.appendChild(el('div', 'card-body small py-2 px-2 overflow-auto va-def-float-body'));
    // Licence 1.2.4: DigitVA-written text beside an ICD-11 entity is not WHO content.
    panel.appendChild(el('div', 'card-footer small text-muted py-1 px-2 va-def-float-source', 'DigitVA addition \u2014 not from WHO'));
    document.body.appendChild(panel);
    return panel;
  }

  function hide() {
    requestSeq += 1;  // drop any lookup still in flight
    if (panel) panel.classList.add('d-none');
  }

  // data: the for-icd answer, or null for an ICD-11 code with no bucket. Servers
  // that predate buckets send no bucket_label and render as before.
  function show(data, fieldLabel, code) {
    var p = ensurePanel();
    var bucket = !!data && data.bucket_label != null;
    var hasDefinition = !!data && (!bucket || data.has_definition !== false);
    var section = (bucket && data.bucket_section) || '';
    p.querySelector('.va-def-float-context').textContent =
      'VA definition · ' + fieldLabel + ' · ' + (data ? data.icd_code : code);
    var sectionNode = p.querySelector('.va-def-float-section');
    sectionNode.textContent = section;
    sectionNode.classList.toggle('d-none', !section);
    var badge = p.querySelector('.va-def-float-code');
    badge.textContent = data && !bucket ? data.va_code : '';
    badge.classList.toggle('d-none', !(data && !bucket));
    p.querySelector('.va-def-float-title').textContent = !data ? 'VA cause: not mapped'
      : bucket ? 'VA cause: ' + data.bucket_label + ' (' + data.va_code + ')' : data.title;
    var body = p.querySelector('.va-def-float-body');
    body.classList.toggle('d-none', !hasDefinition);
    if (hasDefinition) {
      body.innerHTML = data.definition_html || '';
      if (!data.definition_html) body.textContent = 'No definition text for this VA cause.';
    } else {
      body.textContent = '';
    }
    body.scrollTop = 0;
    p.classList.remove('d-none');
  }

  function lookup(value, fieldLabel, classification) {
    var seq = ++requestSeq;
    if (!value) { hide(); return; }
    var query = '?code=' + encodeURIComponent(value) + (classification ? '&classification=' + encodeURIComponent(classification) : '');
    fetch(API_URL + query, {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin'
    }).then(function (r) {
      if (seq !== requestSeq) return;
      if (r.status === 404 && classification === 'icd11') { show(null, fieldLabel, String(value).trim().split(/\s+/)[0]); return; }
      if (!r.ok) { hide(); return; }
      return r.json().then(function (data) { if (seq === requestSeq) show(data, fieldLabel); });
    }).catch(function () { if (seq === requestSeq) hide(); });
  }

  function hook() {
    var $ = window.jQuery;
    if (!$ || hook.done) return;
    hook.done = true;
    // Select2 raises its events on the original <select>, and jQuery bubbles
    // them, so one delegated handler covers selects swapped in later by htmx.
    $(document).on('select2:select', SELECTOR, function (e) {
      var data = e.params && e.params.data;
      lookup(data && data.id, FIELDS[this.id] || 'Cause');
    });
    $(document).on('select2:clear select2:unselect', SELECTOR, hide);
  }

  hook();
  if (!hook.done) document.addEventListener('DOMContentLoaded', hook);
  window.DigitVADefinitionPanel = { hide: hide, lookup: lookup };
})();
