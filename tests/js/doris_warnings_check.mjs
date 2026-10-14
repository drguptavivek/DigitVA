// Run: node tests/js/doris_warnings_check.mjs (no test runner; throws on failure).
// Checks the web DORIS warning reader against tests/fixtures/doris_warning_cases.json,
// the same cases the Expo app's parity test runs against dorisWarnings.ts.
import { readFileSync } from 'node:fs';

const { describeWarning } = await import(new URL('../../app/static/js/doris_warnings.js', import.meta.url));
const { cases } = JSON.parse(readFileSync(new URL('../fixtures/doris_warning_cases.json', import.meta.url), 'utf8'));

for (const testCase of cases) {
  const got = describeWarning(testCase.warning, testCase.report, (code) => testCase.titles[code]);
  const want = testCase.expect;
  if (got.text !== want.text) throw new Error(`${testCase.name}: text\n  got  ${got.text}\n  want ${want.text}`);
  if (got.original !== want.original) throw new Error(`${testCase.name}: original ${got.original}`);
  if (got.code !== want.code) throw new Error(`${testCase.name}: code ${got.code}`);
}
console.log(`doris_warnings_check: ${cases.length} cases passed`);
