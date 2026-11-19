// Plain-language summary of one DORIS + CoDEdit run for the medical
// officer: the suggested underlying cause, anything that needs a manual
// check, and whether the certificate check found problems. The raw codes,
// URIs and reports sit under its "Details" (as on the Expo screen).
'use strict';

import { codeditMessages } from './codedit_messages.js';
import { describeWarning, warningCodes } from './doris_warnings.js?v=1';

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function lines(value) {
  return typeof value === 'string' ? value.split('\n').map(function (line) { return line.trim(); }).filter(Boolean) : [];
}

// CoDEdit's report is a sentence for front-end rules but a bare key for
// back-end ones (RE_W_IV_CodeURIMismatch). Its tabular report has one row per
// issue, "n,KEY,BER-CE-9;param0;param1", so a bare key is replaced by WHO's
// published sentence for that ID with the parameters filled in.
function codeditChecks(result) {
  var rows = lines(result.tabularReport).map(function (row) {
    var fields = row.split(';'); var head = fields[0].split(',');
    return {key: head[1], id: head[2], params: fields.slice(1)};
  });
  var checks = lines(result.report).map(function (line) {
    if (/\s/.test(line)) return line;
    var row = rows.find(function (candidate) { return candidate.key === line; });
    var template = row && codeditMessages[row.id];
    if (!template) return 'The certificate check (CoDEdit) reported ' + line + (row && row.id ? ' (' + row.id + ').' : '.');
    return template.replace(/\{(\d+)\}/g, function (_match, index) { return row.params[Number(index)] || ''; })
      .replace(/ [-\u2013] +[-\u2013] /g, ' ').replace(/\(\s*\)/g, '').replace(/\s{2,}/g, ' ').trim();
  });
  return checks.length ? checks : ['The certificate check (CoDEdit) reported: ' + result.issueIds];
}

// Text the certifier typed for this code, if DORIS picked a certificate line.
function certificateTitle(certificate, codes) {
  var parts = [].concat(certificate.Part1 || [], certificate.Part2 ? [certificate.Part2] : []);
  for (var i = 0; i < parts.length; i += 1) {
    var conditions = parts[i].Conditions || [];
    for (var j = 0; j < conditions.length; j += 1) {
      if (conditions[j].Code && codes.indexOf(conditions[j].Code) !== -1) return conditions[j].Text || '';
    }
  }
  return '';
}

// An empty CoDEdit issue list ([] or '') names nothing: it must not add a "reported:" item.
function hasIssueIds(value) { return Array.isArray(value) ? value.length > 0 : Boolean(value); }

var UCOD_ROLE_NOTE = {stem: '', extension: ' (extension)', postcoordinated: ' (manifestation)'};
export var UCOD_CLUSTER_EXPLANATION = 'A "/" joins the stem code DORIS chose as the underlying cause to the code(s) it attached to it as manifestations or details; "&" adds an extension code to a stem.';

// The computed UCOD as titled codes (server-resolved ucod_parts), one line each:
// "Underlying cause: CODE title", then "+ CODE title (manifestation)", then the full code as a chip
// (same layout as the Expo screen).
function appendUcodCluster(container, parts, dr) {
  var cluster = el('div', 'doris-summary-cluster mb-2');
  parts.forEach(function (part, index) {
    var label = part.title ? part.code + ' ' + part.title : part.code;
    cluster.appendChild(el('div', '', index === 0 ? 'Underlying cause: ' + label : '+ ' + label + (UCOD_ROLE_NOTE[part.role] || '')));
  });
  if (typeof dr.code === 'string') cluster.appendChild(el('span', 'doris-summary-code', dr.code));
  container.appendChild(cluster);
}

// Without ucod_parts (older saved runs) the code alone is the cause; its title
// comes from the certificate or, failing that, WHO via lookupTitle.
function appendBareCode(container, dr, certificate, lookupTitle) {
  var title = el('span', '', certificateTitle(certificate || {}, [dr.code, dr.stemCode]));
  var line = el('div', 'doris-summary-cluster mb-2');
  line.append(document.createTextNode('Underlying cause: '), el('span', 'doris-summary-code', dr.code), document.createTextNode(' '), title);
  container.appendChild(line);
  if (!title.textContent && lookupTitle) {
    lookupTitle(dr.code).then(function (text) { if (text && title.isConnected) title.textContent = text; }).catch(function () {});
  }
}

// Report text ready to show: CRLF to LF, trailing spaces dropped, a run of blank lines collapsed to one
// (collapseBlankLines in the Expo resultSummary.ts). '' when there is nothing, so no empty box is drawn.
export function collapseBlankLines(value) {
  if (typeof value !== 'string') return '';
  return value.replace(/\r\n?/g, '\n').replace(/[ \t]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim();
}

// Collapsed "Details": the "/" and "&" explanation, stem, URI and the DORIS, CoDEdit and tabular reports.
function appendCodeDetails(container, parts, dr, cr) {
  var many = Array.isArray(parts) && parts.length > 1;
  var reports = [dr.report, cr.report, cr.tabularReport].map(collapseBlankLines).filter(Boolean);
  if (!many && typeof dr.stemCode !== 'string' && typeof dr.uri !== 'string' && !reports.length) return;
  var details = el('details', 'small text-muted mb-2');
  details.appendChild(el('summary', '', 'Details'));
  if (many) details.appendChild(el('div', '', UCOD_CLUSTER_EXPLANATION));
  if (typeof dr.stemCode === 'string') details.appendChild(el('div', '', 'Computed stem: ' + dr.stemCode));
  if (typeof dr.uri === 'string') details.appendChild(el('div', '', 'Computed URI: ' + dr.uri));
  reports.forEach(function (report) { details.appendChild(el('pre', 'small text-wrap border rounded p-2 mt-2 mb-0', report)); });
  container.appendChild(details);
}

// lookupTitle(code) -> Promise<string>; used only when the code is not on
// the certificate (DORIS can select a code nobody typed, e.g. KD3B.1).
export function renderSummary(container, processing, certificate, lookupTitle) {
  var doris = processing.doris || {}; var codedit = processing.codedit || {};
  var dr = doris.result || {}; var cr = codedit.result || {};
  container.replaceChildren();

  // WHO's reason is shown in full, as the Expo screen does.
  container.appendChild(el('h5', 'h6 mb-2', 'DORIS and CoDEdit'));
  container.appendChild(el('p', 'small mb-1', 'DORIS: ' + (doris.status || 'not processed')));
  if (typeof dr.error === 'string' && dr.error) container.appendChild(el('div', 'alert alert-danger py-2 mb-2', dr.error));
  if (dr.reject === true || doris.status === 'rejected') container.appendChild(el('div', 'alert alert-danger py-2 mb-2', 'DORIS rejected the certificate result.'));
  if (doris.status !== 'completed' && doris.status !== 'rejected') {
    container.appendChild(el('div', 'alert alert-danger py-2 mb-2', 'DORIS did not run (' + String(doris.status || 'unavailable').replaceAll('_', ' ') + '). Choose the underlying cause without it.'));
  } else if (doris.status === 'completed' && (dr.reject || !dr.code)) {
    container.appendChild(el('div', 'alert alert-danger py-2 mb-2', 'DORIS could not select an underlying cause from this certificate.'));
  } else if (doris.status === 'completed') {
    if (Array.isArray(processing.ucod_parts) && processing.ucod_parts.length) appendUcodCluster(container, processing.ucod_parts, dr);
    else appendBareCode(container, dr, certificate, lookupTitle);
  }

  (processing.who_notes || []).forEach(function (note) { container.appendChild(el('p', 'small text-muted mb-1', note)); });

  // A known DORIS warning shows its meaning and what to do, with DORIS's text
  // smaller underneath; titles arrive after the first paint (lookupTitle).
  var warnings = lines(dr.warning);
  var titles = {};
  var codeditChecksList = [];
  if (codedit.status !== 'completed') {
    codeditChecksList.push('The certificate check (CoDEdit) did not run.');
  } else if (hasIssueIds(cr.issueIds) || lines(cr.report).length) {
    codeditChecksList = codeditChecks(cr);
  }
  if (warnings.length || codeditChecksList.length) {
    container.appendChild(el('p', 'small fw-semibold mb-1', 'Check before you decide'));
    var list = el('ul', 'doris-summary-checks mb-0');
    var described = warnings.map(function (warning) {
      var item = {warning: warning, known: false, text: null};
      var text = describeWarning(warning, dr.report, function (code) { return titles[code]; });
      item.known = text.original !== null;
      if (!item.known) { list.appendChild(el('li', '', text.text)); return item; }
      var li = el('li'); item.text = el('span', '', text.text); li.appendChild(item.text);
      li.appendChild(el('div', 'small text-muted', 'DORIS: ' + text.original));
      list.appendChild(li);
      return item;
    });
    codeditChecksList.forEach(function (text) { list.appendChild(el('li', '', text)); });
    container.appendChild(list);
    if (lookupTitle) {
      warningCodes(dr.warning).forEach(function (code) {
        lookupTitle(code).then(function (title) {
          if (!title) return;
          titles[code] = title;
          described.forEach(function (item) {
            if (item.known) item.text.textContent = describeWarning(item.warning, dr.report, function (known) { return titles[known]; }).text;
          });
        }).catch(function () {});
      });
    }
  } else if (doris.status === 'completed') {
    container.appendChild(el('p', 'small text-success mb-0', 'No problems found in the certificate.'));
  }
  appendCodeDetails(container, processing.ucod_parts, dr, cr);
  container.appendChild(el('hr', 'my-2'));
  container.appendChild(el('p', 'small mb-0', 'CoDEdit: ' + (codedit.status || 'not processed')));
}

// The code Step 2's "Use DORIS result" should enter, or '' if none.
// DORIS can return a mortality cluster that WHO codeinfo does not resolve:
// for an injury death it puts the external cause first (PA60/NC72.Z), while
// codeinfo only accepts NC72.Z/PA60, whose stem is the injury. Offer the
// full code when it resolves, otherwise DORIS's stem, which is the
// underlying cause itself. resolves(code) -> Promise<boolean>.
export function usableDorisCode(processing, resolves) {
  var doris = processing.doris || {}; var dr = doris.result || {};
  if (doris.status !== 'completed' || dr.reject || !dr.code) return Promise.resolve('');
  return resolves(dr.code).then(function (ok) {
    if (ok) return dr.code;
    if (!dr.stemCode || dr.stemCode === dr.code) return '';
    return resolves(dr.stemCode).then(function (stemOk) { return stemOk ? dr.stemCode : ''; });
  });
}

// The Step 2 button's label: "Use DORIS result: CODE — title"; the code alone until its title is known
// (DorisPanel.tsx dorisQuickChoices).
export function useDorisLabel(code, title) {
  return 'Use DORIS result: ' + code + (title ? ' — ' + title : '');
}
