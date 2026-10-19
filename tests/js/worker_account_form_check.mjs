/** Exercise the actual worker submit handler before any HTTP request. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('app/templates/admin/panels/organization.html', 'utf8');
const start = source.indexOf("  $('ow-save-btn').addEventListener('click', function () {");
const end = source.indexOf('\n\n  // ── export / import', start);
const elements = {};
let handler, requests = 0, error = '';
const defaults = {
  'ow-id': '', 'ow-unit': 'unit', 'ow-cadre': 'cadre', 'ow-name': 'Worker',
  'ow-email': 'worker@example.org', 'ow-email-confirm': 'worker@example.org',
  'ow-phone': '', 'ow-phone-confirm': '', 'ow-year': '', 'ow-sex': '',
  'ow-user': '', 'ow-remarks': '', 'ow-save-btn': '',
};
for (const [id, value] of Object.entries(defaults)) {
  elements[id] = { value, checkValidity: () => true, addEventListener: (_, fn) => { handler = fn; } };
}
elements['ow-no-email'] = { checked: false };
const context = {
  $: id => elements[id], val: id => elements[id].value.trim(),
  unitById: () => ({ org_level_id: 'level' }),
  STATE: { level_cadres: [{ is_active: true, org_level_id: 'level', cadre_id: 'cadre', default_roles: ['coder'] }] },
  canvasFail: (_, response) => { error = response.data.error; },
  selectedWorkerLanguages: () => ['en'], base: () => '/organization',
  api: () => { requests++; return Promise.resolve({ ok: false }); },
};
vm.runInNewContext(source.slice(start, end), context);
for (const phone of ['123456789', '12345678901', '12345x7890', '१२३४५६७८९०', ' 1234567890']) {
  elements['ow-phone'].value = phone;
  error = ''; handler();
  assert.match(error, /exactly 10 digits/);
  assert.equal(requests, 0);
}
elements['ow-phone'].value = '9876543210';
elements['ow-no-email'].checked = true;
elements['ow-phone-confirm'].value = '9876543211';
handler(); assert.match(error, /confirm/); assert.equal(requests, 0);
elements['ow-phone-confirm'].value = '9876543210';
handler(); assert.equal(requests, 1);
elements['ow-no-email'].checked = false;
elements['ow-email-confirm'].value = 'different@example.org';
handler(); assert.equal(requests, 1);
console.log('Worker form: invalid phone, mobile confirmation, valid mobile and email confirmation checks passed.');
