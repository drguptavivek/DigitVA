// Run: node tests/js/translation_editor_filters_check.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../mobile/digitva-collect/package.json', import.meta.url));
const { JSDOM } = require('jsdom');

const editor = readFileSync(new URL('../../app/templates/admin/instrument_translations_editor.html', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../../app/templates/admin/panels/instrument_translations.html', import.meta.url), 'utf8');
const dom = new JSDOM(editor, { runScripts: 'outside-only', url: 'http://localhost/admin/instrument-translations/WHO/hi?page=2&q=age' });
const w = dom.window, requests = [];
let modalHideCount = 0;
w.parseRichText = text => [{ text: text || '' }];
w.richTextToPlain = text => text || '';
w.bootstrap = { Modal: class {
  constructor(element) { this.element = element; }
  show() { this.element.classList.add('show'); }
  hide() {
    modalHideCount += 1;
    this.element.classList.remove('show');
  }
} };
w.fetch = (url, options) => new Promise(resolve => requests.push({ url, options, resolve(data) {
  resolve({ ok: true, json: async () => data });
} }));
const source = editor.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
  .replace(/^import .*;\s*/m, '');
w.eval(source);
const tick = () => new Promise(resolve => setImmediate(resolve));
const answer = (request, data) => request.resolve(data);

assert.match(requests[0].url, /page=2/);
assert.match(requests[0].url, /q=age/);
assert.equal(w.document.getElementById('ite-search').getAttribute('aria-label'), 'Search translations');
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
assert.equal(requests.length, 1, 'an empty final page is clamped and reloaded once');
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
w.document.getElementById('ite-missing').value = 'missing_options';
w.document.getElementById('ite-missing').dispatchEvent(new w.Event('change'));
await tick();
assert.match(requests[0].url, /page=1/);
assert.match(requests[0].url, /q=age/);
assert.match(requests[0].url, /missing=missing_options/);
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
w.document.getElementById('ite-extension').value = 'doris_support_whova_2022';
w.document.getElementById('ite-extension').dispatchEvent(new w.Event('change'));
await tick();
assert.match(requests[0].url, /extension=doris_support_whova_2022/);
assert.equal(w.document.querySelector('#ite-extension option[value="doris_support_whova_2022"]').textContent, 'DORIS support');
assert.equal(w.document.querySelector('#ite-extension option[value="base"]').textContent, 'WHO base');
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
w.document.getElementById('ite-extension').value = 'base';
w.document.getElementById('ite-extension').dispatchEvent(new w.Event('change'));
await tick();
assert.match(requests[0].url, /extension=base/);
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
assert.equal(w.document.getElementById('ite-extension').value, 'base', 'WHO base remains selectable without being in available_extensions');
w.document.getElementById('ite-extension').value = 'doris_support_whova_2022';
w.document.getElementById('ite-extension').dispatchEvent(new w.Event('change'));
await tick();
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();

// A newer filter response wins even if an older request returns afterwards.
w.document.getElementById('ite-missing').value = 'missing_options';
w.document.getElementById('ite-missing').dispatchEvent(new w.Event('change'));
await tick();
const stale = requests.shift();
w.document.getElementById('ite-missing').value = 'missing_notes';
w.document.getElementById('ite-missing').dispatchEvent(new w.Event('change'));
await tick();
const fresh = requests.shift();
const question = (name, order) => ({ name, order, english_label: name, translated_label: '', source: null,
  missing_counts: { labels: 0, options: 1, notes: 0 },
  choices: [{ value: 'yes', english: 'Yes', translated: '', source: null, extensions: ['narration_language'] }], extensions: [] });
answer(fresh, { total: 2, items: [question('first', 1), question('second', 2)], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
answer(stale, { total: 1, items: [question('stale-row', 1)], available_extensions: [] });
await tick();
assert.doesNotMatch(w.document.getElementById('ite-table-wrap').textContent, /stale-row/);
assert.match(w.document.getElementById('ite-table-wrap').textContent, /narration_language/,
  'question extension badges include nested choice provenance');
assert.match(w.document.getElementById('ite-table-wrap').textContent, /1 option\(s\)/,
  'missing options remain visible when the question label is present');
assert.match(w.location.search, /missing=missing_notes/);
assert.match(w.location.search, /extension=doris_support_whova_2022/);
w.document.querySelector('#ite-table-wrap tbody tr').click();
const textarea = w.document.querySelector('#ite-modal-body textarea');
textarea.value = 'first translated';
w.document.getElementById('ite-savenext-btn').click();
await tick();
assert.equal(requests.length, 1, 'Save and next writes only the edited field');
assert.equal(requests[0].options.method, 'PUT');
assert.equal(JSON.parse(requests[0].options.body).text, 'first translated');
answer(requests.shift(), { source: 'edited' });
await tick();
assert.match(w.document.getElementById('ite-modal-title').textContent, /^second/);
assert.match(w.location.search, /missing=missing_notes/);
assert.match(w.location.search, /extension=doris_support_whova_2022/);
const secondTextarea = w.document.querySelector('#ite-modal-body textarea');
secondTextarea.value = 'second translated';
w.document.getElementById('ite-savenext-btn').click();
await tick();
answer(requests.shift(), { source: 'edited' });
await tick();
assert.match(requests[0].url, /missing=missing_notes/);
answer(requests.shift(), { total: 1, items: [question('third', 3)], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
assert.match(w.document.getElementById('ite-modal-title').textContent, /^third/,
  'refreshing a filter that shrinks after saves advances by stable order without skipping');
const thirdTextarea = w.document.querySelector('#ite-modal-body textarea');
thirdTextarea.value = 'third translated';
w.document.getElementById('ite-savenext-btn').click();
await tick();
assert.equal(w.document.getElementById('ite-savenext-btn').disabled, true);
assert.equal(w.document.getElementById('ite-save-btn').disabled, true);
answer(requests.shift(), { source: 'edited' });
await tick();
assert.equal(w.document.getElementById('ite-savenext-btn').disabled, true,
  'save controls stay locked while the refreshed filter is loading');
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
await tick();
assert.equal(modalHideCount, 1, 'the modal closes when no questions remain under the filter');
w.document.getElementById('ite-modal').dispatchEvent(new w.Event('hidden.bs.modal'));
await tick();
assert.equal(requests.length, 1, 'closing the modal reloads the filtered list');
answer(requests.shift(), { total: 0, items: [], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
await tick();
assert.match(w.document.getElementById('ite-alert').textContent, /No remaining questions match these filters/);
assert.equal(w.document.getElementById('ite-savenext-btn').disabled, true,
  'save controls stay locked after the empty filtered result closes the modal');
w.document.getElementById('ite-savenext-btn').click();
assert.equal(requests.length, 0, 'a second save-next cannot operate on the emptied cache');
w.document.getElementById('ite-missing').value = 'all';
w.document.getElementById('ite-missing').dispatchEvent(new w.Event('change'));
await tick();
answer(requests.shift(), { total: 1, items: [question('reopened', 4)], available_extensions: ['doris_support_whova_2022', 'narration_language'] });
await tick();
w.document.querySelector('#ite-table-wrap tbody tr').click();
assert.equal(w.document.getElementById('ite-save-btn').disabled, false,
  'opening another question resets the footer save control');
assert.equal(w.document.getElementById('ite-undo-btn').disabled, false,
  'opening another question resets Undo');
assert.equal(w.document.querySelector('#ite-modal .modal-footer [data-bs-dismiss="modal"]').disabled, false,
  'opening another question resets the footer Close control');

const extBadgeBlock = panel.slice(panel.indexOf('var extBadges'), panel.indexOf('}).join', panel.indexOf('var extBadges')));
assert.match(extBadgeBlock, /\?extension=/, 'coverage badges link to the selected extension');
assert.match(source, /function advanceToNext/);
assert.match(source, /function loadNextAfter\(order\)/,
  'Save and next refreshes the filtered page and resumes after the saved row order');
assert.match(source, /hidden\.bs\.modal'[\s\S]*?loadQuestions\(\)/,
  'closing a question reloads the filtered list');
console.log('OK: URL filters, stale responses, extension deep links and save-next filter preservation');
