(function () {
  'use strict';

  var panel = document.getElementById('panel-users');
  if (!panel || panel.dataset.initialized) return;
  panel.dataset.initialized = '1';

  function csrf() { return window._adminCsrf || ''; }

  function apiJson(url, method, body) {
    var m = method || 'GET';
    var headers = { 'X-CSRFToken': csrf() };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(url, {
      method: m, headers: headers,
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); });
  }

  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── state & render ────────────────────────────────────────────────────────

  var _users = [];
  var _editingId = null;
  var _searchTimeout = null;
  var CURRENT_USER_ID = window._adminState && window._adminState.user ? window._adminState.user.user_id : null;
  var AVAILABLE_LANGUAGES = JSON.parse(panel.dataset.languages || '[]');

  function loadUsers() {
    var wrap = document.getElementById('user-table-wrap');
    wrap.innerHTML = '<div class="text-center text-muted py-4 small"><i class="fa-solid fa-spinner fa-spin me-1"></i>Loading…</div>';

    var showInactive = document.getElementById('user-show-inactive').checked ? '1' : '0';
    var query = document.getElementById('user-search-input').value.trim();
    var url = '/admin/api/users?master=1&include_inactive=' + showInactive;
    if (query) url += '&query=' + encodeURIComponent(query);

    apiJson(url).then(function (res) {
      if (!res.ok) {
        wrap.innerHTML = '<div class="alert alert-danger small py-2">' + esc(res.data.error || 'Failed to load.') + '</div>';
        return;
      }
      _users = res.data.users || [];
      renderTable();
    }).catch(function () {
      wrap.innerHTML = '<div class="alert alert-danger small py-2">Network error.</div>';
    });
  }

  function renderTable() {
    var wrap = document.getElementById('user-table-wrap');
    if (!_users.length) {
      wrap.innerHTML = '<p class="text-muted small text-center py-3">No users found.</p>';
      return;
    }

    var rows = _users.map(function (u) {
      var isActive = u.status === 'active';
      var isSelf = u.user_id === CURRENT_USER_ID;
      var isAdmin = !!u.is_admin;

      var toggleBtn = '';
      if (!isSelf) {
        toggleBtn = '<button class="btn btn-sm py-0 px-2 user-toggle-btn '
          + (isActive ? 'btn-outline-danger' : 'btn-outline-success') + '"'
          + ' data-id="' + esc(u.user_id) + '"'
          + ' data-email="' + esc(u.email) + '"'
          + ' data-active="' + (isActive ? '1' : '0') + '"'
          + ' title="' + (isActive ? 'Deactivate' : 'Activate') + '">'
          + '<i class="fa-solid ' + (isActive ? 'fa-toggle-on' : 'fa-toggle-off') + '"></i>'
          + '</button>';
      } else {
        toggleBtn = '<button class="btn btn-sm py-0 px-2 btn-outline-secondary" disabled title="Cannot toggle self"><i class="fa-solid fa-toggle-on"></i></button>';
      }

      var editBtn = '<button class="btn btn-sm py-0 px-2 btn-outline-primary user-edit-btn" '
        + ' data-id="' + esc(u.user_id) + '" title="Edit">'
        + '<i class="fa-solid fa-pen"></i></button>';

      var adminBadge = isAdmin ? ' <span class="badge text-bg-warning small">Admin</span>' : '';

      return '<tr class="' + (isActive ? '' : 'text-muted') + '">'
        + '<td class="align-middle py-2">'
        +   '<div class="fw-semibold small">' + esc(u.name) + adminBadge + '</div>'
        +   '<div class="small text-muted">' + esc(u.email) + '</div>'
        + '</td>'
        + '<td class="align-middle py-2 small">' + esc(u.phone || '') + '</td>'
        + '<td class="align-middle py-2 small">' + esc((u.languages || []).join(', ')) + '</td>'
        + '<td class="align-middle py-2">'
        + (isActive
            ? '<span class="badge text-bg-success">Active</span>'
            : '<span class="badge text-bg-secondary">Inactive</span>')
        + '</td>'
        + '<td class="align-middle py-2 text-end">' + toggleBtn + ' ' + editBtn + '</td>'
        + '</tr>';
    }).join('');

    wrap.innerHTML = '<div class="table-responsive"><table class="table table-sm table-hover align-middle mb-0">'
      + '<thead class="table-light"><tr>'
      + '<th class="fw-medium small text-muted">User</th>'
      + '<th class="fw-medium small text-muted" style="width:20%;">Phone</th>'
      + '<th class="fw-medium small text-muted" style="width:20%;">VA Languages</th>'
      + '<th class="fw-medium small text-muted" style="width:10%;">Status</th>'
      + '<th class="fw-medium small text-muted text-end" style="width:14%;">Actions</th>'
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody>'
      + '</table></div>';

    // Bind edit buttons
    var editBtns = wrap.querySelectorAll('.user-edit-btn');
    for (var i = 0; i < editBtns.length; i++) {
      editBtns[i].addEventListener('click', function() {
        var id = this.getAttribute('data-id');
        openEditForm(id);
      });
    }

    // Bind toggle buttons
    var toggleBtns = wrap.querySelectorAll('.user-toggle-btn');
    for (var j = 0; j < toggleBtns.length; j++) {
      toggleBtns[j].addEventListener('click', function () {
        promptToggle(this.getAttribute('data-id'), this.getAttribute('data-email'), this.getAttribute('data-active') === '1');
      });
    }
  }

  document.getElementById('user-show-inactive').addEventListener('change', function () {
    loadUsers();
  });

  document.getElementById('user-search-input').addEventListener('input', function () {
    clearTimeout(_searchTimeout);
    _searchTimeout = setTimeout(loadUsers, 300);
  });

  // ── toggle modal ──────────────────────────────────────────────────────────

  var _pendingToggleId = null;
  var _toggleModal = null;

  function promptToggle(userId, email, isActive) {
    var action = isActive ? 'Deactivate' : 'Activate';
    var color  = isActive ? 'text-danger' : 'text-success';
    document.getElementById('user-toggle-modal-label').innerHTML =
      '<i class="fa-solid fa-toggle-' + (isActive ? 'off' : 'on') + ' ' + color + ' me-2"></i>' + action + ' User';
    var body = action + ' <strong>' + esc(email) + '</strong>?';
    if (isActive) {
      body += '<div class="text-danger small mt-2"><i class="fa-solid fa-triangle-exclamation me-1"></i>'
        + 'User will no longer be able to log in or access granted resources.</div>';
    }
    document.getElementById('user-toggle-modal-body').innerHTML = body;
    var confirmBtn = document.getElementById('user-toggle-confirm-btn');
    confirmBtn.className = 'btn btn-sm ' + (isActive ? 'btn-danger' : 'btn-success');
    confirmBtn.textContent = action;
    _pendingToggleId = userId;
    if (!_toggleModal) _toggleModal = new bootstrap.Modal(document.getElementById('user-toggle-modal'));
    _toggleModal.show();
  }

  document.getElementById('user-toggle-confirm-btn').addEventListener('click', function () {
    if (!_pendingToggleId) return;
    var userId = _pendingToggleId;
    _pendingToggleId = null;
    _toggleModal.hide();
    var btn = this;
    btn.disabled = true;
    apiJson('/admin/api/users/' + encodeURIComponent(userId) + '/toggle', 'POST').then(function (res) {
      btn.disabled = false;
      if (!res.ok) {
        var wrap = document.getElementById('user-table-wrap');
        wrap.insertAdjacentHTML('afterbegin', '<div class="alert alert-danger small py-2 mt-2">' + esc(res.data.error || 'Failed.') + '</div>');
        return;
      }
      var newStatus = res.data.status;
      _users = _users.map(function (u) {
        return u.user_id === userId ? Object.assign({}, u, { status: newStatus }) : u;
      });
      renderTable();
    }).catch(function () { btn.disabled = false; });
  });

  // ── form handling ─────────────────────────────────────────────────────────

  var formContainer = document.getElementById('user-form-container');
  var formTitle = document.getElementById('user-form-title');
  var emailInput = document.getElementById('user-email-input');
  var emailConfirmInput = document.getElementById('user-email-confirm-input');
  var emailConfirmAsterisk = document.getElementById('user-email-confirm-asterisk');
  var nameInput = document.getElementById('user-name-input');
  var phoneInput = document.getElementById('user-phone-input');
  var passwordCol = document.getElementById('user-password-col');
  var passwordInput = document.getElementById('user-password-input');
  var passwordAsterisk = document.getElementById('user-password-asterisk');
  var passwordHelp = document.getElementById('user-password-help');
  var statusInput = document.getElementById('user-status-input');
  var languagesInput = $('#user-languages-input');
  var adminRow = document.getElementById('admin-toggle-row');
  var adminSwitch = document.getElementById('user-admin-input');
  var errEl = document.getElementById('user-form-error');

  function resetForm() {
    _editingId = null;
    formTitle.textContent = 'Create User';
    emailInput.value = '';
    emailInput.disabled = false;
    emailConfirmInput.value = '';
    emailConfirmInput.disabled = false;
    emailConfirmAsterisk.classList.remove('d-none');
    nameInput.value = '';
    phoneInput.value = '';
    passwordInput.value = '';
    passwordCol.classList.add('d-none');
    passwordAsterisk.classList.add('d-none');
    passwordHelp.textContent = 'Invite flow: user sets password from email link.';
    statusInput.value = 'active';
    statusInput.disabled = true; // New users are always active
    languagesInput.val([]).trigger('change');
    adminRow.classList.add('d-none');
    adminSwitch.checked = false;
    errEl.textContent = '';
  }

  function openEditForm(userId) {
    var user = _users.find(function(u) { return u.user_id === userId; });
    if (!user) return;

    _editingId = userId;
    formTitle.textContent = 'Edit User';
    emailInput.value = user.email;
    emailInput.disabled = true;
    emailConfirmInput.value = '';
    emailConfirmInput.disabled = true;
    emailConfirmAsterisk.classList.add('d-none');
    nameInput.value = user.name;
    phoneInput.value = user.phone || '';
    passwordCol.classList.remove('d-none');
    passwordInput.value = '';
    passwordAsterisk.classList.add('d-none');
    passwordHelp.textContent = '(Leave blank to keep unchanged)';
    statusInput.value = user.status;
    statusInput.disabled = (userId === CURRENT_USER_ID); // Cannot change own status
    languagesInput.val(user.languages || []).trigger('change');
    errEl.textContent = '';

    // Show admin toggle (hidden for self)
    if (userId === CURRENT_USER_ID) {
      adminRow.classList.add('d-none');
    } else {
      adminRow.classList.remove('d-none');
      adminSwitch.checked = !!user.is_admin;
    }

    formContainer.classList.remove('d-none');
    nameInput.focus();
  }

  // Admin switch — immediate toggle via API
  adminSwitch.addEventListener('change', function () {
    if (!_editingId) return;
    var userId = _editingId;
    var switchEl = this;
    switchEl.disabled = true;
    apiJson('/admin/api/users/' + encodeURIComponent(userId) + '/toggle-admin', 'POST').then(function (res) {
      switchEl.disabled = false;
      if (!res.ok) {
        switchEl.checked = !switchEl.checked;
        errEl.textContent = res.data.error || 'Failed to toggle admin.';
        return;
      }
      _users = _users.map(function (u) {
        return u.user_id === userId ? Object.assign({}, u, { is_admin: res.data.is_admin }) : u;
      });
      // No re-render needed — switch already reflects the new state
    }).catch(function () {
      switchEl.disabled = false;
      switchEl.checked = !switchEl.checked;
      errEl.textContent = 'Network error.';
    });
  });

  document.getElementById('user-form').addEventListener('submit', function (e) { e.preventDefault(); });

  document.getElementById('user-show-form-btn').addEventListener('click', function () {
    resetForm();
    formContainer.classList.remove('d-none');
    emailInput.focus();
  });

  document.getElementById('user-cancel-btn').addEventListener('click', function () {
    formContainer.classList.add('d-none');
    resetForm();
  });

  document.getElementById('user-submit-btn').addEventListener('click', function () {
    errEl.textContent = '';

    var data = {
      name: nameInput.value.trim(),
      phone: phoneInput.value.trim(),
      password: passwordInput.value,
      languages: languagesInput.val()
    };

    var url, method;

    if (_editingId) {
      url = '/admin/api/users/' + encodeURIComponent(_editingId);
      method = 'PUT';
      data.status = statusInput.value;
      if (!data.password) delete data.password;
    } else {
      url = '/admin/api/users';
      method = 'POST';
      data.email = emailInput.value.trim().toLowerCase();
      data.email_confirm = emailConfirmInput.value.trim().toLowerCase();
      if (!data.email) { errEl.textContent = 'Email is required.'; return; }
      if (!data.email_confirm) { errEl.textContent = 'Confirm email is required.'; return; }
      if (data.email !== data.email_confirm) { errEl.textContent = 'Email confirmation does not match.'; return; }
      delete data.password;
    }

    if (!data.name) { errEl.textContent = 'Name is required.'; return; }

    var btn = this;
    btn.disabled = true;
    apiJson(url, method, data).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { errEl.textContent = res.data.error || 'Failed.'; return; }
      formContainer.classList.add('d-none');
      loadUsers();
    }).catch(function () {
      btn.disabled = false;
      errEl.textContent = 'Network error.';
    });
  });

  // ── init ──────────────────────────────────────────────────────────────────

  AVAILABLE_LANGUAGES.forEach(function (lang) {
    languagesInput.append(new Option(lang.name, lang.code, false, false));
  });
  languagesInput.select2({
    placeholder: 'Select languages…',
    width: '100%',
    theme: 'bootstrap-5'
  });

  loadUsers();

}());
