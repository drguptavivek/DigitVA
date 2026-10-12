// Run: node tests/js/icd11_picker_check.mjs (needs jsdom from mobile/digitva-collect/node_modules).
// A new search must clear the previous guided/builder panel, details and related window.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../mobile/digitva-collect/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<body></body>');
globalThis.window = dom.window; globalThis.document = dom.window.document;
const { createIcd11Picker } = await import(new URL('../../app/static/js/digitva_icd11_picker.js', import.meta.url));

const picker = createIcd11Picker({mount: document.body, transport: {post: () => new Promise(() => {})}, onSelect() {}});
const line = document.createElement('div');
line.innerHTML = '<div data-doris-details-panel></div><div data-doris-guided-panel></div>';
document.body.appendChild(line);
const guided = () => line.querySelector('[data-doris-guided-panel-content]');

picker.openPostcoordination(line, {code: 'BD10', title: 'Congestive heart failure', uri: 'u'}, null, true);
assert.equal(guided().hidden, false);            // builder is up for the old stem
const related = document.createElement('section'); related.setAttribute('data-doris-related-window', ''); line.appendChild(related);
line.querySelector('[data-doris-details-panel]').hidden = false;

picker.clearPanels(line);
assert.equal(guided().hidden, true); assert.equal(guided().childNodes.length, 0);
assert.equal(line.querySelector('[data-doris-details-panel]').hidden, true);
assert.equal(line.querySelector('[data-doris-related-window]'), null);
picker.clearPanels(document.createElement('div')); // no panels: no throw

// Scroll/focus on open, Back to results, footer structure (jsdom has no layout: spy scrollIntoView).
const scrolled = [];
dom.window.Element.prototype.scrollIntoView = function (arg) { scrolled.push([this, arg]); };
const post = (path) => path === 'postcoordination' ? Promise.resolve({stem: {code: 'FB32', title: 'Infarction', uri: 'u'}, axes: [{id: 'a', label: 'Severity', required: true, options: [{code: 'XS1', title: 'Mild', uri: 'x'}]}]})
  : Promise.resolve({});
const host = document.createElement('div');
host.innerHTML = '<h2 data-line-title>L</h2><input><div data-doris-search-status></div><div data-doris-search-results></div><div data-doris-details-panel hidden></div><div data-doris-guided-panel></div>';
document.body.appendChild(host);
const p2 = createIcd11Picker({mount: document.body, transport: {post}, onSelect() {}});
p2.open(host, host.querySelector('input'));
const footer = host.querySelector('.doris-selection-footer');
assert.ok(footer.querySelector('.doris-selection-caption'));
assert.equal(footer.querySelector('.doris-selection-choice').textContent, 'No code selected');
assert.ok(footer.querySelector('.doris-footer-buttons').classList.contains('flex-wrap'));
p2.renderResults(host, [{code: 'FB32', title: 'Infarction', uri: 'u', postcoordination: true, postcoordination_availability: 1}], {input: host.querySelector('input'), statusEl: host.querySelector('[data-doris-search-status]'), resultList: host.querySelector('[data-doris-search-results]'), onRequery() {}});
const row = host.querySelector('.doris-search-result');
row.querySelector('.doris-context-icon--post').click();
await new Promise((r) => setTimeout(r, 0));
const card = host.querySelector('[data-doris-guided-panel-content]');
assert.ok(scrolled.some(([node]) => node === card), 'build card scrolled into view');
assert.equal(document.activeElement.tagName, 'H4'); assert.ok(card.contains(document.activeElement));
assert.equal(footer.querySelector('.doris-selection-caption').textContent, 'BUILDING');
assert.ok(footer.querySelector('.doris-selection-code').textContent.startsWith('FB32'));
assert.ok(footer.querySelector('.doris-selection-note'));
scrolled.length = 0;
card.querySelector('.doris-back-to-results').click();
assert.equal(scrolled[0][0], row);
// Details card: scrolls, focuses its heading, can go back
scrolled.length = 0;
[...row.querySelectorAll('button')].find((b) => b.textContent === 'Details').click();
const details = host.querySelector('[data-doris-details-panel]');
assert.equal(scrolled[0][0], details); assert.equal(document.activeElement.tagName, 'H4');
// Staged choice: SELECTED caption, code chip, title
p2.stage(host, {code: 'FB32.2Z', title: 'Ischaemic infarction of muscle, unspecified', uri: 'u'}, null);
assert.equal(footer.querySelector('.doris-selection-caption').textContent, 'SELECTED');
assert.equal(footer.querySelector('.doris-selection-code').textContent, 'FB32.2Z');
assert.ok(footer.querySelector('.doris-selection-title').textContent.startsWith('Ischaemic'));
p2.close();
console.log('icd11_picker ok');
