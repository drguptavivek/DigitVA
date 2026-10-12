// Run: NODE_PATH=mobile/digitva-collect/node_modules node tests/js/doris_fields_check.mjs
// Date precision dropdown, per-question clear button and the 3-character
// auto-search timing (jsdom from mobile/digitva-collect/node_modules).
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../mobile/digitva-collect/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const dom = new JSDOM(`<body><section id="ed">
<div class="row">
 <div class="col-sm-6"><label>Date of birth</label><div class="input-group"><select data-doris-precision><option value="date">Date</option><option value="month">Year-Month</option><option value="year">Year</option></select><input data-doris-date id="dob"></div></div>
 <div class="col-sm-6"><label for="dd">Date of death</label><input id="dd" type="date" data-doris-date-plain></div>
 <div class="col-sm-6"><label>Weight</label><input type="number" id="w"></div>
 <div class="col-sm-6"><label>Notes *</label><textarea id="n"></textarea></div>
 <div class="col-sm-6"><label>Sex</label><select id="sex"><option value="">Not stated</option><option value="1">Male</option></select><span data-doris-prefill-marker>from interview</span></div>
</div></section></body>`);
Object.assign(globalThis, {window: dom.window, document: dom.window.document, Event: dom.window.Event});
const F = await import(new URL('../../app/static/js/doris_fields.js', import.meta.url));
const { attachAutoSearch } = await import(new URL('../../app/static/js/digitva_icd11_picker.js', import.meta.url));
const $ = (s) => document.querySelector(s);
const editor = $('#ed'); const dob = $('#dob'); const select = $('[data-doris-precision]');

// precision: stored value picks its own precision; widening keeps nothing; narrowing keeps the prefix
F.mountDates(editor);
assert.equal(dob.type, 'date');
F.setDate(dob, '2020-05-17'); assert.equal(select.value, 'date'); assert.equal(dob.value, '2020-05-17');
const choose = (mode) => { select.value = mode; select.dispatchEvent(new dom.window.Event('change', {bubbles: true})); };
choose('month'); assert.equal(dob.type, 'month'); assert.equal(dob.value, '2020-05');
choose('year'); assert.equal(dob.type, 'text'); assert.equal(dob.value, '2020'); assert.equal(dob.maxLength, 4); assert.equal(dob.inputMode, 'numeric');
assert.equal(dob.hasAttribute('max'), false);
choose('month'); assert.equal(dob.value, ''); choose('date'); assert.equal(dob.type, 'date');
F.setDate(dob, '1999-03'); assert.equal(select.value, 'month'); assert.equal(dob.value, '1999-03');
F.setDate(dob, '1980'); assert.equal(select.value, 'year'); assert.equal(dob.value, '1980');
dob.value = '20ab24x9'; dob.dispatchEvent(new dom.window.Event('input', {bubbles: true})); assert.equal(dob.value, '2024');
F.setDate(dob, ''); assert.equal(select.value, 'year'); assert.equal(dob.value, '');   // blank keeps the chosen precision
F.resetDate(dob); assert.equal(select.value, 'date'); assert.equal(dob.type, 'date');
assert.equal(F.precisionOf('2020'), 'year'); assert.equal(F.precisionOf('2020-1'), null); assert.equal(F.isDate('abc'), false);

// date of death: a saved partial value stays in a text input and is replaceable; clearing restores the calendar
const dd = $('#dd');
F.setPlainDate(dd, '2020-05'); assert.equal(dd.type, 'text'); assert.equal(dd.value, '2020-05');
F.setPlainDate(dd, '2020-05-17'); assert.equal(dd.type, 'date');

// clear buttons
F.setPlainDate(dd, ''); const seen = []; editor.addEventListener('input', (e) => seen.push(e.target.id));
const clear = F.mountClear(editor);
const buttons = [...editor.querySelectorAll('[data-doris-clear]')];
assert.equal(buttons.length, 7);   // dob, death, weight x2, notes x2, sex
assert.ok(buttons.every((b) => b.hidden));
assert.deepEqual(buttons.map((b) => b.getAttribute('aria-label')).filter((l) => /Notes|Date of birth/.test(l)), ['Clear Date of birth', 'Clear Notes', 'Clear Notes']);
F.setDate(dob, '2001-02'); $('#w').value = '5'; $('#sex').value = '1'; clear.refresh();
const visible = () => buttons.filter((b) => !b.hidden).map((b) => b.getAttribute('aria-label'));
assert.deepEqual(visible(), ['Clear Date of birth', 'Clear Weight', 'Clear Weight', 'Clear Sex']);
buttons.find((b) => b.getAttribute('aria-label') === 'Clear Date of birth').click();
assert.equal(dob.value, ''); assert.equal(select.value, 'month'); assert.ok(seen.includes('dob'));   // precision kept, input event fired
assert.ok(!visible().includes('Clear Date of birth'));
buttons.find((b) => b.getAttribute('aria-label') === 'Clear Sex').click();
assert.equal($('#sex').value, ''); assert.equal(document.querySelector('[data-doris-prefill-marker]'), null);
buttons.filter((b) => b.getAttribute('aria-label') === 'Clear Weight')[1].click(); assert.equal($('#w').value, ''); assert.deepEqual(visible(), []);
F.setPlainDate(dd, '2020'); clear.refresh(); buttons.find((b) => b.getAttribute('aria-label') === 'Clear Date of death').click();
assert.equal(dd.value, ''); assert.equal(dd.type, 'date');

// auto-search: 500 ms rest at 3+ chars, once per term, never for 1-2 chars, blur cancels, reset allows the term again
const box = document.createElement('input'); document.body.appendChild(box);
let calls = []; const auto = attachAutoSearch(box, (t) => calls.push(t), 40);
const type = (v) => { box.value = v; box.dispatchEvent(new dom.window.Event('input')); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
type('ab'); await wait(80); assert.deepEqual(calls, []);
type('abc'); type('abcd'); await wait(20); assert.deepEqual(calls, []);    // each keystroke restarts the pause
await wait(60); assert.deepEqual(calls, ['abcd']);
type('abcd'); await wait(80); assert.deepEqual(calls, ['abcd']);          // same term: no repeat
type('abc'); await wait(80); assert.deepEqual(calls, ['abcd', 'abc']);
type('ab'); type('abc'); await wait(80); assert.deepEqual(calls, ['abcd', 'abc', 'abc']);   // dropped below 3 first
type('xyz'); box.dispatchEvent(new dom.window.Event('blur')); await wait(80); assert.equal(calls.length, 3);
type('xyz'); auto.mark(); await wait(80); assert.equal(calls.length, 3);  // explicit Search already ran this term
box.value = ''; auto.reset(); type('xyz'); await wait(80); assert.equal(calls.at(-1), 'xyz'); assert.equal(calls.length, 4);
console.log('doris_fields ok');

// a saved date with a time part shows as its day; partial values keep their precision
{
  const plain = document.createElement('input'); plain.type = 'date';
  F.setPlainDate(plain, '2020-06-03T12:30:00Z'); assert.equal(plain.type, 'date'); assert.equal(plain.value, '2020-06-03'); assert.equal(F.isDate(plain.value), true);
  F.setPlainDate(plain, '2020-06'); assert.equal(plain.type, 'text'); assert.equal(plain.value, '2020-06');
  F.setDate(dob, '2020-06-03T12:30:00Z'); assert.equal(select.value, 'date'); assert.equal(dob.value, '2020-06-03');
  F.setDate(dob, '1980'); assert.equal(dob.value, '1980');
}

// clearing a hidden rule removes the "from interview" badges of the node and of its host column
{
  const holder = document.createElement('div');
  holder.innerHTML = '<div data-doris-field="A"><label>A<span data-doris-prefill-marker="A">x</span></label><div data-doris-rule="r"><input></div></div>' +
    '<div data-doris-rule="h" data-doris-field="B"><label>B<span data-doris-prefill-marker="B">y</span></label></div>' +
    '<div data-doris-field="C"><label>C<span data-doris-prefill-marker="C">z</span></label></div>';
  const inner = holder.querySelector('[data-doris-rule="r"]'); const host = holder.querySelector('[data-doris-rule="h"]');
  assert.equal(holder.querySelectorAll('[data-doris-prefill-marker]').length, 3);
  F.removePrefillMarkers(host); assert.equal(host.querySelector('[data-doris-prefill-marker]'), null);
  F.removePrefillMarkers(inner); assert.equal(holder.querySelector('[data-doris-prefill-marker="A"]'), null);
  assert.ok(holder.querySelector('[data-doris-prefill-marker="C"]'));   // other fields keep theirs
}
