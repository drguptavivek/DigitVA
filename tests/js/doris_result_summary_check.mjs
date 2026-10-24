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

// An empty CoDEdit issue list is no issue: no "reported:" item, and a clean run says so.
const box3 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box3, {doris: {status: 'completed', result: {code: 'PA60', stemCode: 'PA60', report: '', warning: ''}}, codedit: {status: 'completed', result: {issueIds: [], report: '', tabularReport: ''}}}, {}, null);
if (box3.children.some(c => c.tag === 'ul')) throw new Error('an empty issue list added checks');
if (!box3.children.some(c => c.textContent === 'No problems found in the certificate.')) throw new Error('clean run not reported');

// The server's ucod_parts render as a titled cluster, the raw code kept underneath.
const box4 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box4, {ucod_parts: [{code: '5A14', title: 'Diabetes mellitus, type unspecified', role: 'stem'}, {code: 'BA41.Z', title: 'Acute myocardial infarction, unspecified', role: 'postcoordinated'}], doris: {status: 'completed', result: {code: '5A14/BA41.Z', stemCode: '5A14', uri: 'http://x/1', report: '', warning: ''}}, codedit: {status: 'completed', result: {}}}, {}, null);
const clusterText = box4.children.find(c => c.className.includes('doris-summary-cluster')).children.map(c => c.textContent);
if (clusterText[0] !== 'Underlying cause: 5A14 Diabetes mellitus, type unspecified') throw new Error('stem line: ' + clusterText[0]);
if (clusterText[1] !== '+ BA41.Z Acute myocardial infarction, unspecified (manifestation)') throw new Error('manifestation line: ' + clusterText[1]);
if (clusterText[2] !== '5A14/BA41.Z') throw new Error('full code chip: ' + clusterText[2]);
if (clusterText.some(text => text.includes('Computed UCOD'))) throw new Error('raw code line not moved into Details');
const details = box4.children.find(c => c.tag === 'details');
if (!details || details.children[0].textContent !== 'Details') throw new Error('no collapsed Details');
const detailText = details.children.map(c => c.textContent).join('\n');
if (!detailText.includes('joins the stem code') || !detailText.includes('Computed stem: 5A14') || !detailText.includes('Computed URI: http://x/1')) throw new Error('details incomplete: ' + detailText);

// One code: its line alone, no duplicate chip.
const box5 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box5, {ucod_parts: [{code: 'PA60', title: 'Some injury', role: 'stem'}], doris: {status: 'completed', result: {code: 'PA60', stemCode: 'PA60', report: '', warning: ''}}, codedit: {status: 'completed', result: {}}}, {}, null);
const single = box5.children.find(c => c.className.includes('doris-summary-cluster')).children.map(c => c.textContent);
if (single.length !== 1 || single[0] !== 'Underlying cause: PA60 Some injury') throw new Error('single code: ' + single.join(' | '));

// A rejected run says DORIS rejected the certificate and shows WHO's reason; it does not say "did not run".
const box6 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box6, {doris: {status: 'rejected', result: {reject: true, code: null, error: 'Stem PA60 is not a valid starting point.'}}, codedit: {status: 'completed', result: {}}}, {}, null);
const rejected = box6.children.map(c => c.textContent);
if (!rejected.includes('DORIS rejected the certificate.') || !rejected.includes('Stem PA60 is not a valid starting point.')) throw new Error('rejection not shown: ' + rejected.join(' | '));
if (rejected.some(text => text.includes('did not run'))) throw new Error('rejection reported as did not run');

// An engine that did not run keeps the "did not run" wording.
const box7 = { children: [], replaceChildren(){ this.children = []; }, appendChild(c){ this.children.push(c); } };
renderSummary(box7, {doris: {status: 'unavailable', result: null}, codedit: {status: 'completed', result: {}}}, {}, null);
if (!box7.children.some(c => c.textContent === 'DORIS did not run (unavailable). Choose the underlying cause without it.')) throw new Error('unavailable wording');
