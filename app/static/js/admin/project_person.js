// Roster person page (digitva-eyp3): one person in one project. Config comes
// from data attributes on #person-root; policy
// docs/policy/dm-user-grant-management.md, "Roster User Panel".
(function () {
  'use strict';

  var root = document.getElementById('person-root');
  var projectId = root.getAttribute('data-project-id');
  var userId = root.getAttribute('data-user-id');
  var tz = root.getAttribute('data-timezone') || 'UTC';
  var rosterUrl = root.getAttribute('data-roster-url');

  function csrfHeaders() {
    return { 'Content-Type': 'application/json', 'X-CSRFToken': window._adminCsrf || '' };
  }

  // Every value goes in with textContent; the server decides what may be
  // changed (may_edit_account, may_issue_code, may_remove) and checks it again.
  function upEl(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function upBase() {
    return '/admin/api/projects/' + encodeURIComponent(projectId) + '/users-grid/' + encodeURIComponent(userId);
  }
  function upMsg(kind, text) {
    var box = document.getElementById('person-msg');
    box.className = text ? 'alert alert-' + kind + ' py-1 px-2 mb-2' : 'd-none';
    box.textContent = text || '';
  }
  function upSend(method, path, body) {
    return fetch(upBase() + path, { method: method, headers: csrfHeaders(), body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }, function () { return { ok: false, data: {} }; }); });
  }
  function upWhen(iso) {
    if (!iso) return '';
    try { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: tz }).format(new Date(iso)); }
    catch (e) { return new Date(iso).toLocaleString(); }
  }
  function upSection(title) {
    var sec = upEl('section', 'mb-3');
    sec.appendChild(upEl('h6', 'border-bottom pb-1', title));
    return sec;
  }
  function upField(form, label, input) {
    var wrap = upEl('label', 'form-label d-block mb-2');
    wrap.appendChild(upEl('span', 'd-block text-muted', label));
    wrap.appendChild(input);
    form.appendChild(wrap);
    return input;
  }
  function upProfile(d) {
    var u = d.user, sec = upSection('Profile');
    if (!d.may_edit_account) {
      var dl = upEl('dl', 'row mb-1');
      [['Name', u.name], ['Age', u.age === null ? '' : u.age], ['Sex', u.sex || ''],
       ['Coding languages', (u.languages || []).join(', ')], ['Email', u.email || 'Mobile-only'], ['Phone', u.phone || '']]
        .forEach(function (pair) { dl.appendChild(upEl('dt', 'col-4', pair[0])); dl.appendChild(upEl('dd', 'col-8', pair[1])); });
      sec.appendChild(dl);
      sec.appendChild(upEl('div', 'text-muted', 'This account is shared with other projects, so its details are read-only here.'));
      return sec;
    }
    var form = upEl('form', '');
    var name = upField(form, 'Name', upEl('input', 'form-control form-control-sm'));
    name.maxLength = 128; name.value = u.name || '';
    var age = upField(form, 'Age (years)', upEl('input', 'form-control form-control-sm'));
    age.type = 'number'; age.min = 0; age.max = 130; age.value = u.age === null ? '' : u.age;
    var sex = upField(form, 'Sex', upEl('select', 'form-select form-select-sm'));
    [['', '—'], ['female', 'Female'], ['male', 'Male'], ['undetermined', 'Undetermined']].forEach(function (o) {
      var opt = upEl('option', '', o[1]); opt.value = o[0]; sex.appendChild(opt);
    });
    sex.value = u.sex || '';
    var langs = upEl('fieldset', 'mb-2');
    langs.appendChild(upEl('legend', 'form-label text-muted fs-6 mb-1', 'Coding languages (pick one or more)'));
    var grid = upEl('div', 'd-flex flex-wrap gap-3');
    (d.language_options || []).forEach(function (o) {
      var item = upEl('label', 'form-check mb-0');
      var box = upEl('input', 'form-check-input'); box.type = 'checkbox'; box.value = o.code;
      box.checked = (u.languages || []).indexOf(o.code) !== -1;
      item.appendChild(box); item.appendChild(upEl('span', 'form-check-label', o.name));
      grid.appendChild(item);
    });
    langs.appendChild(grid); form.appendChild(langs);
    sec.appendChild(upEl('div', 'text-muted mb-2', (u.email || 'Mobile-only') + (u.phone ? ' · ' + u.phone : '')));
    var save = upEl('button', 'btn btn-sm btn-primary', 'Save profile'); save.type = 'submit';
    form.appendChild(save);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      save.disabled = true;
      var body = { name: name.value, age: age.value, sex: sex.value || null,
                   languages: Array.prototype.map.call(langs.querySelectorAll('input:checked'), function (b) { return b.value; }) };
      upSend('PATCH', '/profile', body).then(function (res) {
        save.disabled = false;
        if (!res.ok) { upMsg('danger', res.data.error || 'Could not save the profile.'); return; }
        upMsg('success', res.data.changed && res.data.changed.length ? 'Profile saved.' : 'Nothing changed.');
        upLoad();
      }, function () { save.disabled = false; upMsg('danger', 'Could not save the profile.'); });
    });
    sec.appendChild(form);
    return sec;
  }
  function upList(title, items, empty, line) {
    var sec = upSection(title);
    if (!items.length) { sec.appendChild(upEl('div', 'text-muted', empty)); return sec; }
    var ul = upEl('ul', 'list-unstyled mb-0');
    items.forEach(function (x) { ul.appendChild(upEl('li', 'mb-1', line(x))); });
    sec.appendChild(ul);
    return sec;
  }
  function upActions(d) {
    var u = d.user, sec = upSection('Actions'), row = upEl('div', 'd-flex flex-wrap gap-2 align-items-center');
    if (d.may_edit_account && u.email && u.email_verified) {
      var reset = upEl('button', 'btn btn-sm btn-outline-primary', 'Reset password'); reset.type = 'button';
      reset.addEventListener('click', function () {
        reset.disabled = true;
        upSend('POST', '/password-reset').then(function (res) {
          upMsg(res.ok ? 'success' : 'danger', res.ok ? 'A reset link was sent to their email.' : (res.data.error || 'Could not send the reset link.'));
          reset.disabled = res.ok;
        }, function () { reset.disabled = false; upMsg('danger', 'Could not send the reset link.'); });
      });
      row.appendChild(reset);
    } else if (u.email && !u.email_verified) {
      row.appendChild(upEl('span', 'text-muted', 'Email not verified yet: resend verification from Users.'));
    }
    if (d.may_issue_code) {
      var code = upEl('button', 'btn btn-sm btn-outline-primary', 'Generate code'); code.type = 'button';
      code.addEventListener('click', function () {
        code.disabled = true;
        upSend('POST', '/sign-in-code').then(function (res) {
          if (!res.ok || !res.data.sign_in_code) { code.disabled = false; upMsg('danger', res.data.error || 'Could not generate a sign-in code.'); return; }
          var shown = upEl('span', 'font-monospace fw-semibold fs-6', res.data.sign_in_code);
          code.replaceWith(shown);
          shown.insertAdjacentElement('afterend', upEl('span', 'text-muted', 'valid ' + (res.data.expires_in_minutes || 90) + ' minutes'));
        }, function () { code.disabled = false; upMsg('danger', 'Could not generate a sign-in code.'); });
      });
      row.appendChild(code);
    }
    if (d.may_remove) {
      var rm = upEl('button', 'btn btn-sm btn-outline-danger', 'Remove from this project'); rm.type = 'button';
      rm.addEventListener('click', function () {
        // Inline confirm, not window.confirm.
        rm.classList.add('d-none');
        var ask = upEl('span', 'd-inline-flex align-items-center gap-1');
        ask.appendChild(upEl('span', '', 'Remove their access, unit placement and membership in this project?'));
        var yes = upEl('button', 'btn btn-sm btn-danger py-0', 'Yes, remove'); yes.type = 'button';
        var no = upEl('button', 'btn btn-sm btn-outline-secondary py-0', 'Cancel'); no.type = 'button';
        ask.appendChild(yes); ask.appendChild(no);
        rm.insertAdjacentElement('afterend', ask);
        no.addEventListener('click', function () { ask.remove(); rm.classList.remove('d-none'); });
        yes.addEventListener('click', function () {
          yes.disabled = true;
          upSend('POST', '/remove').then(function (res) {
            ask.remove(); rm.classList.remove('d-none');
            if (!res.ok) { upMsg('danger', res.data.error || 'Could not remove this person.'); return; }
            window.location.href = rosterUrl;
          }, function () { ask.remove(); rm.classList.remove('d-none'); upMsg('danger', 'Could not remove this person.'); });
        });
        yes.focus();
      });
      row.appendChild(rm);
    }
    if (!row.childNodes.length) row.appendChild(upEl('span', 'text-muted', 'No actions available.'));
    sec.appendChild(row);
    return sec;
  }
  function upRender(d) {
    document.getElementById('person-name').textContent = d.user.name || 'Person';
    var body = document.getElementById('person-body');
    body.replaceChildren(
      upProfile(d),
      upList('Grants', d.grants, 'No active grants in your projects.', function (g) {
        return g.role + ' · ' + g.project_id + (g.site_id ? ' / ' + g.site_id : '') + (g.unit_code ? ' / ' + g.unit_code + (g.unit_name ? ' ' + g.unit_name : '') : '') + (g.cadre_code ? ' (' + g.cadre_code + ')' : '');
      }),
      upList('Phones', d.phones, 'Not signed in on any phone.', function (p) {
        return (p.name || 'Phone') + (p.platform ? ' · ' + p.platform : '') + (p.app_version ? ' ' + p.app_version : '') + ' · signed in' + (p.last_seen_at ? ', last seen ' + upWhen(p.last_seen_at) : '');
      }),
      upList('Activity: submissions in this project', d.activity.submissions, 'No submission activity in this project.', function (a) {
        return upWhen(a.at) + ' · ' + a.action + ' · ' + a.form_id;
      }),
      upList('Activity: account', d.activity.events, 'No account events.', function (ev) {
        return upWhen(ev.at) + ' · ' + ev.type.replace(/_/g, ' ') + (ev.actor_name ? ' · by ' + ev.actor_name : '');
      }),
      upActions(d)
    );
  }
  function upLoad() {
    fetch(upBase(), { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) { document.getElementById('person-body').replaceChildren(upEl('div', 'text-danger', res.data.error || 'Could not load this person.')); return; }
        upRender(res.data);
      }, function () { document.getElementById('person-body').replaceChildren(upEl('div', 'text-danger', 'Could not load this person.')); });
  }
  upLoad();
}());
