// Renders /admin/api/projects/<id>/web-intake-readiness for people, not for
// the API: plain labels instead of check codes, "To do / Check / Done"
// instead of fail/warn/ok, and a neutral "Off" state for projects that do
// not capture interviews in the browser (docs/policy/web-intake.md).
// Used by the Project Setup Overview and the Projects panel edit form.
(function () {
  'use strict';

  var LABELS = {
    mode: 'Web capture switched on',
    sites: 'Active sites',
    web_forms: 'Web form for every site',
    form_type: 'Questionnaire',
    locales: 'Questionnaire languages',
    interviewers: 'Interviewers',
    org_tree: 'Organization tree',
    org_unplaced: 'Units placed in the tree',
    geography_fields: 'Geography questions',
    coding_scope: 'Coding scope'
  };
  var STATES = {
    fail: { word: 'To do', cls: 'text-bg-danger' },
    warn: { word: 'Check', cls: 'text-bg-warning' },
    ok: { word: 'Done', cls: 'text-bg-success' }
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function isOff(result) {
    return (result.checks || []).some(function (c) {
      return c.code === 'mode' && c.status === 'fail';
    });
  }

  // opts.fixLink(code) may return extra HTML (e.g. a "Go to Basics" link)
  // shown under an open item.
  function render(result, listEl, summaryEl, opts) {
    opts = opts || {};
    if (isOff(result)) {
      listEl.innerHTML = '<div class="small text-muted py-1 border-top">'
        + 'Web capture is off: this project collects interviews through ODK only, '
        + 'so nothing here needs attention. The checklist applies once Web Intake '
        + 'is set to direct entry, death register or both.</div>';
      summaryEl.innerHTML = '<span class="badge text-bg-secondary">Off (ODK only)</span>';
      return;
    }
    listEl.innerHTML = (result.checks || []).map(function (c) {
      var st = STATES[c.status] || { word: c.status, cls: 'text-bg-secondary' };
      var open = c.status !== 'ok';
      var fix = open && opts.fixLink ? opts.fixLink(c.code) : '';
      return '<div class="d-flex align-items-start gap-2 py-1 border-top">'
        + '<span class="badge ' + st.cls + '" style="min-width:3.4rem;">' + esc(st.word) + '</span>'
        + '<div class="small">'
        +   '<div><span class="fw-semibold">' + esc(LABELS[c.code] || c.code) + '.</span> ' + esc(c.message) + '</div>'
        +   (open && c.fix_hint ? '<div class="text-muted">' + esc(c.fix_hint) + '</div>' : '')
        +   (fix || '')
        + '</div></div>';
    }).join('');
    summaryEl.innerHTML = result.ready
      ? '<span class="badge text-bg-success">Ready for web capture</span>'
      : '<span class="badge text-bg-danger">Not ready for web capture</span>';
  }

  window.WebCaptureReadiness = { render: render, label: function (code) { return LABELS[code] || code; } };
}());
