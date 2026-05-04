(function () {
'use strict';
  const CONFIG = window.DIGITVA_CODING_DASHBOARD || {};
  const CSRF_TOKEN = CONFIG.csrfToken || '';
  const DEMO_PROJECTS = CONFIG.demoProjects || [];

  async function apiFetch(url) {
    const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    const contentType = r.headers.get('content-type') || '';
    if (contentType.indexOf('application/json') === -1) {
      throw new Error(`${url} returned non-JSON content`);
    }
    return r.json();
  }

  function valueOrZero(value) {
    return value === null || value === undefined ? 0 : value;
  }

  // ── mode label ────────────────────────────────────────────────────────────
  function modeLabel(hasRandom, hasPick) {
    if (hasRandom && hasPick) return 'Modes: Random, Manual Selection';
    if (hasPick)              return 'Mode: Manual Selection';
    if (hasRandom)            return 'Mode: Random';
    return '';
  }

  // ── project selector ──────────────────────────────────────────────────────
  const _PROJECT_SELECT_KEY = 'digitva_coding_project_select';

  let PROJECT_OPTIONS = [];

  function selectedProjectLabel(projectId) {
    if (!projectId) return 'All Projects';
    const match = PROJECT_OPTIONS.find(project => project.project_id === projectId);
    if (!match) return projectId;
    if (!match.project_name || match.project_name === match.project_id) {
      return match.project_id;
    }
    return `${match.project_id} - ${match.project_name}`;
  }

  function updateSelectedProjectName() {
    const sel = document.getElementById('project-select-top');
    const target = document.getElementById('selected-project-name');
    const historySuffix = document.getElementById('history-project-suffix');
    if (!sel) return;
    const projectId = sel.value.trim().toUpperCase();
    if (target) {
      target.textContent = selectedProjectLabel(projectId);
    }
    if (historySuffix) {
      historySuffix.textContent = projectId ? `: ${projectId}` : "";
    }
  }

  function populateProjectSelector(projects, projectOptions) {
    const sel = document.getElementById('project-select-top');
    PROJECT_OPTIONS = Array.isArray(projectOptions) && projectOptions.length
      ? projectOptions
      : (projects || []).map(projectId => ({ project_id: projectId, project_name: projectId }));
    projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p; opt.textContent = p;
      sel.appendChild(opt);
    });
    // Restore previous selection
    const saved = localStorage.getItem(_PROJECT_SELECT_KEY);
    if (saved && Array.from(sel.options).some(o => o.value === saved)) {
      sel.value = saved;
    }
    updateSelectedProjectName();
  }

  // ── action buttons ────────────────────────────────────────────────────────
  function continuePendingLabel(allocation) {
    if (!allocation) return 'Continue Pending Coding';
    const loc = (allocation.project_id && allocation.site_id)
      ? ` — ${allocation.project_id} / ${allocation.site_id}`
      : (allocation.project_id ? ` — ${allocation.project_id}` : '');
    return 'Continue Pending Coding' + loc;
  }

  function renderActionButtons(allocation, randomReady, mode) {
    const el = document.getElementById('action-buttons');
    let html = '<div class="d-inline-flex align-items-center gap-2 flex-wrap justify-content-center">';

    if (mode) {
      html += `<span class="text-secondary small me-1"><i class="fas fa-layer-group me-1"></i>${mode}</span>`;
    }

    if (allocation) {
      const continueLabel = continuePendingLabel(allocation);
      html += `<a href="/coding/resume" class="btn btn-primary">
        <i class="fas fa-edit me-2"></i>${continueLabel}
      </a>`;
    } else if (randomReady > 0) {
      html += `<button id="start-btn" class="btn btn-primary">
        <i class="fas fa-edit me-2"></i>Start Random Allocation Coding
      </button>`;
    }

    if (DEMO_PROJECTS.length) {
      html += `<button id="demo-coding-shortcut-btn" class="btn btn-outline-warning"${allocation ? ' disabled title="Finish your pending coding first"' : ''}>
        <i class="fas fa-flask me-2"></i>DEMO-CODING
      </button>`;
    }

    html += '</div>';
    el.innerHTML = html;
  }

  // ── pick table ────────────────────────────────────────────────────────────
  let pickTableInstance = null;
  let ALL_PICK_FORMS = [];

  function selectedProjectId() {
    const sel = document.getElementById('project-select-top');
    return sel ? sel.value.trim().toUpperCase() || null : null;
  }

  function renderPickTable(forms, hasAllocation) {
    const section = document.getElementById('pick-section');
    const badge   = document.getElementById('pick-badge');
    const tbody   = document.getElementById('pick-tbody');

    if (!forms.length) {
      section.style.display = 'none';
      badge.textContent = '0 ready';
      if (pickTableInstance) {
        pickTableInstance.destroy();
        pickTableInstance = null;
        $('#pickCodingTable').find('tbody').empty();
      }
      return;
    }

    section.style.display = '';
    badge.textContent = `${forms.length} ready`;

    tbody.innerHTML = forms.map(row => {
      const actionCell = hasAllocation
        ? `<button class="btn btn-sm btn-outline-secondary" disabled>Continue current coding first</button>`
        : `<form method="POST" action="/coding/pick/${row.va_sid}" style="display:inline"><input type="hidden" name="csrf_token" value="${CSRF_TOKEN}"><button type="submit" class="btn btn-sm btn-outline-primary">Start Coding</button></form>`;
      return `<tr>
        <td>${row.project_id || ''}</td>
        <td>${row.site_id || ''}</td>
        <td>${row.va_submission_date || ''}</td>
        <td>${row.va_uniqueid_masked || ''}</td>
        <td>${row.va_data_collector || '-'}</td>
        <td>${row.va_deceased_age || '-'} / ${row.va_deceased_gender || '-'}</td>
        <td>${actionCell}</td>
      </tr>`;
    }).join('');

    if (pickTableInstance) { pickTableInstance.destroy(); }
    pickTableInstance = $('#pickCodingTable').DataTable({
      pageLength: 10,
      order: [[0, 'asc'], [1, 'asc'], [2, 'asc']],
      columnDefs: [{ targets: 6, orderable: false, searchable: false }],
    });
  }

  function applyProjectFilterToPick(hasAllocation) {
    const pid = selectedProjectId();
    const filteredForms = pid
      ? ALL_PICK_FORMS.filter(row => (row.project_id || '').toUpperCase() === pid)
      : ALL_PICK_FORMS;
    renderPickTable(filteredForms, hasAllocation);
  }

  // ── history table ─────────────────────────────────────────────────────────
  let historyTableInstance = null;
  const configuredTimezone = CONFIG.timezone || '';
  const historyLocale = navigator.language || undefined;
  const historyTimezone = configuredTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone;

  function formatHistoryDateTime(isoValue) {
    if (!isoValue) return '-';
    const parsed = new Date(isoValue);
    if (Number.isNaN(parsed.getTime())) return isoValue;
    try {
      return new Intl.DateTimeFormat(historyLocale, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: historyTimezone,
      }).format(parsed);
    } catch (error) {
      return isoValue;
    }
  }

  function initHistoryTable(history) {
    if (historyTableInstance) {
      historyTableInstance.destroy();
      $('#vaTable').empty();
      $('#columnToggles').empty();
    }

    historyTableInstance = $('#vaTable').DataTable({
      data: history,
      order: [[0, 'asc']],
      columns: [
        { data: '_priority',          title: '',                visible: false },
        { data: 'project_id',         title: 'Project Code' },
        { data: 'site_id',            title: 'Site Code' },
        { data: 'va_submission_date', title: 'Submission Date', visible: false },
        { data: 'va_sid',             title: 'SID',             visible: false },
        { data: 'va_uniqueid_masked', title: 'VA Form ID' },
        { data: 'va_deceased_age',    title: 'H1',              visible: false },
        { data: 'va_deceased_gender', title: 'H2',              visible: false },
        { data: null, title: 'Age / Gender',
          render: r => `${r.va_deceased_age || '-'} / ${r.va_deceased_gender || '-'}` },
        { data: 'va_code_status', title: 'VA Code Status',
          render: d => {
            if (d === '__pending__') return '<span class="badge bg-warning text-dark">In Progress</span>';
            if (d === 'VA Coding Completed') return '<span class="badge bg-success">VA Coding Completed</span>';
            return '<span class="badge bg-danger">Not Codeable</span>';
          }
        },
        { data: 'va_coding_date', title: 'VA Coding Date',
          render: d => formatHistoryDateTime(d) },
        { data: null, title: 'Action', orderable: false,
          render: (_, __, row) => {
            if (row.va_code_status === '__pending__') {
              return `<a href="/coding/resume" class="btn btn-sm btn-primary">Continue</a>`;
            }
            let html = `<a href="/coding/view/${row.va_sid}" class="btn btn-sm btn-outline-primary me-1">View</a>`;
            if (row.recodeable) {
              html += `<form method="POST" action="/coding/recode/${row.va_sid}" style="display:inline"><input type="hidden" name="csrf_token" value="${CSRF_TOKEN}"><button type="submit" class="btn btn-sm btn-outline-danger">Recode</button></form>`;
            }
            return html;
          }
        },
      ],
      initComplete: function () {
        const api = this.api();
        $('#filterSubmissionDate, #filterFormID, #filterAge, #filterGender').select2({ width: '100%' });

        api.columns().every(function () {
          const col   = this;
          const idx   = col.index();
          const title = col.header().textContent;
          if (['Action', 'H1', 'H2'].includes(title)) return;
          $('#columnToggles').append(`
            <div class="form-check form-check-inline">
              <input type="checkbox" class="form-check-input me-1" data-col="${idx}" ${col.visible() ? 'checked' : ''}>
              <label class="form-check-label me-3">${title}</label>
            </div>`);
        });

        $('#columnToggles input[type=checkbox]').on('change', function () {
          api.column($(this).data('col')).visible($(this).is(':checked'));
        });

        const filters = [
          { idx: 3, sel: '#filterSubmissionDate' },
          { idx: 2, sel: '#filterFormID' },
          { idx: 6, sel: '#filterAge' },
          { idx: 7, sel: '#filterGender' },
        ];
        filters.forEach(f => {
          const col = api.column(f.idx);
          const $s  = $(f.sel);
          $s.empty();
          col.data().unique().sort().each(d => { if (d) $s.append(`<option value="${d}">${d}</option>`); });
          $s.on('change', function () {
            const val = $(this).val();
            col.search(val && val.length ? `^(${val.join('|')})$` : '', true, false).draw();
          });
        });
      },
    });

    return historyTableInstance;
  }

  // ── bootstrap ─────────────────────────────────────────────────────────────
  $(document).ready(async function () {
    try {
      const _savedProject = localStorage.getItem(_PROJECT_SELECT_KEY) || '';
      const _statsQs = _savedProject ? '?project_id=' + encodeURIComponent(_savedProject) : '';
      const [statsData, allocData, availData, histData, projData] = await Promise.all([
        apiFetch('/api/v1/coding/stats' + _statsQs),
        apiFetch('/api/v1/coding/allocation'),
        apiFetch('/api/v1/coding/available'),
        apiFetch('/api/v1/coding/history'),
        apiFetch('/api/v1/coding/projects'),
      ]);

      // KPI cards
      document.getElementById('kpi-random-ready').textContent = valueOrZero(statsData.random_ready);
      document.getElementById('kpi-pick-ready').textContent   = valueOrZero(statsData.pick_ready);
      document.getElementById('kpi-completed').textContent    = valueOrZero(statsData.completed);
      document.getElementById('kpi-not-codeable').textContent = valueOrZero(statsData.not_codeable);

      populateProjectSelector(projData.projects || [], projData.project_options || []);

      function bindStartBtn() {
        const btn = document.getElementById('start-btn');
        if (!btn) return;
        btn.addEventListener('click', () => {
          const pid = selectedProjectId();
          const body = pid ? { project_id: pid } : {};
          startAllocationBtn(btn, body, '<i class="fas fa-edit me-2"></i>Start Random Allocation Coding');
        });
      }

      function applyStats(alloc, stats) {
        document.getElementById('kpi-random-ready').textContent = valueOrZero(stats.random_ready);
        document.getElementById('kpi-pick-ready').textContent   = valueOrZero(stats.pick_ready);
        document.getElementById('kpi-completed').textContent    = valueOrZero(stats.completed);
        document.getElementById('kpi-not-codeable').textContent = valueOrZero(stats.not_codeable);
        renderActionButtons(alloc, stats.random_ready,
                            modeLabel(stats.has_random_mode, stats.has_pick_mode));
        bindStartBtn();
      }

      applyStats(allocData.allocation, statsData);
      applyProjectFilterToEligibility();

      function applyProjectFilterToHistory() {
        if (!historyTableInstance) return;
        const pid = selectedProjectId();
        historyTableInstance.column(1).search(pid || '', true, false).draw();
      }

      function applyProjectFilterToEligibility() {
        const pid = selectedProjectId();
        document.querySelectorAll('.eligibility-row').forEach(row => {
          row.style.display = (!pid || row.dataset.project === pid) ? '' : 'none';
        });
      }

      function isDemoProjectSelected() {
        const pid = selectedProjectId();
        return !!pid && DEMO_PROJECTS.includes(pid);
      }

      function syncDemoTrainingBanner() {
        const banner = document.getElementById('demo-training-banner');
        if (!banner) return;
        banner.style.display = isDemoProjectSelected() ? '' : 'none';
      }

      function selectFirstDemoProject() {
        if (!DEMO_PROJECTS.length) return null;
        const sel = document.getElementById('project-select-top');
        if (!sel) return DEMO_PROJECTS[0];
        sel.value = DEMO_PROJECTS[0];
        localStorage.setItem(_PROJECT_SELECT_KEY, sel.value);
        updateSelectedProjectName();
        syncDemoTrainingBanner();
        applyProjectFilterToHistory();
        applyProjectFilterToEligibility();
        applyProjectFilterToPick(!!allocData.allocation);
        return sel.value;
      }

      let _codingErrorModal = null;
      function showCodingError(msg) {
        document.getElementById('coding-error-modal-body').textContent = msg;
        if (!_codingErrorModal) _codingErrorModal = new bootstrap.Modal(document.getElementById('coding-error-modal'));
        _codingErrorModal.show();
      }

      function startAllocationBtn(btn, body, label) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Starting…';
        fetch('/api/v1/coding/allocation', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
          body: JSON.stringify(body),
        })
        .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
        .then(({ ok, data }) => {
          if (!ok) { showCodingError(data.error || 'Allocation failed.'); btn.disabled = false; btn.innerHTML = label; return; }
          window.location.href = '/coding/resume';
        })
        .catch(() => { showCodingError('Network error. Please try again.'); btn.disabled = false; btn.innerHTML = label; });
      }

      const demoCodingShortcutBtn = document.getElementById('demo-coding-shortcut-btn');
      if (demoCodingShortcutBtn) {
        demoCodingShortcutBtn.addEventListener('click', async () => {
          const demoProjectId = selectFirstDemoProject();
          if (!demoProjectId) {
            showCodingError('No demo project is configured.');
            return;
          }

          try {
            const fresh = await apiFetch('/api/v1/coding/stats?project_id=' + encodeURIComponent(demoProjectId));
            applyStats(allocData.allocation, fresh);
          } catch {}

          const startBtn = document.getElementById('start-btn');
          if (!startBtn || startBtn.disabled) {
            showCodingError('No forms are currently available for demo coding.');
            return;
          }

          startAllocationBtn(
            startBtn,
            { project_id: demoProjectId },
            '<i class="fas fa-edit me-2"></i>Start Random Allocation Coding'
          );
        });
      }

      const projectSelectTop = document.getElementById('project-select-top');
      if (projectSelectTop) {
        projectSelectTop.addEventListener('change', async () => {
          localStorage.setItem(_PROJECT_SELECT_KEY, projectSelectTop.value);
          updateSelectedProjectName();
          syncDemoTrainingBanner();
          applyProjectFilterToHistory();
          applyProjectFilterToEligibility();
          applyProjectFilterToPick(!!allocData.allocation);
          const pid = selectedProjectId();
          const qs = pid ? '?project_id=' + encodeURIComponent(pid) : '';
          try {
            const fresh = await apiFetch('/api/v1/coding/stats' + qs);
            applyStats(allocData.allocation, fresh);
          } catch {}
        });
      }

      syncDemoTrainingBanner();

      ALL_PICK_FORMS = availData.forms || [];
      applyProjectFilterToPick(!!allocData.allocation);

      const history = (histData.history || []).map(r => ({ ...r, _priority: 1 }));
      if (allocData.allocation) {
        const a = allocData.allocation;
        history.unshift({
          _priority: 0,
          project_id: a.project_id,
          site_id: a.site_id,
          va_sid: a.va_sid,
          va_form_id: a.va_form_id,
          va_uniqueid_masked: a.va_uniqueid_masked,
          va_deceased_age: a.va_deceased_age,
          va_deceased_gender: a.va_deceased_gender,
          va_submission_date: a.va_submission_date,
          va_coding_date: null,
          va_code_status: '__pending__',
          recodeable: false,
        });
      }
      initHistoryTable(history);
      applyProjectFilterToHistory();

    } catch (err) {
      console.error('Dashboard load error:', err);
      const errorBanner = document.getElementById('dashboard-load-error');
      if (errorBanner) {
        errorBanner.style.display = '';
      }
    }
  });
})();
