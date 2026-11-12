// Server text must be escaped before it enters an HTML string in the coding and
// data-manager KPI dashboards. Run: node tests/js/dashboard_escape_check.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (p) => readFileSync(new URL(`../../app/static/js/${p}`, import.meta.url), "utf8");

const code = read("va_code_dashboard.js");
const m = code.match(/function escapeHtml\(value\) \{[\s\S]*?\n  \}/);
assert.ok(m, "escapeHtml is present in va_code_dashboard.js");
const escapeHtml = new Function(`${m[0]}; return escapeHtml;`)();
const out = escapeHtml("<img src=x onerror=alert(1)>");
assert.ok(!out.includes("<") && !out.includes(">"), "markup characters are escaped");
assert.equal(escapeHtml(null), "");
assert.equal(escapeHtml('"&'), "&quot;&amp;");

for (const expr of [
  "escapeHtml(row.project_id)", "escapeHtml(row.site_id)", "escapeHtml(row.va_uniqueid_masked)",
  "escapeHtml(row.va_data_collector || '-')", "escapeHtml(row.va_deceased_gender || '-')",
  "escapeHtml(r.va_deceased_gender || '-')", "escapeHtml(continueLabel)",
]) assert.ok(code.includes(expr), `va_code_dashboard.js escapes ${expr}`);
assert.ok(code.includes("$.fn.dataTable.render.text()"), "history text columns use the text renderer");

const kpi = read("dm_kpi_dashboard.js");
for (const expr of [
  "escapeHtml(site.site_id)", "escapeHtml(lang.language)", "escapeHtml(name)",
  "escapeHtml(item.label || item.blockage_reason)", "escapeHtml(l) + '('",
]) assert.ok(kpi.includes(expr), `dm_kpi_dashboard.js escapes ${expr}`);

console.log("OK: dashboard server text is escaped");
