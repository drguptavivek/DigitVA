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

      var adminBtn = '';
      if (!isSelf) {
        adminBtn = '<button class="btn btn-sm py-0 px-2 user-admin-btn '
          + (isAdmin ? 'btn-outline-warning' : 'btn-outline-secondary') + '"'
          + ' data-id="' + esc(u.user_id) + '"'
          + ' data-email="' + esc(u.email) + '"'
          + ' data-admin="' + (isAdmin ? '1' : '0') + '"'
          + ' title="' + (isAdmin ? 'Revoke admin' : 'Grant admin') + '">'
          + '<i class="fa-solid fa-shield-halved"></i>'
          + '</button>';
      } else {
        adminBtn = '<button class="btn btn-sm py-0 px-2 btn-outline-secondary" disabled title="Cannot change own admin"><i class="fa-solid fa-shield-halved"></i></button>';
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
        + '<td class="align-middle py-2 text-end">' + adminBtn + ' ' + toggleBtn + ' ' + editBtn + '</td>'
        + '</tr>';
    }).join('');

    wrap.innerHTML = '<div class="table-responsive"><table class="table table-sm table-hover align-middle mb-0">'
      + '<thead class="table-light"><tr>'
      + '<th class="fw-medium small text-muted">User</th>'
      + '<th class="fw-medium small text-muted" style="width:20%;">Phone</th>'
      + '<th class="fw-medium small text-muted" style="width:20%;">VA Languages</th>'
      + '<th class="fw-medium small text-muted" style="width:10%;">Status</th>'
      + '<th class="fw-medium small text-muted text-end" style="width:18%;">Actions</th>'
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

    // Bind admin toggle buttons
    var adminBtns = wrap.querySelectorAll('.user-admin-btn');
    for (var k = 0; k < adminBtns.length; k++) {
      adminBtns[k].addEventListener('click', function () {
        var userId = this.getAttribute('data-id');
        var isAdmin = this.getAttribute('data-admin') === '1';
        toggleAdmin(userId, isAdmin);
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

  // ── admin toggle ──────────────────────────────────────────────────────────

  function toggleAdmin(userId) {
    apiJson('/admin/api/users/' + encodeURIComponent(userId) + '/toggle-admin', 'POST').then(function (res) {
      if (!res.ok) {
        var wrap = document.getElementById('user-table-wrap');
        wrap.insertAdjacentHTML('afterbegin', '<div class="alert alert-danger small py-2 mt-2">' + esc(res.data.error || 'Failed.') + '</div>');
        return;
      }
      _users = _users.map(function (u) {
        return u.user_id === userId ? Object.assign({}, u, { is_admin: res.data.is_admin }) : u;
      });
      renderTable();
    });
  }

  // ── form handling ─────────────────────────────────────────────────────────

  var formContainer = document.getElementById('user-form-container');
  var formTitle = document.getElementById('user-form-title');
  var emailInput = document.getElementById('user-email-input');
  var nameInput = document.getElementById('user-name-input');
  var phoneInput = document.getElementById('user-phone-input');
  var passwordInput = document.getElementById('user-password-input');
  var passwordAsterisk = document.getElementById('user-password-asterisk');
  var passwordHelp = document.getElementById('user-password-help');
  var statusInput = document.getElementById('user-status-input');
  var languagesInput = $('#user-languages-input');
  var errEl = document.getElementById('user-form-error');

  function resetForm() {
    _editingId = null;
    formTitle.textContent = 'Create User';
    emailInput.value = '';
    emailInput.disabled = false;
    nameInput.value = '';
    phoneInput.value = '';
    passwordInput.value = '';
    passwordAsterisk.classList.remove('d-none');
    passwordHelp.textContent = '';
    statusInput.value = 'active';
    statusInput.disabled = true; // New users are always active
    languagesInput.val([]).trigger('change');
    errEl.textContent = '';
  }

  function openEditForm(userId) {
    var user = _users.find(function(u) { return u.user_id === userId; });
    if (!user) return;

    _editingId = userId;
    formTitle.textContent = 'Edit User';
    emailInput.value = user.email;
    emailInput.disabled = true;
    nameInput.value = user.name;
    phoneInput.value = user.phone || '';
    passwordInput.value = '';
    passwordAsterisk.classList.add('d-none');
    passwordHelp.textContent = '(Leave blank to keep unchanged)';
    statusInput.value = user.status;
    statusInput.disabled = (userId === CURRENT_USER_ID); // Cannot change own status
    languagesInput.val(user.languages || []).trigger('change');
    errEl.textContent = '';

    formContainer.classList.remove('d-none');
    nameInput.focus();
  }

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
      if (!data.email) { errEl.textContent = 'Email is required.'; return; }
      if (!data.password) { errEl.textContent = 'Password is required for new users.'; return; }
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
