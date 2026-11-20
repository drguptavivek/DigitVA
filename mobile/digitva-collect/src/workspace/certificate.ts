/**
 * The WHO-form cause-of-death certificate of a coded organization-project case, for the phone
 * (docs/policy/cod-certificate-export.md). `GET /api/v1/va/<sid>/certificate` answers the data, already
 * redacted for the viewer; `certificateHtml` lays it out like the server's printable page
 * (app/templates/va_frontpages/va_cod_certificate.html) for `expo-print`. English only, as the web page.
 */
import { WorkspaceContractError } from "./contracts";

export interface CertificateCondition { text: string; code: string }
export interface CertificateLine { conditions: CertificateCondition[]; interval: string }
export interface CertificateData {
  project_name: string;
  case_id: string | null;
  age: string | number | null;
  sex: string | null;
  date_of_death: string;
  part1: CertificateLine[];
  part2: CertificateCondition[];
  underlying_cause: string | null;
  outcome: string;
  coded_at: string | null;
  generated_at: string | null;
  coded_by: string | null;
  reviewed_by: string | null;
  deceased_name: string | null;
  address: string | null;
  place_of_death: string | null;
  respondent: string | null;
  real_id: string | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const maybe = (value: unknown): string | null => (typeof value === "string" ? value : null);
const conditions = (value: unknown): CertificateCondition[] =>
  Array.isArray(value) ? value.filter(isRecord).map((c) => ({ text: text(c.text), code: text(c.code) })) : [];

/** Check the server's reply is a certificate object and keep only the fields the layout prints. */
export function parseCertificate(value: unknown): CertificateData {
  if (!isRecord(value) || !Array.isArray(value.part1) || !Array.isArray(value.part2)) throw new WorkspaceContractError("certificate");
  const age = value.age;
  return {
    project_name: text(value.project_name),
    case_id: maybe(value.case_id),
    age: typeof age === "string" || typeof age === "number" ? age : null,
    sex: maybe(value.sex),
    date_of_death: text(value.date_of_death),
    part1: value.part1.filter(isRecord).map((line) => ({ conditions: conditions(line.conditions), interval: text(line.interval) })),
    part2: conditions(value.part2),
    underlying_cause: maybe(value.underlying_cause),
    outcome: text(value.outcome),
    coded_at: maybe(value.coded_at),
    generated_at: maybe(value.generated_at),
    coded_by: maybe(value.coded_by),
    reviewed_by: maybe(value.reviewed_by),
    deceased_name: maybe(value.deceased_name),
    address: maybe(value.address),
    place_of_death: maybe(value.place_of_death),
    respondent: maybe(value.respondent),
    real_id: maybe(value.real_id),
  };
}

const esc = (value: string | number | null | undefined): string =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
const dash = (value: string | number | null | undefined): string => (value === null || value === undefined || value === "" ? "—" : esc(value));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");
/** DD-MMM-YYYY HH:MM:SS in the phone's local time (owner 2026-11-20). */
export const formatWhen = (iso: string | null): string => {
  if (!iso || Number.isNaN(Date.parse(iso))) return "—";
  const d = new Date(iso);
  return `${pad(d.getDate())}-${MONTHS[d.getMonth()]}-${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
/** A YYYY-MM-DD date as DD-MMM-YYYY; other text as stored. */
export const formatDate = (value: string): string => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return m ? `${m[3]}-${MONTHS[Number(m[2]) - 1]}-${m[1]}` : value || "—";
};
const when = (iso: string | null): string => esc(formatWhen(iso));
const cond = (c: CertificateCondition) => `<div>${esc(c.text)}${c.code ? ` <span class="small">[${esc(c.code)}]</span>` : ""}</div>`;
const LETTERS = "abcde";

/** The certificate as one A4 HTML document (every value escaped). Part I always has at least four lines, as the form. */
export function certificateHtml(c: CertificateData): string {
  const lines = [...c.part1];
  while (lines.length < 4) lines.push({ conditions: [], interval: "" });
  const part1 = lines.map((line, i) => `<tr>
      <td><strong>(${LETTERS[i] ?? ""})</strong>${i ? ' <span class="small">due to (or as a consequence of)</span>' : ""}
        ${line.conditions.length ? line.conditions.map(cond).join("") : '<div class="blank"></div>'}</td>
      <td>${esc(line.interval)}</td></tr>`).join("");
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Cause of death certificate ${esc(c.case_id)}</title>
<style>
@page { size: A4; margin: 14mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 11pt; color: black; background: white; margin: 0; }
h1 { font-size: 15pt; margin: 0 0 2px; text-align: center; }
.sub { text-align: center; font-size: 9pt; margin-bottom: 12px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
th, td { border: 1px solid black; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: lightgray; font-weight: bold; }
.frame { font-weight: bold; margin: 10px 0 4px; }
.blank { height: 1.6em; }
.small { font-size: 9pt; }
.foot { margin-top: 14px; border-top: 1px solid black; padding-top: 6px; font-size: 9pt; }
</style></head><body>
<h1>International Form of Medical Certificate of Cause of Death</h1>
<div class="sub">Coding result of a verbal autopsy, in the layout of the WHO form</div>
<table>
  <tr><th>Case id</th><td style="white-space:nowrap">${dash(c.case_id)}</td><th>Age</th><td>${dash(c.age)}</td><th>Sex</th><td>${dash(c.sex)}</td></tr>
  <tr><th>Date of death</th><td>${esc(formatDate(c.date_of_death))}</td><th>Place of death</th><td colspan="3">${dash(c.place_of_death)}</td></tr>
  <tr><th>Deceased</th><td colspan="2">${dash(c.deceased_name)}</td><th>Respondent</th><td colspan="2">${dash(c.respondent)}</td></tr>
  <tr><th>Address</th><td colspan="3">${dash(c.address)}</td><th>Identifier</th><td style="white-space:nowrap">${dash(c.real_id)}</td></tr>
</table>
<div class="frame">Frame A. Medical data: part 1 and part 2</div>
<table>
  <tr><th style="width:62%">1. Report disease or condition directly leading to death on line (a)</th><th>Approximate interval from onset to death</th></tr>
  ${part1}
  <tr><th colspan="2">2. Other significant conditions contributing to the death</th></tr>
  <tr><td colspan="2">${c.part2.length ? c.part2.map(cond).join("") : '<div class="blank"></div>'}</td></tr>
  <tr><th>Underlying cause of death</th><td>${esc(c.underlying_cause)}</td></tr>
</table>
<div class="frame">Coding</div>
<table>
  <tr><th>Date coded</th><td>${when(c.coded_at)}</td><th>Review</th><td>${esc(c.outcome)}</td></tr>
  <tr><th>Coded by</th><td>${dash(c.coded_by)}</td><th>Reviewed by</th><td>${dash(c.reviewed_by)}</td></tr>
</table>
<div class="foot">Cause of death assigned through verbal autopsy. Not a legal death certificate.<br>
Project: ${esc(c.project_name)} &middot; Generated ${when(c.generated_at)}</div>
</body></html>`;
}
