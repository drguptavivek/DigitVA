// VA Intake dashboard (/intake/): project/site and unit pickers for new
// entries, and the interviewer worklist over GET /intake/api/cases
// (digitva-vzk.6, policy docs/policy/web-intake.md, "The list").
//
// Path A rules (docs/policy/field-data-collection.md): no case data in URLs
// or browser storage. localStorage holds only the chosen project/site, unit,
// tab and "Mine" switch. Every DOM write of server data goes through
// textContent / Option, never innerHTML.
(function () {
  var CSRF = '', CONTEXT = [], SCOPE = null;
  // Units for the picker come from the organization tree API, not from
  // bootstrap's grant-derived context: a project- or site-scoped interviewer
  // grant reaches every unit of the project, but interviewer_context() only
  // lists units from unit-scoped grants, so it would show an empty dropdown
  // for exactly the callers who most need one (see the server-side rule in
  // app/services/web_intake_service.py::_require_scope).
  var RENDER_TOKEN = 0;
  var UNITS = [], LEVELS = [], SELECTED_CODES = [], SELECTED_UNIT_ID = null;
  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function stored(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) {}
    return null;
  }

  // ---- Cascading unit picker: pure decision logic (no DOM access) ----
  //
  // Builds one tier per step of the actual parent/child forest found in
  // `units` -- NOT one tier per depth. DigitVA's org model allows a unit to
  // attach to a grandparent when an intervening level is optional (see
  // docs/policy/organization-model.md), so a branch can legitimately skip a
  // depth (e.g. a CHC hanging directly off a District because Taluka was
  // skipped). Enumerating tiers by the *global* sorted list of depths
  // present in `units` truncates those branches: the skipped depth's tier
  // filters by parent_code and finds nothing, so the cascade stops before
  // it ever reaches the unit that skipped ahead. Walking the forest instead
  // -- tier 0 is the roots, tier n+1 is whatever has parent_code equal to
  // what was selected at tier n -- reaches every branch regardless of which
  // depths it passes through.
  //
  // The server now returns every reachable unit's ancestors too (flagged
  // `selectable: false`, see app/routes/api/organization.py), so a
  // unit-scoped interviewer's picker has the full root-to-leaf chain to
  // render as context -- this function does not need to know which rows are
  // ancestors vs. grants; it only counts candidates at each tier. A "root"
  // for tier 0 is a unit with no parent_code, OR whose parent_code isn't
  // among the units returned -- a scoped response can start mid-tree.
  //
  // THE RULE, applied uniformly at every tier, no special-casing by depth or
  // by why a unit is or isn't reachable: a tier with exactly one candidate
  // (given what's selected above it) is FIXED — there's nothing to choose,
  // so it auto-selects that one unit and contributes it to the chain without
  // rendering a control. A tier with more than one candidate is a SELECT.
  // This is what makes a unit-scoped interviewer's District/Taluka/CHC
  // collapse to fixed text while their PHC (or above, if two granted PHCs
  // sit under different CHCs) still renders as a real choice — no branch in
  // this function cares whether the caller is unit-scoped or project-wide.
  //
  // Because levels can be skipped per-branch, the children of one parent can
  // sit at different levels (e.g. D1's children could be a Taluka and a CHC
  // side by side). Such a tier is `mixed: true` and gets a neutral label --
  // its options carry their own `level_code`/`level_name` so the caller can
  // render the level per option instead of mislabeling the whole tier with
  // the first candidate's level.
  //
  // `selectedCodes` is an array of unit_code values, one per tier, top-down
  // (ignored for a fixed tier, which always resolves to its one candidate).
  // The cascade stops -- no further tiers are produced -- the moment a tier
  // has zero candidates, or the moment a non-fixed tier has no valid
  // selection to descend from: a selected unit with nothing under it is a
  // legitimate place to stop (a unit-scoped interviewer with nothing below
  // their own unit, or a deployment that attributes above the leaf level).
  function optionsForLevels(units, levels, selectedCodes) {
    selectedCodes = selectedCodes || [];
    var levelNameByCode = {};
    (levels || []).forEach(function (l) { levelNameByCode[l.level_code] = l.level_name; });

    var codePresent = {};
    (units || []).forEach(function (u) { codePresent[u.unit_code] = true; });
    var byParent = {};
    (units || []).forEach(function (u) {
      var key = (u.parent_code && codePresent[u.parent_code]) ? u.parent_code : '__root__';
      if (!byParent[key]) byParent[key] = [];
      byParent[key].push(u);
    });

    var tiers = [];
    var parentKey = '__root__';
    var i = 0;
    while (true) {
      var candidates = (byParent[parentKey] || []).slice();
      if (!candidates.length) break; // Nothing reachable under this selection -- stop the cascade here.
      candidates.sort(function (a, b) { return (a.path || '').localeCompare(b.path || ''); });
      var levelCodesSeen = {};
      candidates.forEach(function (u) { levelCodesSeen[u.level_code] = true; });
      var mixed = Object.keys(levelCodesSeen).length > 1;
      var levelCode = mixed ? null : candidates[0].level_code;
      var fixed = candidates.length === 1;
      var selected;
      if (fixed) {
        selected = candidates[0].unit_code;
      } else {
        selected = selectedCodes[i] || null;
        var stillValid = selected && candidates.some(function (u) { return u.unit_code === selected; });
        if (!stillValid) selected = null;
      }
      tiers.push({
        level_code: levelCode,
        level_name: mixed ? 'Organization unit' : (levelNameByCode[levelCode] || levelCode),
        mixed: mixed,
        depth: candidates[0].depth,
        options: candidates.map(function (u) {
          return {
            unit_code: u.unit_code, unit_name: u.unit_name, org_unit_id: u.org_unit_id, path: u.path,
            level_code: u.level_code, level_name: levelNameByCode[u.level_code] || u.level_code
          };
        }),
        fixed: fixed,
        selected: selected
      });
      if (!selected) break; // Tier left unresolved -- nothing to filter the next tier by.
      parentKey = selected;
      i++;
    }
    return tiers;
  }

  // Walks a remembered unit's dot-separated `path` (root..leaf unit codes)
  // forward through the cascade, keeping only the prefix that still
  // validates against the currently fetched units — a deactivated or
  // out-of-scope ancestor breaks the chain at that point rather than
  // producing a select bound to a code that isn't actually offered.
  function restoreSelectedCodesFromChain(units, levels, rememberedOrgUnitId) {
    var remembered = (units || []).filter(function (u) { return u.org_unit_id === rememberedOrgUnitId; })[0];
    if (!remembered) return [];
    var chainCodes = String(remembered.path || '').split('.').filter(Boolean);
    var selectedCodes = [];
    for (var i = 0; i < chainCodes.length; i++) {
      var tiers = optionsForLevels(units, levels, selectedCodes);
      if (i >= tiers.length) break;
      var code = chainCodes[i];
      var valid = tiers[i].options.some(function (o) { return o.unit_code === code; });
      if (!valid) break;
      selectedCodes.push(code);
    }
    return selectedCodes;
  }

  // Default when nothing valid was remembered: a fixed tier already
  // resolves itself, and an editable tier defaults to its first option --
  // cascading down until a tier produces nothing further.
  function autoSelectFirstChain(units, levels) {
    var codes = [];
    while (true) {
      var tiers = optionsForLevels(units, levels, codes);
      var next = tiers[codes.length];
      if (!next) break;
      codes.push(next.selected || next.options[0].unit_code);
    }
    return codes;
  }
  function api(url, method, body) {
    var headers = { 'X-CSRFToken': CSRF };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(url, { method: method || 'GET', headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json()
          .catch(function () { return { error: 'Unexpected response from the server (HTTP ' + r.status + ').' }; })
          .then(function (d) { return { ok: r.ok, data: d || {} }; });
      })
      .catch(function () { return { ok: false, data: { error: 'Could not reach the server.' } }; });
  }
  function alertBox(kind, msg) { var box = $('intake-alert'); if (!msg) { box.classList.add('d-none'); return; } box.className = 'alert alert-' + kind + ' small py-2'; box.textContent = msg; }
  function scopeKey(c) { return c.project_id + '|' + c.site_id; }
  function currentScope() { return CONTEXT.filter(function (c) { return scopeKey(c) === SCOPE; })[0] || null; }
  function unitId() { return SELECTED_UNIT_ID; }
  function setBlocked(blocked, reason) {
    var deathLink = $('intake-new-death'), directBtn = $('intake-new-direct');
    if (blocked) {
      alertBox('danger', reason || 'No organization unit is available to you in this project, so a new entry cannot be routed to a coder.');
      deathLink.classList.add('disabled');
      deathLink.setAttribute('aria-disabled', 'true');
      deathLink.removeAttribute('href');
      directBtn.setAttribute('disabled', 'disabled');
    } else {
      alertBox();
      deathLink.classList.remove('disabled');
      deathLink.removeAttribute('aria-disabled');
      directBtn.removeAttribute('disabled');
    }
  }
  function updateNewDeathHref(c) {
    var deathLink = $('intake-new-death');
    if (deathLink.classList.contains('disabled')) return;
    deathLink.href = '/intake/deaths/new?project_id=' + encodeURIComponent(c.project_id) + '&site_id=' + encodeURIComponent(c.site_id) + (unitId() ? '&org_unit_id=' + encodeURIComponent(unitId()) : '');
  }

  api('/intake/api/bootstrap').then(function (res) {
    if (!res.ok) { alertBox('danger', res.data.error || 'Could not load intake context.'); return; }
    CSRF = res.data.csrf_token; CONTEXT = res.data.context || [];
    initWorklist();
    var sel = $('intake-scope');
    CONTEXT.forEach(function (c) { sel.add(new Option(c.project_id + ' / ' + c.site_id + ' — ' + c.project_name, scopeKey(c))); });
    if (!CONTEXT.length) { alertBox('warning', 'No project has web intake enabled for your interviewer grants.'); return; }
    SCOPE = stored('intake.scope');
    if (!SCOPE || !currentScope()) SCOPE = scopeKey(CONTEXT[0]);
    sel.value = SCOPE;
    sel.addEventListener('change', function () { SCOPE = this.value; stored('intake.scope', SCOPE); render(); });
    render();
  });

  function render() {
    var c = currentScope(); if (!c) return;
    var mode = c.web_intake_mode;
    $('intake-new-death').classList.toggle('d-none', !(mode === 'death_register' || mode === 'both'));
    $('intake-new-direct').classList.toggle('d-none', !(mode === 'direct' || mode === 'both'));
    loadUnits(c);
  }

  // Renders one control per tier returned by optionsForLevels: fixed text
  // for a tier with exactly one candidate, an editable <select> otherwise.
  // Wires the selects' change handlers. Returns the tiers it rendered, so
  // callers can read back the resulting selection.
  function renderUnitTiers(units, levels, selectedCodes) {
    var container = $('intake-unit-levels');
    var tiers = optionsForLevels(units, levels, selectedCodes);
    container.replaceChildren();
    tiers.forEach(function (tier, i) {
      var cell = el('div', 'flex-fill');
      cell.style.minWidth = '160px';
      cell.appendChild(el('label', 'form-label small mb-1', tier.level_name || ('Level ' + tier.depth)));
      if (tier.fixed) {
        var only = tier.options[0];
        var fixed = el('div', 'form-control form-control-sm bg-light text-body-secondary', only.unit_code + ' — ' + only.unit_name);
        fixed.setAttribute('aria-readonly', 'true');
        cell.appendChild(fixed);
        container.appendChild(cell);
        return;
      }
      var tierSel = el('select', 'form-select form-select-sm');
      tier.options.forEach(function (o) {
        // A mixed tier's options can sit at different org levels (an
        // optional level was skipped on some branches but not others), so
        // each option names its own level instead of relying on a tier
        // heading that would be wrong for at least one of them.
        var text = tier.mixed
          ? (o.level_name || o.level_code) + ': ' + o.unit_code + ' — ' + o.unit_name
          : o.unit_code + ' — ' + o.unit_name;
        var isSel = o.unit_code === tier.selected;
        tierSel.add(new Option(text, o.unit_code, isSel, isSel));
      });
      tierSel.addEventListener('change', function () {
        // Changing a tier resets and re-filters every tier below it — a
        // stale deeper selection from a previous branch must not survive.
        SELECTED_CODES = SELECTED_CODES.slice(0, i);
        SELECTED_CODES.push(this.value);
        applySelection();
      });
      cell.appendChild(tierSel);
      container.appendChild(cell);
    });
    return tiers;
  }

  // Re-renders the cascade from SELECTED_CODES, resolves the deepest
  // selected tier's org_unit_id (the value actually submitted — the
  // interviewer may legitimately stop above a leaf), and persists it.
  function applySelection() {
    var tiers = renderUnitTiers(UNITS, LEVELS, SELECTED_CODES);
    SELECTED_CODES = tiers.map(function (t) { return t.selected; });
    var deepest = null;
    for (var i = tiers.length - 1; i >= 0; i--) {
      if (tiers[i].selected) {
        for (var j = 0; j < tiers[i].options.length; j++) {
          if (tiers[i].options[j].unit_code === tiers[i].selected) { deepest = tiers[i].options[j].org_unit_id; break; }
        }
        break;
      }
    }
    SELECTED_UNIT_ID = deepest;
    stored('intake.unit', SELECTED_UNIT_ID || null);
    var c = currentScope();
    if (c) updateNewDeathHref(c);
    setBlocked(!SELECTED_UNIT_ID, SELECTED_UNIT_ID ? null : 'Select an organization unit to continue.');
  }

  function loadUnits(c) {
    var token = ++RENDER_TOKEN;
    var wrap = $('intake-unit-wrap'), levelsEl = $('intake-unit-levels');
    function failClosed(message) {
      // Never let a unit-less submission through silently because the
      // picker could not be built.
      wrap.classList.add('d-none');
      levelsEl.replaceChildren();
      UNITS = []; LEVELS = []; SELECTED_CODES = []; SELECTED_UNIT_ID = null;
      setBlocked(true, message);
    }
    fetch('/api/v1/organization/' + encodeURIComponent(c.project_id) + '/units?role=interviewer')
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; }); })
      .then(function (res) {
        if (token !== RENDER_TOKEN) return; // a newer scope change is in flight
        if (!res.ok) {
          failClosed(res.data && res.data.error ? res.data.error : 'Could not load organization units (HTTP ' + res.status + ').');
          return;
        }
        LEVELS = res.data.levels || [];
        UNITS = res.data.units || [];
        var hasTree = LEVELS.length > 0;
        wrap.classList.toggle('d-none', !hasTree);
        if (!hasTree) {
          levelsEl.replaceChildren();
          SELECTED_CODES = []; SELECTED_UNIT_ID = null;
          setBlocked(false);
        } else if (!UNITS.length) {
          levelsEl.replaceChildren();
          SELECTED_CODES = []; SELECTED_UNIT_ID = null;
          setBlocked(true, 'No organization unit is available to you in this project, so a new entry cannot be routed to a coder.');
        } else {
          var saved = stored('intake.unit');
          var restored = saved ? restoreSelectedCodesFromChain(UNITS, LEVELS, saved) : [];
          SELECTED_CODES = restored.length ? restored : autoSelectFirstChain(UNITS, LEVELS);
          applySelection();
        }
        updateNewDeathHref(c);
      })
      .catch(function () {
        if (token !== RENDER_TOKEN) return;
        failClosed('Could not reach the server to load organization units.');
      });
  }

  // Opens the questionnaire: `body` names the project/site (and unit for a
  // direct start, or the case for a register-first one).
  function openDraft(body, button) {
    if (button) button.disabled = true;
    api('/intake/api/drafts', 'POST', body).then(function (res) {
      if (!res.ok) {
        if (button) button.disabled = false;
        alertBox('danger', res.data.error || 'Could not start the questionnaire.');
        return;
      }
      window.location.href = '/intake/form/' + encodeURIComponent(res.data.draft.draft_id);
    });
  }
  $('intake-new-direct').addEventListener('click', function () {
    var c = currentScope(); if (!c) return;
    openDraft({ project_id: c.project_id, site_id: c.site_id, org_unit_id: unitId() }, this);
  });

  // ---- Worklist ----
  //
  // One list over GET /intake/api/cases (team cases in scope across every
  // project-site of the caller's interviewer grants, newest activity first,
  // keyset-paged). Tabs group case states; counts come from the API's
  // per-state counts, which ignore the state filter but honour "Mine".
  var TABS = {
    visit: ['registered', 'scheduled', 'not_reachable', 'paused'],
    progress: ['in_progress', 'draft_identity'],
    done: ['submitted', 'refused', 'duplicate', 'cancelled']
  };
  var STATE_BADGE = {
    draft_identity: ['Details pending', 'text-bg-light border'],
    registered: ['Registered', 'text-bg-primary'],
    scheduled: ['Scheduled', 'text-bg-info'],
    not_reachable: ['Not reachable', 'text-bg-warning'],
    paused: ['Paused', 'text-bg-warning'],
    in_progress: ['In progress', 'text-bg-primary'],
    refused: ['Refused', 'text-bg-danger'],
    submitted: ['Submitted', 'text-bg-success'],
    duplicate: ['Closed', 'text-bg-secondary'],
    cancelled: ['Closed', 'text-bg-secondary']
  };
  // Mirrors _FLAGGABLE in app/services/case_transition_service.py, only to
  // decide which buttons to show; the server is the authority.
  var FLAGGABLE = {
    duplicate: ['registered', 'scheduled', 'in_progress', 'paused', 'submitted'],
    cancel: ['registered', 'scheduled', 'in_progress', 'paused']
  };
  var STARTABLE = ['draft_identity', 'registered', 'scheduled', 'paused', 'not_reachable', 'refused', 'in_progress'];
  var REASON_MAX = 200;
  var REASON_WARNING = 'No names, phone numbers or addresses in the reason.';
  var TAB = 'visit', MINE = false, NEXT_CURSOR = null, LIST_TOKEN = 0;
  var TZ = $('intake-worklist').dataset.userTz || 'Asia/Kolkata';
  var dateTimeFormat;
  try {
    dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: TZ });
  } catch (e) {
    dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' });
  }
  function formatWhen(iso) {
    var parsed = iso ? new Date(iso) : null;
    return parsed && !isNaN(parsed) ? dateTimeFormat.format(parsed) : '—';
  }

  function initWorklist() {
    var savedTab = stored('intake.tab');
    if (TABS[savedTab]) TAB = savedTab;
    MINE = stored('intake.mine') === '1';
    $('intake-mine').checked = MINE;
    $('intake-mine').addEventListener('change', function () {
      MINE = this.checked;
      stored('intake.mine', MINE ? '1' : '0');
      loadWorklist(true);
    });
    Array.prototype.forEach.call(document.querySelectorAll('#intake-tabs [data-tab]'), function (btn) {
      btn.addEventListener('click', function () {
        TAB = btn.dataset.tab;
        stored('intake.tab', TAB);
        loadWorklist(true);
      });
    });
    $('intake-load-more').addEventListener('click', function () { loadWorklist(false); });
    loadWorklist(true);
  }

  function loadWorklist(reset) {
    var token = ++LIST_TOKEN;
    var rows = $('intake-worklist-rows'), more = $('intake-load-more');
    Array.prototype.forEach.call(document.querySelectorAll('#intake-tabs [data-tab]'), function (btn) {
      var active = btn.dataset.tab === TAB;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $('intake-worklist-scope').textContent = MINE
      ? 'Cases you registered, started or worked on.'
      : 'Team cases in your scope.';
    if (reset) { NEXT_CURSOR = null; rows.replaceChildren(); }
    more.disabled = true;
    var url = '/intake/api/cases?state=' + encodeURIComponent(TABS[TAB].join(','))
      + '&mine=' + (MINE ? 'true' : 'false')
      + (NEXT_CURSOR ? '&cursor=' + encodeURIComponent(NEXT_CURSOR) : '');
    api(url).then(function (res) {
      if (token !== LIST_TOKEN) return; // a newer tab/filter change is in flight
      more.disabled = false;
      var empty = $('intake-worklist-empty');
      if (!res.ok) {
        // Shown in place of the list too: on a phone the alert is scrolled off.
        empty.textContent = res.data.error || 'Could not load the worklist.';
        empty.classList.remove('d-none');
        return;
      }
      empty.textContent = 'No cases here.';
      var counts = res.data.counts || {};
      Object.keys(TABS).forEach(function (tab) {
        var total = TABS[tab].reduce(function (sum, state) { return sum + (counts[state] || 0); }, 0);
        document.querySelector('#intake-tabs [data-count="' + tab + '"]').textContent = String(total);
      });
      (res.data.cases || []).forEach(function (row) { rows.appendChild(renderRow(row)); });
      NEXT_CURSOR = res.data.next_cursor || null;
      more.classList.toggle('d-none', !NEXT_CURSOR);
      empty.classList.toggle('d-none', rows.children.length > 0);
    });
  }

  function renderRow(row) {
    var item = el('li', 'list-group-item px-2 py-2');
    var head = el('div', 'd-flex justify-content-between align-items-start gap-2');
    head.appendChild(el('strong', 'text-break', row.details_pending ? 'New interview' : (row.deceased_name || '—')));
    var badge = STATE_BADGE[row.state] || [row.state, 'text-bg-secondary'];
    head.appendChild(el('span', 'badge ' + badge[1] + ' flex-shrink-0', badge[0]));
    item.appendChild(head);

    item.appendChild(el('div', 'small text-break', [
      row.unique_id,
      row.deceased_sex || '—',
      row.age_years != null ? row.age_years + ' y' : 'age —',
      'died ' + (row.date_of_death || '—'),
      row.unit_name || 'no unit'
    ].join(' · ')));
    var meta = el('div', 'small text-muted', 'Updated ' + formatWhen(row.updated_at));
    if (row.pending_flag) {
      meta.appendChild(document.createTextNode(' '));
      meta.appendChild(el('span', 'badge text-bg-warning', row.pending_flag === 'duplicate' ? 'Duplicate flag pending' : 'Cancel flag pending'));
    }
    item.appendChild(meta);

    var actions = el('div', 'd-flex flex-wrap gap-2 mt-2');
    var panel = el('div', 'mt-2 d-none');
    if (row.my_draft_id) {
      var resume = el('a', 'btn btn-sm btn-primary', 'Resume');
      resume.href = '/intake/form/' + encodeURIComponent(row.my_draft_id);
      actions.appendChild(resume);
    } else if (STARTABLE.indexOf(row.state) !== -1) {
      var label = row.state === 'refused' ? 'Restart'
        : (row.state === 'in_progress' || row.state === 'draft_identity') ? 'Resume' : 'Start';
      var start = el('button', 'btn btn-sm btn-primary', label);
      start.type = 'button';
      start.addEventListener('click', function () {
        openDraft({ project_id: row.project_id, site_id: row.site_id, death_id: row.death_id }, start);
      });
      actions.appendChild(start);
    }
    if (!row.pending_flag) {
      if (FLAGGABLE.duplicate.indexOf(row.state) !== -1) {
        actions.appendChild(flagButton('Flag duplicate', function () { showFlagForm(panel, row, 'duplicate'); }));
      }
      if (FLAGGABLE.cancel.indexOf(row.state) !== -1) {
        actions.appendChild(flagButton('Flag for cancel', function () { showFlagForm(panel, row, 'cancel'); }));
      }
    }
    if (actions.children.length) item.appendChild(actions);
    item.appendChild(panel);
    return item;
  }

  function flagButton(text, onClick) {
    var b = el('button', 'btn btn-sm btn-outline-secondary', text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  // Inline form under the row (no modal: easier on a phone). A duplicate
  // names the kept case by death_id, picked from cases in scope.
  function showFlagForm(panel, row, kind) {
    panel.replaceChildren();
    panel.classList.remove('d-none');
    var form = el('form', 'border rounded p-2 bg-light');
    var picker = null;
    if (kind === 'duplicate') {
      form.appendChild(el('label', 'form-label small mb-1', 'Same death as case'));
      picker = el('select', 'form-select form-select-sm mb-2');
      picker.required = true;
      picker.add(new Option('Loading cases…', ''));
      form.appendChild(picker);
      loadDuplicateOptions(picker, row);
    }
    form.appendChild(el('label', 'form-label small mb-1', kind === 'cancel' ? 'Reason for cancelling' : 'Reason (optional)'));
    var reason = el('input', 'form-control form-control-sm');
    reason.type = 'text';
    reason.maxLength = REASON_MAX;
    reason.required = kind === 'cancel';
    reason.autocomplete = 'off';
    form.appendChild(reason);
    form.appendChild(el('div', 'form-text text-danger mb-2', REASON_WARNING));
    var buttons = el('div', 'd-flex flex-wrap gap-2');
    var submit = el('button', 'btn btn-sm btn-warning', kind === 'cancel' ? 'Send cancel flag' : 'Send duplicate flag');
    submit.type = 'submit';
    var close = el('button', 'btn btn-sm btn-outline-secondary', 'Close');
    close.type = 'button';
    close.addEventListener('click', function () { panel.replaceChildren(); panel.classList.add('d-none'); });
    buttons.appendChild(submit);
    buttons.appendChild(close);
    form.appendChild(buttons);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var body = { kind: kind, reason: reason.value.trim() };
      if (picker) body.duplicate_of = picker.value;
      submit.disabled = true;
      api('/intake/api/cases/' + encodeURIComponent(row.death_id) + '/flags', 'POST', body).then(function (res) {
        submit.disabled = false;
        if (!res.ok) { alertBox('danger', res.data.error || 'Could not flag the case.'); return; }
        alertBox('success', 'Case ' + row.unique_id + ' flagged. A supervisor will confirm or reject it.');
        loadWorklist(true);
      });
    });
    panel.appendChild(form);
  }

  // ponytail: first 200 cases by recent activity (the API's page cap); a
  // server-side search by case id is the upgrade when scopes outgrow that.
  function loadDuplicateOptions(picker, row) {
    api('/intake/api/cases?limit=200').then(function (res) {
      picker.replaceChildren();
      if (!res.ok) { picker.add(new Option(res.data.error || 'Could not load cases.', '')); return; }
      var options = (res.data.cases || []).filter(function (c) {
        return c.death_id !== row.death_id && c.project_id === row.project_id
          && ['duplicate', 'cancelled', 'draft_identity'].indexOf(c.state) === -1;
      });
      picker.add(new Option(options.length ? 'Choose the case it duplicates' : 'No other case in scope', ''));
      options.forEach(function (c) {
        picker.add(new Option([c.unique_id, c.deceased_name || '—', c.date_of_death || '—'].join(' — '), c.death_id));
      });
    });
  }
}());
