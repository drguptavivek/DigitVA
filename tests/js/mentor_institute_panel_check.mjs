// Run: node tests/js/mentor_institute_panel_check.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../mobile/digitva-collect/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const source = readFileSync(new URL('../../app/templates/admin/panels/mentor_institutes.html', import.meta.url), 'utf8');
const script = source.match(/<script>([\s\S]*)<\/script>/)[1];
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const dom = new JSDOM(source.replace(/<script>[\s\S]*<\/script>/, ''), {runScripts: 'outside-only', url: 'http://localhost'});
  const w = dom.window, requests = [];
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.fetch = (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve({ok: true, json: async () => data}), reject}));
  w.eval(script);
  const el = id => w.document.getElementById('mentor-' + id);
  const data = code => ({institute: {institute_code: code, institute_name: 'Institute ' + code, is_active: true}, staff: [], districts: [], staff_next: null, districts_next: null});
  const select = code => { el('select').value = code; el('select').onchange(); };
  const submit = () => el('new-staff').onsubmit({preventDefault() {}, target: el('new-staff')});
  return {w, requests, el, data, select, submit};
}
async function initialized() {
  const s = setup();
  s.requests.shift().resolve({institutes: ['A', 'B'].map(code => ({institute_code: code, institute_name: code, is_active: true})), next: null, languages: [{language_code: 'english', language_name: 'English'}]});
  await tick(); return s;
}
{
  const s = await initialized();
  s.select('A'); const a = s.requests.shift();
  assert.equal(s.el('status').disabled, true, 'writes disabled during detail loading');
  s.select('B'); const b = s.requests.shift();
  b.resolve(s.data('B')); await tick();
  a.resolve(s.data('A')); await tick();
  assert.equal(s.el('heading').textContent, 'Institute B', 'late A response cannot overwrite B');
  s.el('status').onclick();
  const mutation = s.requests.shift();
  assert.equal(JSON.parse(mutation.options.body).code, 'B', 'action targets rendered institute');
  mutation.resolve({ok: true}); await tick();
  s.requests.shift().resolve(s.data('B')); await tick();
}
{
  const s = await initialized(); s.select('A'); s.requests.shift().resolve(s.data('A')); await tick();
  const submitted = s.submit();
  const creation = s.requests.shift();
  creation.resolve({sign_in_code: 'one-time-secret'}); await tick();
  assert.equal(s.el('code-dialog').open, true, 'code shown before refresh finishes');
  assert.match(s.el('once-code').textContent, /one-time-secret/);
  s.requests.shift().reject(new Error('Refresh unavailable')); await submitted;
  assert.match(s.el('once-code').textContent, /one-time-secret/, 'failed refresh retains one-time code');
}
{
  const s = await initialized(); s.select('A'); s.requests.shift().resolve(s.data('A')); await tick();
  const submitted = s.submit(), creation = s.requests.shift();
  s.select('B'); s.requests.shift().resolve(s.data('B')); await tick();
  s.el('staff-name').value = 'New B draft';
  creation.resolve({sign_in_code: 'A-code'}); await submitted;
  assert.equal(s.el('heading').textContent, 'Institute B');
  assert.equal(s.el('staff-name').value, 'New B draft', 'late A creation cannot clear B form');
  assert.equal(s.requests.length, 0, 'late A creation does not refresh current B selection');
  assert.match(s.el('once-code').textContent, /A: A-code/, 'returned code retains institute context');
}
console.log('OK: mentor panel rejects stale details, binds writes, and retains one-time codes across refresh failures and selection changes');
