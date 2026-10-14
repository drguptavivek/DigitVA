// Run: NODE_PATH=mobile/digitva-collect/node_modules node tests/js/doris_derive_check.mjs (no test runner; throws on failure).
// EstimatedAge derive decisions (V7) and the interval control's typed() probe, which the editor's date-change refill reads.
import assert from 'node:assert/strict';
const R = await import(new URL('../../app/static/js/doris_rules.js', import.meta.url));
const I = await import(new URL('../../app/static/js/doris_interval.js', import.meta.url));

// Load: derive only for a prefill seed (non-empty provenance) and never for a restored processing.
const provenance = {'AdministrativeData.DateBirth': {sources: ['Id10020']}};
assert.equal(R.derivesAtLoad(provenance, null), true);
assert.equal(R.derivesAtLoad({}, null), false, 'a saved certificate has no provenance and keeps its own age');
assert.equal(R.derivesAtLoad(provenance, {certificate: {}, doris: {}}), false, 'a restored processing keeps its age');
assert.equal(R.derivesAtLoad(undefined, undefined), false);

// Date change refill: a typed or cleared-by-typing age is never replaced; only empty or the derived value is.
assert.equal(R.mayRefillAge('', false, null), true, 'blank and untouched refills from the dates');
assert.equal(R.mayRefillAge('', true, null), false, 'a half-typed number (no unit) is user input');
assert.equal(R.mayRefillAge('P30Y', false, null), false, 'a value the coder typed is kept');
assert.equal(R.mayRefillAge('P30Y', false, 'P30Y'), true, 'the value derived last time is refreshed');
assert.equal(R.mayRefillAge('', false, 'P30Y'), true, 'cleared by the coder: refilled by the next date change');

// The real interval control: a number with no unit reads as '' from peek() but typed() reports it.
const listeners = {};
const el = (extra = {}) => ({value: '', dataset: {}, textContent: '', hidden: false, options: [], appendChild() {}, addEventListener(type, fn) { listeners[type] = fn; }, ...extra});
const valueInput = el(), unitSelect = el();
const container = {querySelector: (sel) => sel.includes('value') ? valueInput : sel.includes('unit') ? unitSelect : null};
globalThis.document = {createElement: () => el()};
const control = I.mount(container, '');
assert.equal(control.typed(), false, 'blank control is not typed');
valueInput.value = '28'; listeners.input();
assert.equal(control.peek(), '', 'a number without a unit is not a value yet');
assert.equal(control.typed(), true, 'but it is typed input');
assert.equal(R.mayRefillAge(control.peek(), control.typed(), null), false);
valueInput.value = ''; unitSelect.value = 'Y'; listeners.change();
assert.equal(control.typed(), true, 'a unit alone counts as typed');
delete globalThis.document;
console.log('doris_derive ok');
