// Plain-language summary of one DORIS + CoDEdit run for the medical
// officer: the suggested underlying cause, anything that needs a manual
// check, and whether the certificate check found problems. The raw codes,
// URIs, reports and rule trace stay in the host's "Technical details".
'use strict';

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function lines(value) {
  return typeof value === 'string' ? value.split('\n').map(function (line) { return line.trim(); }).filter(Boolean) : [];
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

  var checks = lines(dr.warning);
  if (codedit.status !== 'completed') {
    checks.push('The certificate check (CoDEdit) did not run.');
  } else if (cr.issueIds) {
    var reported = lines(cr.report);
    checks = checks.concat(reported.length ? reported : ['The certificate check (CoDEdit) reported: ' + cr.issueIds]);
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
