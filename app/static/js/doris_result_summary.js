// Plain-language summary of one DORIS + CoDEdit run for the medical
// officer: the suggested underlying cause, anything that needs a manual
// check, and whether the certificate check found problems. The raw codes,
// URIs, reports and rule trace stay in the host's "Technical details".
'use strict';

import { codeditMessages } from './codedit_messages.js';

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function lines(value) {
  return typeof value === 'string' ? value.split('\n').map(function (line) { return line.trim(); }).filter(Boolean) : [];
}

// DORIS warns with a bare rule id ("M4 may have been applied.") and explains
// the rule in its report ("M4: Adding the main injury - NC72.Z - as
// postcoordination for the current TUC - PA60."). Join the two, spelling
// out TUC and TSP, so a coder need not know WHO's rule numbers.
function explained(warning, report) {
  var rule = warning.match(/^(SP\d+|M\d+)\b(?!:)/);
  if (!rule) return warning;
  var detail = lines(report).find(function (line) { return line.indexOf(rule[1] + ':') === 0; });
  if (!detail) return warning;
  detail = detail.slice(rule[1].length + 1).trim()
    .replace(/\bTUC\b/g, 'tentative underlying cause').replace(/\bTSP\b/g, 'tentative starting point');
  return warning.replace(/\.$/, '') + ': ' + detail;
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

// lookupTitle(code) -> Promise<string>; used only when the code is not on
// the certificate (DORIS can select a code nobody typed, e.g. KD3B.1).
export function renderSummary(container, processing, certificate, lookupTitle) {
  var doris = processing.doris || {}; var codedit = processing.codedit || {};
  var dr = doris.result || {}; var cr = codedit.result || {};
  container.replaceChildren();

  if (doris.status !== 'completed') {
    container.appendChild(el('div', 'alert alert-danger py-2 mb-2', 'DORIS did not run (' + String(doris.status || 'unavailable').replaceAll('_', ' ') + '). Choose the underlying cause without it.'));
  } else if (dr.reject || !dr.code) {
    container.appendChild(el('div', 'alert alert-danger py-2 mb-2', 'DORIS could not select an underlying cause from this certificate.' + (dr.error ? ' ' + dr.error : '')));
  } else {
    container.appendChild(el('p', 'small text-muted mb-1', 'DORIS suggests this underlying cause'));
    var headline = el('p', 'doris-summary-headline mb-2');
    var title = el('span', 'fw-semibold', certificateTitle(certificate || {}, [dr.code, dr.stemCode]));
    headline.append(el('span', 'doris-summary-code', dr.code), document.createTextNode(' '), title);
    container.appendChild(headline);
    if (!title.textContent && lookupTitle) {
      lookupTitle(dr.code).then(function (text) { if (text && title.isConnected) title.textContent = text; }).catch(function () {});
    }
  }

  var checks = lines(dr.warning).map(function (warning) { return explained(warning, dr.report); });
  if (codedit.status !== 'completed') {
    checks.push('The certificate check (CoDEdit) did not run.');
  } else if (cr.issueIds) {
    checks = checks.concat(codeditChecks(cr));
  }
  if (checks.length) {
    container.appendChild(el('p', 'small fw-semibold mb-1', 'Check before you decide'));
    var list = el('ul', 'doris-summary-checks mb-0');
    checks.forEach(function (text) { list.appendChild(el('li', '', text)); });
    container.appendChild(list);
  } else if (doris.status === 'completed') {
    container.appendChild(el('p', 'small text-success mb-0', 'No problems found in the certificate.'));
  }
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
