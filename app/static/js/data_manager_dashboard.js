(function () {
  'use strict';

  /* ── Constants ── */
  const CONFIG = window.DM_DASHBOARD_CONFIG || {};
  const CSRF = CONFIG.csrfToken || '';
  const LS_KEY = 'digitva.data_manager.table_state.v2';
  const CHARTJS_SRC = CONFIG.chartJsSrc || '';
  const TOM_SELECT_SRC = CONFIG.tomSelectSrc || '';

  /* ── Column definitions (toggleable metadata) ── */
  const TOGGLEABLE_COLS = [
    { field: 'project_id',        label: 'Project' },
    { field: 'va_data_collector', label: 'Data Collector' },
    { field: 'attachment_count',  label: 'Attachments' },
    { field: 'analytics_age_band',label: 'Age Group' },
    { field: 'va_deceased_gender',label: 'Gender' },
    { field: 'odk_sync_status',   label: 'ODK Sync' },
    { field: 'va_dmreview_createdat', label: 'Flagged At' },
    { field: 'va_consent',           label: 'Consent' },
  ];
  /* fields hidden by default */
  const DEFAULT_HIDDEN = new Set([
    'project_id', 'va_data_collector', 'attachment_count',
    'analytics_age_band', 'va_deceased_gender', 'odk_sync_status',
    'va_dmreview_createdat', 'va_consent'
  ]);

  /* ── Filter state ── */
  let currentFilters = {
    search: '',
    project: '',
    site: '',
    date_from: '',
    date_to: '',
    odk_status: '',
    smartva: '',
    age_group: '',
    gender: '',
    odk_sync: '',
    workflow: '',
  };

  /* ── Column visibility state ── */
  let colVisibility = {};
  TOGGLEABLE_COLS.forEach(c => {
    colVisibility[c.field] = !DEFAULT_HIDDEN.has(c.field);
  });

  /* ── Load persisted state ── */
  function loadPersistedState() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved.filters) Object.assign(currentFilters, saved.filters);
      if (saved.colVisibility) Object.assign(colVisibility, saved.colVisibility);
    } catch (_) { /* ignore */ }
  }

  function saveState() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        filters: currentFilters,
        colVisibility,
      }));
    } catch (_) { /* ignore */ }
  }

  /* ── Filter-options cache ── */
  let filterOptions = { projects: [], sites: [], genders: [] };
  let filterOptionsPromise = null;

  /* ── Tom Select instances ── */
  let tsProjectFilter = null;
  let tsSiteFilter = null;
  let tsSyncProject = null;
  let tsSyncSite = null;
  let tomSelectLoader = null;

  /* ── Chart instances ── */
  let chartProjectSite = null;
  let chartAgeBand = null;
  let chartSex = null;
  let chartWorkflowDist = null;
  let chartJsLoader = null;

  /* ── Workflow state display config ── */
  const WORKFLOW_STATE_CONFIG = {
    ready_for_coding:             { label: 'Ready for Coding',         color: '#3b82f6' },
    smartva_pending:              { label: 'SmartVA Queue',            color: '#0891b2' },
    screening_pending:            { label: 'Screening Pending',        color: '#64748b' },
    coding_in_progress:           { label: 'Coding In Progress',       color: '#f59e0b' },
    coder_step1_saved:            { label: 'Step 1 Saved',             color: '#fbbf24' },
    not_codeable_by_coder:        { label: 'Not Codeable (Coder)',     color: '#d97706' },
    coder_finalized:              { label: 'Coder Finalized',          color: '#10b981' },
    reviewer_eligible:            { label: 'Coded — Reviewer Eligible', color: '#059669' },
    reviewer_coding_in_progress:  { label: 'Reviewer Coding',         color: '#047857' },
    reviewer_finalized:           { label: 'Reviewer Finalized',       color: '#065f46' },
    finalized_upstream_changed:   { label: 'Upstream Changed',         color: '#9333ea' },
    not_codeable_by_data_manager: { label: 'Not Codeable — DM',        color: '#ea580c' },
    consent_refused:              { label: 'Consent Refused',          color: '#dc2626' },
  };

  /* ── AG Grid instance ── */
  let gridApi = null;

  /* ── Poll handles ── */
  let syncRunsPollInterval = null;

  /* ════════════════════════════════════════════════════
     UTILITY
     ════════════════════════════════════════════════════ */
  function toast(msg, type) {
    if (window.showAppToast) window.showAppToast(msg, type || 'info');
  }

  function jsonFetch(url, opts) {
    const defaults = {
      headers: {
        'Accept': 'application/json',
        'X-CSRFToken': CSRF,
      }
    };
    return fetch(url, Object.assign({}, defaults, opts)).then(r => {
      if (!r.ok) return r.json().catch(() => ({})).then(body => {
        throw new Error(body.error || body.message || `HTTP ${r.status}`);
      });
      return r.json();
    });
  }

  function loadChartJs() {
    if (window.Chart) {
      return Promise.resolve(window.Chart);
    }
    if (chartJsLoader) {
      return chartJsLoader;
    }
    chartJsLoader = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = CHARTJS_SRC;
      script.async = true;
      script.onload = () => resolve(window.Chart);
      script.onerror = () => reject(new Error('Failed to load Chart.js'));
      document.head.appendChild(script);
    });
    return chartJsLoader;
  }

  function loadTomSelect() {
    if (window.TomSelect) {
      return Promise.resolve(window.TomSelect);
    }
    if (tomSelectLoader) {
      return tomSelectLoader;
    }
    tomSelectLoader = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = TOM_SELECT_SRC;
      script.async = true;
      script.onload = () => resolve(window.TomSelect);
      script.onerror = () => reject(new Error('Failed to load Tom Select'));
      document.head.appendChild(script);
    });
    return tomSelectLoader;
  }

  /* ════════════════════════════════════════════════════
     AG GRID CELL RENDERERS
     ════════════════════════════════════════════════════ */
  class SmartVARenderer {
    init(params) {
      this.eGui = document.createElement('span');
      this.eGui.innerHTML = params.value
        ? '<span class="badge bg-success">Available</span>'
        : '<span class="badge bg-secondary">Missing</span>';
    }
    getGui() { return this.eGui; }
  }

  class OdkStatusRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const v = params.value;
      const row = params.data || {};
      if (v === 'hasIssues') {
        let tip = '';
        if (Array.isArray(row.va_odk_reviewcomments) && row.va_odk_reviewcomments.length) {
          tip = row.va_odk_reviewcomments.map(c => c.body || '').filter(Boolean).join(' | ');
        }
        const esc = tip.replace(/"/g, '&quot;');
        this.eGui.innerHTML = `<span class="badge bg-warning text-dark dm-has-issues-badge"${esc ? ` title="${esc}"` : ''}>Has Issues</span>`;
      } else if (v === 'approved') {
        this.eGui.innerHTML = '<span class="badge bg-info text-dark">Approved</span>';
      } else {
        this.eGui.innerHTML = '<span class="badge bg-light text-dark border">No review state</span>';
      }
    }
    getGui() { return this.eGui; }
  }

  class OdkSyncRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      this.eGui.innerHTML = params.value === 'missing_in_odk'
        ? '<span class="badge bg-danger">Missing In ODK</span>'
        : '<span class="badge bg-success">In Sync</span>';
    }
    getGui() { return this.eGui; }
  }

  class WorkflowRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const state = params.value;
      const label = (params.data && params.data.workflow_label) || state || '';
      if (state === 'finalized_upstream_changed') {
        this.eGui.innerHTML = `<span class="badge" style="background:#9333ea;">${label}</span>`;
        return;
      }
      let cls = 'bg-light text-dark border';
      if (state === 'not_codeable_by_data_manager') cls = 'bg-danger';
      else if (state === 'not_codeable_by_coder') cls = 'bg-warning text-dark';
      else if (state === 'ready_for_coding') cls = 'bg-primary';
      else if (state === 'screening_pending') cls = 'bg-secondary';
      this.eGui.innerHTML = `<span class="badge ${cls}">${label}</span>`;
    }
    getGui() { return this.eGui; }
  }

  class AttachmentsRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const v = parseInt(params.value, 10) || 0;
      this.eGui.className = 'dm-attachment-count';
      this.eGui.innerHTML = `<i class="fa-regular fa-paperclip text-muted"></i>${v}`;
    }
    getGui() { return this.eGui; }
  }

  class ActionsRenderer {
    init(params) {
      this.eGui = document.createElement('div');
      this.eGui.className = 'dm-action-cell';
      const sid = params.data ? params.data.va_sid : '';
      const state = params.data ? params.data.workflow_state : '';
      if (!sid) {
        this.eGui.innerHTML = '—';
        return;
      }
      if (state === 'finalized_upstream_changed') {
        this.eGui.innerHTML = `
          <a href="/data-management/view/${sid}" class="btn btn-sm btn-outline-primary py-0 px-1">View</a>
          <button class="btn btn-sm btn-success py-0 px-1 dm-accept-upstream-btn" data-sid="${sid}" title="Accept upstream change — clear COD, recode">Accept</button>
          <button class="btn btn-sm btn-outline-danger py-0 px-1 dm-reject-upstream-btn" data-sid="${sid}" title="Reject upstream change — keep existing COD">Reject</button>`;
      } else {
        this.eGui.innerHTML = `
          <a href="/data-management/view/${sid}" class="btn btn-sm btn-outline-primary py-0 px-1">View</a>
          <a href="/data-management/submissions/${sid}/odk-edit" target="_blank" class="btn btn-sm btn-outline-secondary py-0 px-1">Edit</a>
          <button class="btn btn-sm btn-outline-secondary py-0 px-1 dm-refresh-btn" data-sid="${sid}">Refresh</button>`;
      }
    }
    getGui() { return this.eGui; }
  }

  class DateRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const v = params.value;
      this.eGui.textContent = v ? String(v).slice(0, 10) : '—';
    }
    getGui() { return this.eGui; }
  }

  class DateTimeRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const v = params.value;
      this.eGui.textContent = v ? String(v).slice(0, 16).replace('T', ' ') : '—';
    }
    getGui() { return this.eGui; }
  }

  /* ════════════════════════════════════════════════════
     AG GRID SETUP
     ════════════════════════════════════════════════════ */
  function buildColumnDefs() {
    return [
      { field: 'project_id', headerName: 'Project', width: 90, hide: colVisibility.project_id === false },
      { field: 'site_id', headerName: 'Site', width: 90 },
      { field: 'va_submission_date', headerName: 'Submitted', width: 105, cellRenderer: DateRenderer },
      { field: 'va_uniqueid_masked', headerName: 'VA Form ID', width: 130 },
      { field: 'va_data_collector', headerName: 'Data Collector', width: 130, hide: colVisibility.va_data_collector === false },
      { field: 'attachment_count', headerName: 'Attachments', width: 100, cellRenderer: AttachmentsRenderer, hide: colVisibility.attachment_count === false },
      { field: 'has_smartva', headerName: 'SmartVA', width: 95, cellRenderer: SmartVARenderer },
      { field: 'analytics_age_band', headerName: 'Age Group', width: 100, hide: colVisibility.analytics_age_band === false },
      { field: 'va_deceased_gender', headerName: 'Gender', width: 85, hide: colVisibility.va_deceased_gender === false },
      { field: 'va_odk_reviewstate', headerName: 'ODK Status', width: 120, cellRenderer: OdkStatusRenderer },
      { field: 'odk_sync_status', headerName: 'ODK Sync', width: 110, cellRenderer: OdkSyncRenderer, hide: colVisibility.odk_sync_status === false },
      { field: 'workflow_state', headerName: 'Workflow State', width: 150, cellRenderer: WorkflowRenderer },
      { field: 'va_dmreview_createdat', headerName: 'Flagged At', width: 115, cellRenderer: DateTimeRenderer, hide: colVisibility.va_dmreview_createdat === false },
      { field: 'va_consent', headerName: 'Consent', width: 120, hide: colVisibility.va_consent === false },
      { field: '_actions', headerName: 'Actions', width: 215, cellRenderer: ActionsRenderer, sortable: false },
    ];
  }

  function initTable() {
    const container = document.getElementById('dm-table');
    const gridOptions = {
      theme: agGrid.themeAlpine,
      columnDefs: buildColumnDefs(),
      defaultColDef: {
        sortable: true,
        resizable: true,
        filter: false,
      },
      pagination: true,
      paginationPageSize: 25,
      paginationPageSizeSelector: [10, 25, 50, 100],
      rowModelType: 'infinite',
      cacheBlockSize: 25,
      infiniteInitialRowCount: 1,
      maxBlocksInCache: 10,
      onGridReady: (params) => {
        const ds = createDataSource();
        params.api.setGridOption('datasource', ds);
      },
      onBodyScrollEnd: () => {
        // Lazy-init tooltips for visible rows
        document.querySelectorAll('.dm-has-issues-badge[title]').forEach(badge => {
          if (!badge._bsTooltip) {
            badge._bsTooltip = new bootstrap.Tooltip(badge, { placement: 'top', trigger: 'hover' });
          }
        });
      },
    };

    gridApi = agGrid.createGrid(container, gridOptions);

    /* row-level refresh button delegation */
    container.addEventListener('click', e => {
      const btn = e.target.closest('.dm-refresh-btn');
      if (!btn) return;
      const sid = btn.dataset.sid;
      if (!sid) return;
      btn.disabled = true;
      btn.textContent = '…';
      jsonFetch(`/api/v1/data-management/submissions/${sid}/sync`, { method: 'POST' })
        .then(() => {
          toast('Submission refreshed', 'success');
          gridApi.refreshInfiniteCache();
        })
        .catch(err => toast('Refresh failed: ' + err.message, 'danger'))
        .finally(() => {
          btn.disabled = false;
          btn.textContent = 'Refresh';
        });
    });

    /* Accept upstream ODK change */
    container.addEventListener('click', e => {
      const btn = e.target.closest('.dm-accept-upstream-btn');
      if (!btn) return;
      const sid = btn.dataset.sid;
      if (!sid) return;
      if (!confirm('Accept upstream change?\n\nThis will clear the existing cause-of-death decision and return the submission to the coding queue.')) return;
      btn.disabled = true;
      btn.textContent = '…';
      jsonFetch(`/api/v1/data-management/submissions/${sid}/accept-upstream-change`, { method: 'POST' })
        .then(() => {
          toast('Upstream change accepted — submission reset to ready for coding.', 'success');
          loadKPIs();
          gridApi.refreshInfiniteCache();
        })
        .catch(err => toast('Accept failed: ' + err.message, 'danger'))
        .finally(() => {
          btn.disabled = false;
          btn.textContent = 'Accept';
        });
    });

    /* Reject upstream ODK change */
    container.addEventListener('click', e => {
      const btn = e.target.closest('.dm-reject-upstream-btn');
      if (!btn) return;
      const sid = btn.dataset.sid;
      if (!sid) return;
      if (!confirm('Reject upstream change?\n\nThe existing cause-of-death decision will be kept and the submission restored to Coder Finalized.')) return;
      btn.disabled = true;
      btn.textContent = '…';
      jsonFetch(`/api/v1/data-management/submissions/${sid}/reject-upstream-change`, { method: 'POST' })
        .then(() => {
          toast('Upstream change rejected — submission restored to coder finalized.', 'success');
          loadKPIs();
          gridApi.refreshInfiniteCache();
        })
        .catch(err => toast('Reject failed: ' + err.message, 'danger'))
        .finally(() => {
          btn.disabled = false;
          btn.textContent = 'Reject';
        });
    });
  }

  function createDataSource() {
    return {
      getRows: (params) => {
        const sp = document.getElementById('dm-table-spinner');
        if (sp) sp.style.display = 'flex';

        const page = Math.floor(params.startRow / 25) + 1;
        const size = params.endRow - params.startRow;

        const url = new URL('/api/v1/data-management/submissions', window.location.origin);
        url.searchParams.set('page', page);
        url.searchParams.set('size', size);

        // Add filters
        Object.entries(currentFilters).forEach(([k, v]) => {
          if (v !== '' && v != null) url.searchParams.set(k, v);
        });

        // Add sort
        if (params.sortModel && params.sortModel.length) {
          const s = params.sortModel[0];
          url.searchParams.set('sort[0][field]', s.colId);
          url.searchParams.set('sort[0][dir]', s.sort);
        }

        fetch(url.toString(), {
          headers: { 'Accept': 'application/json', 'X-CSRFToken': CSRF }
        })
          .then(r => r.json())
          .then(data => {
            if (sp) sp.style.display = 'none';
            const rows = data.data || [];
            const lastRow = Number.isInteger(data.total) ? data.total : undefined;
            params.successCallback(rows, lastRow);
          })
          .catch(err => {
            if (sp) sp.style.display = 'none';
            console.error('AG Grid data load error:', err);
            params.failCallback();
          });
      }
    };
  }

  /* ════════════════════════════════════════════════════
     COLUMN VISIBILITY UI
     ════════════════════════════════════════════════════ */
  function renderColVisibilityPanel() {
    const panel = document.getElementById('dm-col-visibility-panel');
    if (!panel) return;
    panel.innerHTML = '';
    TOGGLEABLE_COLS.forEach(col => {
      const visible = colVisibility[col.field] !== false;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `btn btn-sm dm-col-toggle-btn ${visible ? 'btn-primary' : 'btn-outline-secondary'}`;
      btn.textContent = col.label;
      btn.dataset.field = col.field;
      btn.addEventListener('click', () => {
        colVisibility[col.field] = !colVisibility[col.field];
        if (gridApi) {
          gridApi.setColumnsVisible([col.field], colVisibility[col.field]);
        }
        saveState();
        renderColVisibilityPanel();
      });
      panel.appendChild(btn);
    });
  }

  /* ════════════════════════════════════════════════════
     FILTER PILLS
     ════════════════════════════════════════════════════ */
  const FILTER_LABELS = {
    search: 'Search',
    project: 'Project',
    site: 'Site',
    date_from: 'From',
    date_to: 'To',
    odk_status: 'ODK Status',
    smartva: 'SmartVA',
    age_group: 'Age Group',
    gender: 'Gender',
    odk_sync: 'ODK Sync',
    workflow: 'Workflow',
  };

  function renderFilterPills() {
    const container = document.getElementById('dm-filter-pills-container');
    const pills = document.getElementById('dm-filter-pills');
    if (!container || !pills) return;
    pills.innerHTML = '';
    let hasAny = false;
    Object.entries(currentFilters).forEach(([key, val]) => {
      if (!val) return;
      hasAny = true;
      const pill = document.createElement('span');
      pill.className = 'dm-filter-pill';
      pill.innerHTML = `<strong>${FILTER_LABELS[key] || key}:</strong>&nbsp;${val}
        <button type="button" aria-label="Remove filter" data-filter-key="${key}">&#x2715;</button>`;
      pills.appendChild(pill);
    });
    container.style.display = hasAny ? 'block' : 'none';

    pills.querySelectorAll('button[data-filter-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.filterKey;
        currentFilters[key] = '';
        syncInputsFromState();
        applyFilters();
      });
    });
  }

  /* ════════════════════════════════════════════════════
     SYNC INPUTS → STATE → TABLE
     ════════════════════════════════════════════════════ */
  function readInputsToFilters() {
    currentFilters.search    = document.getElementById('dm-search-input').value.trim();
    currentFilters.project   = tsProjectFilter ? tsProjectFilter.getValue().join(',') : '';
    currentFilters.site      = tsSiteFilter    ? tsSiteFilter.getValue().join(',')    : '';
    currentFilters.date_from = document.getElementById('dm-date-from').value;
    currentFilters.date_to   = document.getElementById('dm-date-to').value;
    currentFilters.odk_status= document.getElementById('dm-odk-status-filter').value;
    currentFilters.smartva   = document.getElementById('dm-smartva-filter').value;
    currentFilters.age_group = document.getElementById('dm-age-group-filter').value;
    currentFilters.gender    = document.getElementById('dm-gender-filter').value;
    currentFilters.odk_sync  = document.getElementById('dm-odk-sync-filter').value;
    currentFilters.workflow  = document.getElementById('dm-workflow-filter').value;
  }

  function syncInputsFromState() {
    document.getElementById('dm-search-input').value = currentFilters.search || '';
    document.getElementById('dm-date-from').value    = currentFilters.date_from || '';
    document.getElementById('dm-date-to').value      = currentFilters.date_to || '';
    document.getElementById('dm-odk-status-filter').value = currentFilters.odk_status || '';
    document.getElementById('dm-smartva-filter').value    = currentFilters.smartva || '';
    document.getElementById('dm-age-group-filter').value  = currentFilters.age_group || '';
    document.getElementById('dm-gender-filter').value     = currentFilters.gender || '';
    document.getElementById('dm-odk-sync-filter').value   = currentFilters.odk_sync || '';
    document.getElementById('dm-workflow-filter').value   = currentFilters.workflow || '';

    if (tsProjectFilter) {
      const vals = currentFilters.project ? currentFilters.project.split(',') : [];
      tsProjectFilter.clear(true);
      vals.forEach(v => tsProjectFilter.addItem(v, true));
    }
    if (tsSiteFilter) {
      const vals = currentFilters.site ? currentFilters.site.split(',') : [];
      tsSiteFilter.clear(true);
      vals.forEach(v => tsSiteFilter.addItem(v, true));
    }
  }

  function applyFilters() {
    readInputsToFilters();
    saveState();
    renderFilterPills();
    Promise.all([
      loadKPIs(),
      loadProjectSiteChart(),
      loadDemographicsCharts(),
    ]).catch(() => {});
    if (gridApi) gridApi.refreshInfiniteCache();
  }

  function clearAllFilters() {
    Object.keys(currentFilters).forEach(k => { currentFilters[k] = ''; });
    syncInputsFromState();
    saveState();
    renderFilterPills();
    Promise.all([
      loadKPIs(),
      loadProjectSiteChart(),
      loadDemographicsCharts(),
    ]).catch(() => {});
    if (gridApi) gridApi.refreshInfiniteCache();
  }

  function buildDashboardQuery() {
    const params = new URLSearchParams();
    ['project', 'site', 'date_from', 'date_to', 'odk_status', 'smartva', 'age_group', 'gender', 'odk_sync', 'workflow']
      .forEach(key => {
        const value = currentFilters[key];
        if (value) params.set(key, value);
      });
    const query = params.toString();
    return query ? `?${query}` : '';
  }

  /* ════════════════════════════════════════════════════
     FILTER OPTIONS — Tom Select init
     ════════════════════════════════════════════════════ */
  function initProjectTomSelect(opts) {
    const el = document.getElementById('dm-project-filter');
    if (!el) return;
    if (tsProjectFilter) tsProjectFilter.destroy();
    tsProjectFilter = new TomSelect(el, {
      plugins: ['remove_button'],
      maxOptions: 500,
      options: opts.map(p => ({ value: p, text: p })),
      placeholder: 'All projects…',
      onChange: () => cascadeSiteFilter(),
    });
  }

  function initSiteTomSelect(siteOpts) {
    const el = document.getElementById('dm-site-filter');
    if (!el) return;
    if (tsSiteFilter) tsSiteFilter.destroy();
    tsSiteFilter = new TomSelect(el, {
      plugins: ['remove_button'],
      maxOptions: 500,
      options: siteOpts.map(s => ({ value: s.site_id, text: s.site_id, project: s.project_id })),
      placeholder: 'All sites…',
    });
  }

  function cascadeSiteFilter() {
    if (!tsSiteFilter) return;
    const selectedProjects = tsProjectFilter ? tsProjectFilter.getValue() : [];
    const allSites = filterOptions.sites || [];
    const filtered = selectedProjects.length
      ? allSites.filter(s => selectedProjects.includes(s.project_id))
      : allSites;

    const current = tsSiteFilter.getValue();
    tsSiteFilter.clearOptions();
    filtered.forEach(s => tsSiteFilter.addOption({ value: s.site_id, text: s.site_id, project: s.project_id }));
    tsSiteFilter.refreshOptions(false);

    /* preserve selections that are still valid */
    const validSiteIds = new Set(filtered.map(s => s.site_id));
    const stillValid = current.filter(v => validSiteIds.has(v));
    tsSiteFilter.clear(true);
    stillValid.forEach(v => tsSiteFilter.addItem(v, true));
  }

  function populateGenderFilter(genders) {
    const sel = document.getElementById('dm-gender-filter');
    if (!sel) return;
    /* keep "All" option */
    while (sel.options.length > 1) sel.remove(1);
    genders.forEach(g => {
      const opt = document.createElement('option');
      opt.value = g;
      opt.textContent = g;
      sel.appendChild(opt);
    });
  }

  function loadFilterOptions() {
    if (filterOptionsPromise) {
      return filterOptionsPromise;
    }
    filterOptionsPromise = jsonFetch('/api/v1/data-management/filter-options')
      .then(data => {
        filterOptions = data;
        populateGenderFilter(data.genders || []);
        return loadTomSelect().then(() => {
          initProjectTomSelect(data.projects || []);
          initSiteTomSelect(data.sites || []);
          syncInputsFromState();
          return data;
        });
      })
      .catch(err => {
        filterOptionsPromise = null;
        toast('Failed to load filter options: ' + err.message, 'danger');
        throw err;
      });
    return filterOptionsPromise;
  }

  /* ════════════════════════════════════════════════════
     KPI
     ════════════════════════════════════════════════════ */
  function loadKPIs() {
    return jsonFetch(`/api/v1/data-management/kpi${buildDashboardQuery()}`)
      .then(d => {
        const fmt = v => (v != null && v !== '—') ? Number(v).toLocaleString() : '—';
        document.getElementById('kpi-total').textContent           = fmt(d.total_submissions);
        document.getElementById('kpi-coded').textContent           = fmt(d.coded_submissions);
        document.getElementById('kpi-pending').textContent         = fmt(d.pending_submissions);
        document.getElementById('kpi-flagged').textContent         = fmt(d.flagged_submissions);
        document.getElementById('kpi-odk-issues').textContent      = fmt(d.odk_has_issues_submissions);
        document.getElementById('kpi-smartva-missing').textContent = fmt(d.smartva_missing_submissions);
        document.getElementById('kpi-revoked').textContent         = fmt(d.revoked_submissions);
        document.getElementById('kpi-consent-refused').textContent = fmt(d.consent_refused_submissions);
        document.getElementById('kpi-smartva-pending').textContent = fmt(d.smartva_pending_submissions);
        if (typeof __dm_update_workflow_counts === 'function') {
          __dm_update_workflow_counts(d.workflow_counts || {});
        }
        return loadChartJs().then(() => {
          renderWorkflowDistChart(d.workflow_counts || {});
        });
      })
      .catch(err => toast('Failed to load KPIs: ' + err.message, 'danger'));
  }

  function renderWorkflowDistChart(counts) {
    const ctx = document.getElementById('dm-workflow-dist-chart');
    if (!ctx) return;
    const entries = Object.entries(WORKFLOW_STATE_CONFIG)
      .map(([state, cfg]) => ({ state, label: cfg.label, color: cfg.color, count: counts[state] || 0 }))
      .filter(e => e.count > 0);

    const labels = entries.map(e => `${e.label} (${e.count.toLocaleString()})`);
    const data   = entries.map(e => e.count);
    const colors = entries.map(e => e.color);

    if (chartWorkflowDist) chartWorkflowDist.destroy();
    chartWorkflowDist = new window.Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors, borderWidth: 1.5 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { font: { size: 10 }, boxWidth: 12, padding: 8 } },
          tooltip: {
            callbacks: {
              label: ctx => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                const pct = total ? ((ctx.raw / total) * 100).toFixed(1) : 0;
                return ` ${ctx.raw.toLocaleString()} (${pct}%)`;
              }
            }
          }
        },
        onClick: (event, elements) => {
          if (!elements.length) return;
          const idx = elements[0].index;
          const state = entries[idx] && entries[idx].state;
          if (!state) return;
          currentFilters.workflow = state;
          syncInputsFromState();
          applyFilters();
        },
      },
    });
  }

  /* KPI card click quick-filters */
  function kpiFilterClick(filterKey, filterValue) {
    if (filterKey === 'workflow') currentFilters.workflow = filterValue;
    else if (filterKey === 'odk_status') currentFilters.odk_status = filterValue;
    else if (filterKey === 'smartva') currentFilters.smartva = filterValue;
    syncInputsFromState();
    applyFilters();
    bootstrap.Offcanvas.getOrCreateInstance(document.getElementById('dm-filter-offcanvas')).hide();
  }

  document.getElementById('kpi-coded-card').addEventListener('click',           () => kpiFilterClick('workflow', 'coded'));
  document.getElementById('kpi-pending-card').addEventListener('click',         () => kpiFilterClick('workflow', 'pending_coding'));
  document.getElementById('kpi-smartva-pending-card').addEventListener('click', () => kpiFilterClick('workflow', 'smartva_pending'));
  document.getElementById('kpi-flagged-card').addEventListener('click',         () => kpiFilterClick('workflow', 'not_codeable_by_data_manager'));
  document.getElementById('kpi-odk-issues-card').addEventListener('click',      () => kpiFilterClick('odk_status', 'hasIssues'));
  document.getElementById('kpi-smartva-missing-card').addEventListener('click', () => kpiFilterClick('smartva', 'missing'));
  document.getElementById('kpi-revoked-card').addEventListener('click',         () => kpiFilterClick('workflow', 'finalized_upstream_changed'));
  document.getElementById('kpi-consent-refused-card').addEventListener('click', () => kpiFilterClick('workflow', 'consent_refused'));

  /* ════════════════════════════════════════════════════
     CHARTS
     ════════════════════════════════════════════════════ */
  const CHART_COLORS = [
    '#4e73df','#1cc88a','#36b9cc','#f6c23e','#e74a3b',
    '#858796','#5a5c69','#2e59d9','#17a673','#2c9faf',
  ];

  function loadProjectSiteChart() {
    return loadChartJs().then(() =>
      jsonFetch(`/api/v1/data-management/project-site-submissions${buildDashboardQuery()}`)
      .then(data => {
        const stats = data.stats || [];
        const labels = stats.map(s => `${s.site_id}`);
        const totals = stats.map(s => s.total_submissions || 0);
        const weekCounts = stats.map(s => s.this_week_submissions || 0);
        const todayCounts = stats.map(s => s.today_submissions || 0);

        const ctx = document.getElementById('dm-project-site-submissions-chart');
        if (!ctx) return;
        if (chartProjectSite) chartProjectSite.destroy();
        chartProjectSite = new window.Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [
              { label: 'Total',     data: totals,      backgroundColor: '#4e73df' },
              { label: 'This Week', data: weekCounts,  backgroundColor: '#1cc88a' },
              { label: 'Today',     data: todayCounts, backgroundColor: '#f6c23e' },
            ],
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } } },
            scales: { x: { ticks: { font: { size: 10 } } }, y: { ticks: { font: { size: 10 } } } },
          },
        });
      })
      .catch(err => toast('Project/site chart error: ' + err.message, 'warning'))
    );
  }

  function loadDemographicsCharts() {
    return loadChartJs().then(() =>
      jsonFetch(`/api/v1/analytics/demographics${buildDashboardQuery()}`)
      .then(data => {
        /* Age band chart */
        const ageBands = data.age_bands || [];
        const ageCtx = document.getElementById('dm-age-band-chart');
        if (ageCtx) {
          if (chartAgeBand) chartAgeBand.destroy();
          chartAgeBand = new window.Chart(ageCtx, {
            type: 'pie',
            data: {
              labels: ageBands.map(b => b.band),
              datasets: [{
                data: ageBands.map(b => b.count),
                backgroundColor: CHART_COLORS.slice(0, ageBands.length),
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } } },
            },
          });
        }

        /* Sex chart */
        const sex = data.sex || [];
        const sexCtx = document.getElementById('dm-sex-chart');
        if (sexCtx) {
          if (chartSex) chartSex.destroy();
          chartSex = new window.Chart(sexCtx, {
            type: 'pie',
            data: {
              labels: sex.map(s => s.sex),
              datasets: [{
                data: sex.map(s => s.count),
                backgroundColor: ['#4e73df', '#1cc88a', '#f6c23e', '#e74a3b', '#858796'].slice(0, sex.length),
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12 } } },
            },
          });
        }
      })
      .catch(err => toast('Demographics chart error: ' + err.message, 'warning'))
    );
  }

  /* ════════════════════════════════════════════════════
     SYNC RUNS
     ════════════════════════════════════════════════════ */
  function renderSyncRunRow(run) {
    const statusBadge = run.status === 'running'
      ? '<span class="badge bg-primary">Running</span>'
      : run.status === 'completed'
        ? '<span class="badge bg-success">Done</span>'
        : '<span class="badge bg-danger">Failed</span>';
    const started = run.started_at ? String(run.started_at).slice(0, 16).replace('T', ' ') : '—';
    return `<tr>
      <td title="${run.target || ''}">${(run.target || '').slice(0, 20)}</td>
      <td>${started}</td>
      <td>${statusBadge}</td>
      <td>${run.records_added ?? '—'}</td>
      <td>${run.records_updated ?? '—'}</td>
    </tr>`;
  }

  function loadSyncRuns() {
    return jsonFetch('/api/v1/data-management/sync/runs')
      .then(data => {
        const runs = data.runs || [];
        const tbody = document.getElementById('dm-sync-runs-tbody');
        if (!tbody) return runs;
        if (!runs.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="text-muted text-center small">No sync runs yet</td></tr>';
          return runs;
        }
        tbody.innerHTML = runs.map(renderSyncRunRow).join('');
        return runs;
      })
      .catch(err => {
        toast('Failed to load sync runs: ' + err.message, 'danger');
        return [];
      });
  }

  function startSyncRunsPolling() {
    if (syncRunsPollInterval) return;
    syncRunsPollInterval = setInterval(() => {
      loadSyncRuns().then(runs => {
        const anyRunning = runs.some(r => r.status === 'running');
        if (!anyRunning) {
          clearInterval(syncRunsPollInterval);
          syncRunsPollInterval = null;
        }
      });
    }, 5000);
  }

  /* ════════════════════════════════════════════════════
     SYNC MODAL — Tom Select
     ════════════════════════════════════════════════════ */
  function initSyncModalSelects() {
    const projEl = document.getElementById('dm-sync-project-select');
    const siteEl = document.getElementById('dm-sync-site-select');
    if (!projEl || !siteEl) return;

    if (tsSyncProject) tsSyncProject.destroy();
    if (tsSyncSite) tsSyncSite.destroy();

    tsSyncProject = new TomSelect(projEl, {
      plugins: ['remove_button'],
      options: (filterOptions.projects || []).map(p => ({ value: p, text: p })),
      placeholder: 'All projects…',
      onChange: () => {
        cascadeSyncSiteSelect();
        loadSyncPreview();
      },
    });

    tsSyncSite = new TomSelect(siteEl, {
      plugins: ['remove_button'],
      options: (filterOptions.sites || []).map(s => ({ value: s.site_id, text: s.site_id })),
      placeholder: 'All sites…',
      onChange: () => loadSyncPreview(),
    });
  }

  function cascadeSyncSiteSelect() {
    if (!tsSyncSite) return;
    const selected = tsSyncProject ? tsSyncProject.getValue() : [];
    const allSites = filterOptions.sites || [];
    const filtered = selected.length
      ? allSites.filter(s => selected.includes(s.project_id))
      : allSites;
    const current = tsSyncSite.getValue();
    tsSyncSite.clearOptions();
    filtered.forEach(s => tsSyncSite.addOption({ value: s.site_id, text: s.site_id }));
    tsSyncSite.refreshOptions(false);
    const valid = new Set(filtered.map(s => s.site_id));
    tsSyncSite.clear(true);
    current.filter(v => valid.has(v)).forEach(v => tsSyncSite.addItem(v, true));
  }

  function loadSyncPreview() {
    const projectIds = tsSyncProject ? tsSyncProject.getValue() : [];
    const siteIds    = tsSyncSite    ? tsSyncSite.getValue()    : [];

    const confirmBtn = document.getElementById('dm-sync-confirm-btn');
    if (confirmBtn) confirmBtn.disabled = true;

    /* reset stats */
    ['sync-stat-total','sync-stat-new','sync-stat-updated','sync-stat-missing']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '…';
      });

    const tbody = document.getElementById('dm-sync-preview-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center small text-muted">Loading preview…</td></tr>';

    jsonFetch('/api/v1/data-management/sync/preview', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': CSRF,
      },
      body: JSON.stringify({ project_ids: projectIds, site_ids: siteIds }),
    })
      .then(data => {
        const totals = data.totals || {};
        document.getElementById('sync-stat-total').textContent   = totals.forms ?? 0;
        document.getElementById('sync-stat-new').textContent     = totals.new_fetch_candidates ?? 0;
        document.getElementById('sync-stat-updated').textContent = totals.updated_candidates ?? 0;
        document.getElementById('sync-stat-missing').textContent = totals.missing_in_odk_flags ?? 0;

        const forms = data.forms || [];
        if (!forms.length) {
          if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-muted text-center small">No forms matched</td></tr>';
          return;
        }
        if (tbody) {
          tbody.innerHTML = forms.map(f => `<tr>
            <td class="small">${f.form_id || ''}</td>
            <td class="small">${f.project_id || ''}</td>
            <td class="small">${f.site_id || ''}</td>
            <td class="small">${f.local_submissions ?? '—'}</td>
            <td class="small">${f.odk_submissions ?? '—'}</td>
            <td class="small">${f.new_fetch_candidates ?? '—'}</td>
            <td class="small">${f.missing_in_odk_flags ?? '—'}</td>
            <td class="small">${f.preview_status || ''}</td>
          </tr>`).join('');
        }
        if (confirmBtn) confirmBtn.disabled = false;

        /* stash form ids for confirm */
        confirmBtn._formIds = forms.map(f => f.form_id).filter(Boolean);
      })
      .catch(err => {
        if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-danger small">${err.message}</td></tr>`;
      });
  }

  /* ════════════════════════════════════════════════════
     SYNC CONFIRM
     ════════════════════════════════════════════════════ */
  async function runSyncForForms(formIds) {
    const confirmBtn = document.getElementById('dm-sync-confirm-btn');
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Syncing…';
    }

    let succeeded = 0;
    let failed = 0;
    for (const formId of formIds) {
      try {
        await jsonFetch(`/api/v1/data-management/forms/${formId}/sync`, { method: 'POST' });
        succeeded++;
      } catch (err) {
        failed++;
        console.warn(`Sync failed for form ${formId}:`, err.message);
      }
    }

    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down me-1"></i>Sync All';
    }

    if (failed === 0) {
      toast(`Sync complete: ${succeeded} form(s) synced`, 'success');
    } else {
      toast(`Sync finished: ${succeeded} succeeded, ${failed} failed`, 'warning');
    }

    /* close modal, reload runs, start polling */
    const modal = bootstrap.Modal.getInstance(document.getElementById('dm-sync-confirm-modal'));
    if (modal) modal.hide();
    loadSyncRuns().then(runs => {
      if (runs.some(r => r.status === 'running')) startSyncRunsPolling();
    });
    if (gridApi) gridApi.refreshInfiniteCache();
  }

  /* ════════════════════════════════════════════════════
     EVENT WIRING
     ════════════════════════════════════════════════════ */
  function wireEvents() {
    /* toolbar search */
    document.getElementById('dm-apply-filters-btn').addEventListener('click', applyFilters);
    document.getElementById('dm-clear-filters-btn').addEventListener('click', clearAllFilters);
    document.getElementById('dm-search-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') applyFilters();
    });

    /* offcanvas filter buttons */
    document.getElementById('dm-offcanvas-apply-btn').addEventListener('click', () => {
      applyFilters();
      bootstrap.Offcanvas.getOrCreateInstance(document.getElementById('dm-filter-offcanvas')).hide();
    });
    document.getElementById('dm-offcanvas-clear-btn').addEventListener('click', clearAllFilters);
    document.getElementById('dm-filter-offcanvas').addEventListener('show.bs.offcanvas', () => {
      loadFilterOptions().then(() => {
        syncInputsFromState();
      }).catch(() => {});
    });

    /* refresh dashboard */
    document.getElementById('dm-refresh-dashboard-btn').addEventListener('click', () => {
      const btn = document.getElementById('dm-refresh-dashboard-btn');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Refreshing…';
      jsonFetch('/api/v1/analytics/mv/refresh', { method: 'POST' })
        .then(() => {
          toast('Dashboard refreshed', 'success');
          return Promise.all([loadKPIs(), loadProjectSiteChart(), loadDemographicsCharts()]);
        })
        .catch(err => toast('Refresh error: ' + err.message, 'danger'))
        .finally(() => {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-arrows-rotate me-1"></i>Refresh Dashboard';
          if (gridApi) gridApi.refreshInfiniteCache();
        });
    });

    /* sync modal open */
    document.getElementById('dm-open-sync-modal-btn').addEventListener('click', () => {
      const modal = new bootstrap.Modal(document.getElementById('dm-sync-confirm-modal'));
      loadFilterOptions()
        .then(() => {
          modal.show();
          initSyncModalSelects();
          loadSyncPreview();
        })
        .catch(() => {});
    });

    /* sync confirm */
    document.getElementById('dm-sync-confirm-btn').addEventListener('click', () => {
      const btn = document.getElementById('dm-sync-confirm-btn');
      const formIds = btn._formIds || [];
      if (!formIds.length) {
        toast('No forms to sync', 'warning');
        return;
      }
      runSyncForForms(formIds);
    });

    /* refresh sync runs */
    document.getElementById('dm-refresh-sync-runs-btn').addEventListener('click', () => {
      loadSyncRuns().then(runs => {
        if (runs.some(r => r.status === 'running')) startSyncRunsPolling();
      });
    });

    /* ops offcanvas: load runs on open */
    document.getElementById('dm-ops-offcanvas').addEventListener('show.bs.offcanvas', () => {
      loadSyncRuns().then(runs => {
        if (runs.some(r => r.status === 'running')) startSyncRunsPolling();
      });
    });
  }

  /* ════════════════════════════════════════════════════
     BOOTSTRAP
     ════════════════════════════════════════════════════ */
  function initKpiInfoPopovers() {
    document.querySelectorAll('.dm-kpi-info-btn').forEach(btn => {
      new bootstrap.Popover(btn, { html: false, trigger: 'hover focus', placement: 'top' });
      btn.addEventListener('click', e => e.stopPropagation());
    });
  }

  function deferNonCritical(fn) {
    window.requestAnimationFrame(() => {
      window.setTimeout(fn, 0);
    });
  }

  function init() {
    loadPersistedState();
    initTable();
    renderColVisibilityPanel();
    wireEvents();
    initKpiInfoPopovers();
    const filterOptionsTask = loadFilterOptions()
      .then(() => {
        syncInputsFromState();
        const hasFilters = Object.values(currentFilters).some(v => v !== '' && v != null);
        if (hasFilters) {
          renderFilterPills();
        }
      })
      .catch(() => {});
    const kpiTask = loadKPIs().catch(() => {});

    deferNonCritical(() => {
      Promise.allSettled([
        filterOptionsTask,
        kpiTask,
        loadProjectSiteChart(),
        loadDemographicsCharts(),
      ]);
    });

    renderFilterPills();
  }

  window.DM_DASHBOARD_API = {
    applyWorkflowFilter(state) {
      if (!state) return;
      currentFilters.workflow = state;
      syncInputsFromState();
      applyFilters();
    },
  };

  document.addEventListener('DOMContentLoaded', init);
})();
