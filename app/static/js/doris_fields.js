// DOM-only helpers of the clinical DORIS editor, kept apart so they can be
// tested without the network: the date precision dropdown and the per-question
// clear button. Rules: docs/policy/doris-certificate-rules.md (V10, "Date
// precision", "Clear button"). No `max`/`pattern` attributes are ever set: the
// editor sits in an htmx form and native validation would block Save.
'use strict';

var MODES = {
  date: {type: 'date', re: /^\d{4}-\d{2}-\d{2}$/, length: 10, rank: 3},
  month: {type: 'month', re: /^\d{4}-\d{2}$/, length: 7, rank: 2},
  year: {type: 'text', re: /^\d{4}$/, length: 4, rank: 1}
};

// 'date' | 'month' | 'year' for a stored value, else null.
export function precisionOf(value) {
  return Object.keys(MODES).find(function (mode) { return MODES[mode].re.test(value); }) || null;
}
// A saved date with a time part ("2020-06-03T12:30:00Z") shows and sends as its day.
function dayOnly(value) { return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) ? value.slice(0, 10) : value; }
// "From interview" badges of every field in (or hosting) a node.
export function removePrefillMarkers(node) {
  var host = node.closest('[data-doris-field]');
  [node, host].forEach(function (scope) {
    if (scope) scope.querySelectorAll('[data-doris-prefill-marker]').forEach(function (marker) { marker.remove(); });
  });
}
export function isDate(value) { return precisionOf(value) !== null; }

function selectOf(input) { return input.parentNode.querySelector('[data-doris-precision]'); }

function applyMode(input, mode) {
  input.type = MODES[mode].type;
  if (mode === 'year') { input.maxLength = 4; input.inputMode = 'numeric'; }
  else { input.removeAttribute('maxlength'); input.removeAttribute('inputmode'); }
  input.placeholder = mode === 'year' ? 'YYYY' : mode === 'month' ? 'YYYY-MM' : '';
}

// A stored value opens in its own precision; blank keeps the chosen one.
export function setDate(input, value) {
  value = dayOnly(value);
  var select = selectOf(input); var mode = precisionOf(value);
  if (mode) select.value = mode;
  applyMode(input, select.value);
  input.value = mode ? value : '';
}
export function resetDate(input) { selectOf(input).value = 'date'; applyMode(input, 'date'); input.value = ''; }

// Date of death: a plain calendar input. A saved partial value (older data)
// stays visible in a text input the coder can replace; it is never dropped.
export function setPlainDate(input, value) {
  value = dayOnly(value);
  var partial = Boolean(value) && precisionOf(value) !== 'date';
  input.type = partial ? 'text' : 'date';
  if (partial) { input.maxLength = 10; input.placeholder = 'YYYY, YYYY-MM or YYYY-MM-DD'; }
  else { input.removeAttribute('maxlength'); input.placeholder = ''; }
  input.value = value;
}

// Switching precision keeps only what the new precision can express.
export function mountDates(editor) {
  editor.querySelectorAll('[data-doris-date]').forEach(function (input) {
    var select = selectOf(input);
    applyMode(input, select.value);
    select.addEventListener('change', function () {
      var old = input.value; var from = precisionOf(old); var to = select.value;
      applyMode(input, to);
      input.value = from && MODES[from].rank >= MODES[to].rank ? old.slice(0, MODES[to].length) : '';
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
    input.addEventListener('input', function () {
      if (select.value !== 'year') return;
      var digits = input.value.replace(/\D/g, '').slice(0, 4);
      if (digits !== input.value) input.value = digits;
    });
  });
}

var CROSS = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>';

function clearButton(label, inline, control) {
  var button = document.createElement('button');
  button.type = 'button'; button.hidden = true; button.setAttribute('data-doris-clear', '');
  button.className = inline ? 'btn btn-sm doris-clear doris-clear-inline' + (control.type === 'number' ? ' doris-clear-number' : '') + (control.tagName === 'TEXTAREA' ? ' doris-clear-corner' : '') : 'btn btn-sm doris-clear';
  button.setAttribute('aria-label', 'Clear ' + label);
  button.innerHTML = CROSS;
  return button;
}

// A clear button on every question of the certificate cards (a `.row` column
// holding a label and a control). Part I/II lines have their own Remove and
// are not in a `.row`. Clearing empties the controls, drops the "from
// interview" badge and fires input and change so the editor invalidates,
// re-runs its rules and refreshes its warnings. Returns {refresh}.
export function mountClear(editor) {
  var entries = [];
  editor.querySelectorAll('.row > [class*="col-"]').forEach(function (host) {
    var label = Array.from(host.children).find(function (child) { return child.tagName === 'LABEL'; });
    if (!label || host.closest('[data-doris-line], [data-doris-final-panel]')) return;
    var name = Array.from(label.childNodes).filter(function (node) { return node.nodeType === 3; }).map(function (node) { return node.textContent; }).join('').replace(/\*/g, '').trim();
    var controls = Array.from(host.querySelectorAll('input,select,textarea')).filter(function (control) { return !control.hasAttribute('data-doris-precision'); });
    if (!controls.length) return;
    var row = document.createElement('div'); row.className = 'doris-label-row';
    host.insertBefore(row, label); row.appendChild(label);
    var buttons = [clearButton(name, false, null)];
    row.appendChild(buttons[0]);
    var single = controls.length === 1 ? controls[0] : null;
    if (single && !single.hasAttribute('data-doris-date') && !single.hasAttribute('data-doris-date-plain') && !host.hasAttribute('data-doris-age-control') && (single.tagName === 'TEXTAREA' || (single.tagName === 'INPUT' && (single.type === 'text' || single.type === 'number')))) {
      var wrap = document.createElement('div'); wrap.className = 'doris-inline-clear';
      single.parentNode.insertBefore(wrap, single); wrap.appendChild(single);
      var inline = clearButton(name, true, single); wrap.appendChild(inline); buttons.push(inline);
    }
    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        controls.forEach(function (control) { if (control.hasAttribute('data-doris-date-plain')) setPlainDate(control, ''); else control.value = ''; });
        host.querySelectorAll('[data-doris-prefill-marker]').forEach(function (marker) { marker.remove(); });
        controls.forEach(function (control) {
          control.dispatchEvent(new Event('input', {bubbles: true}));
          control.dispatchEvent(new Event('change', {bubbles: true}));
        });
        controls[0].focus();
      });
    });
    entries.push({controls: controls, buttons: buttons});
  });
  function refresh() {
    entries.forEach(function (entry) {
      var filled = entry.controls.some(function (control) { return control.value !== ''; });
      entry.buttons.forEach(function (button) { button.hidden = !filled; });
    });
  }
  editor.addEventListener('input', refresh);
  editor.addEventListener('change', refresh);
  refresh();
  return {refresh: refresh};
}
