// Run: node tests/js/doris_result_summary_check.mjs (no test runner; throws on failure).
globalThis.document = { createElement: t => ({ tag: t, children: [], className: '', textContent: '', append(...c){this.children.push(...c)}, appendChild(c){this.children.push(c)}, addEventListener(){} }), createTextNode: t => ({ textContent: t }) };
const { renderSummary } = await import(new URL('../../app/static/js/doris_result_summary.js', import.meta.url));
const box = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
const report = "SP3: PA60 is selected as the tentative starting point (TSP).\nM4: Adding the main injury - NC72.Z - as postcoordination for the current TUC - PA60.\n\n\nFull report:\nM4: Adding the main injury - NC72.Z - as postcoordination for the current TUC - PA60.";
renderSummary(box, {doris: {status: 'completed', result: {code: 'PA60/NC72.Z', stemCode: 'PA60', report, warning: "M4 may have been applied.\nM1: Manual check is needed.\n"}}, codedit: {status: 'completed', result: {}}}, {}, null);
const items = box.children.find(c => c.tag === 'ul').children.map(li => li.textContent);

if (items[0] !== 'M4 may have been applied: Adding the main injury - NC72.Z - as postcoordination for the current tentative underlying cause - PA60.') throw new Error('M4 not explained');
if (items[1] !== 'M1: Manual check is needed.') throw new Error('M1 changed');

// A bare CoDEdit back-end key becomes WHO's sentence with its parameters.
const box2 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box2, {doris: {status: 'completed', result: {code: '5A11/GB61.Z', stemCode: '5A11', report: '', warning: ''}}, codedit: {status: 'completed', result: {issueIds: 'BER-CE-9', report: 'RE_W_IV_CodeURIMismatch', tabularReport: '0,RE_W_IV_CodeURIMismatch,BER-CE-9;5A11/GB61.Z;;;'}}}, {}, null);
const coded = box2.children.find(c => c.tag === 'ul').children.map(li => li.textContent);
if (coded[0] !== 'The selected code - 5A11/GB61.Z - and URI correspond to different ICD entities for the same condition. Please verify that the code and the associated URI refer to the same ICD category.') throw new Error('BER-CE-9 not translated: ' + coded[0]);
