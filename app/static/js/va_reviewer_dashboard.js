(function () {
  'use strict';

  const rawDataEl = document.getElementById('table-data');
  const contextEl = document.getElementById('va-context');
  const gridEl = document.getElementById('reviewer-grid');

  if (!rawDataEl || !contextEl || !gridEl || !window.agGrid) {
    return;
  }

  const rows = JSON.parse(rawDataEl.textContent || '[]');
  const context = JSON.parse(contextEl.textContent || '{}');
  const activeAllocationSid = context.activeAllocationSid || '';
  let gridApi = null;

  const filterDefs = [
    { id: 'project', field: 'project_id', elementId: 'reviewer-filter-project' },
    { id: 'site', field: 'site_id', elementId: 'reviewer-filter-site' },
    { id: 'codedDate', field: 'va_coded_at', elementId: 'reviewer-filter-coded-date' },
    { id: 'language', field: 'va_narration_language', elementId: 'reviewer-filter-language' },
    { id: 'submissionDate', field: 'va_submission_date', elementId: 'reviewer-filter-submission-date' },
    { id: 'form', field: 'va_form_id', elementId: 'reviewer-filter-form' },
    { id: 'status', field: 'va_review_status', elementId: 'reviewer-filter-status' },
    { id: 'gender', field: 'va_deceased_gender', elementId: 'reviewer-filter-gender' },
  ];
  const filterState = Object.fromEntries(filterDefs.map(def => [def.id, new Set()]));
  const tomSelects = {};
  let isRefreshingFilterOptions = false;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function asText(value) {
    if (value == null || value === '') {
      return '';
    }
    return String(value);
  }

  function formatBlank(value) {
    const text = asText(value);
    return text || '-';
  }

  function statusBadge(status) {
    if (status === 'Reviewed') {
      return '<span class="badge bg-success">Reviewed</span>';
    }
    if (status === 'In Progress') {
      return '<span class="badge bg-warning text-dark">In Progress</span>';
    }
    return '<span class="badge bg-secondary">Not Reviewed</span>';
  }

  function filterRow(row) {
    const search = asText(document.getElementById('reviewer-search-input').value)
      .trim()
      .toLowerCase();
    if (search) {
      const haystack = [
        row.va_uniqueid_masked,
        row.va_sid,
        row.va_data_collector,
        row.va_form_id,
        row.project_id,
        row.site_id,
        row.va_narration_language,
      ].map(asText).join(' ').toLowerCase();
      if (!haystack.includes(search)) {
        return false;
      }
    }

    return filterDefs.every(def => {
      const selected = filterState[def.id];
      if (!selected || selected.size === 0) {
        return true;
      }
      return selected.has(asText(row[def.field]));
    });
  }

  function applyFilters() {
    if (!gridApi) {
      return;
    }
    gridApi.setGridOption('rowData', rows.filter(filterRow));
    gridApi.paginationGoToFirstPage();
  }

  function rowMatchesFilters(row, ignoredFilterId) {
    return filterDefs.every(def => {
      if (def.id === ignoredFilterId) {
        return true;
      }
      const selected = filterState[def.id];
      if (!selected || selected.size === 0) {
        return true;
      }
      return selected.has(asText(row[def.field]));
    });
  }

  function optionRowsForFilter(def) {
    if (def.id === 'project') {
      return rows;
    }
    if (def.id === 'site') {
      return rows.filter(row => rowMatchesFilters(row, 'site'));
    }
    if (def.id === 'form') {
      return rows.filter(row => rowMatchesFilters(row, 'form'));
    }
    return rows.filter(row => rowMatchesFilters(row, def.id));
  }

  function uniqueValues(field, sourceRows) {
    return Array.from(
      new Set(sourceRows.map(row => asText(row[field])).filter(Boolean)),
    ).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }

  function setFilterOptions(def, values) {
    const el = document.getElementById(def.elementId);
    if (!el) {
      return;
    }
    const available = new Set(values);
    const nextSelected = Array.from(filterState[def.id]).filter(value => available.has(value));
    filterState[def.id] = new Set(nextSelected);

    if (tomSelects[def.id]) {
      tomSelects[def.id].clear(true);
      tomSelects[def.id].clearOptions();
      values.forEach(value => {
        tomSelects[def.id].addOption({ value, text: value });
      });
      tomSelects[def.id].setValue(nextSelected, true);
      tomSelects[def.id].refreshOptions(false);
      return;
    }

    el.innerHTML = '';
    values.forEach(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      option.selected = filterState[def.id].has(value);
      el.appendChild(option);
    });
  }

  function refreshFilterOptions() {
    isRefreshingFilterOptions = true;
    filterDefs.forEach(def => {
      setFilterOptions(def, uniqueValues(def.field, optionRowsForFilter(def)));
    });
    isRefreshingFilterOptions = false;
  }

  function initFilter(def) {
    const el = document.getElementById(def.elementId);
    if (!el) {
      return;
    }
    setFilterOptions(def, uniqueValues(def.field, rows));

    if (window.TomSelect) {
      tomSelects[def.id] = new TomSelect(el, {
        plugins: ['remove_button'],
        maxOptions: 5000,
        placeholder: 'All',
      });
    }

    el.addEventListener('change', () => {
      if (isRefreshingFilterOptions) {
        return;
      }
      filterState[def.id] = new Set(Array.from(el.selectedOptions).map(opt => opt.value));
      refreshFilterOptions();
      applyFilters();
    });
  }

  function clearFilters() {
    document.getElementById('reviewer-search-input').value = '';
    filterDefs.forEach(def => {
      filterState[def.id].clear();
      if (tomSelects[def.id]) {
        tomSelects[def.id].clear(true);
      } else {
        const el = document.getElementById(def.elementId);
        if (el) {
          Array.from(el.options).forEach(option => {
            option.selected = false;
          });
        }
      }
    });
    refreshFilterOptions();
    applyFilters();
  }

  class StatusRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      this.eGui.innerHTML = statusBadge(params.value);
    }
    getGui() {
      return this.eGui;
    }
  }

  class AgeGenderRenderer {
    init(params) {
      this.eGui = document.createElement('span');
      const row = params.data || {};
      this.eGui.textContent = `${formatBlank(row.va_deceased_age)} / ${formatBlank(row.va_deceased_gender)}`;
    }
    getGui() {
      return this.eGui;
    }
  }

  class ActionsRenderer {
    init(params) {
      this.eGui = document.createElement('div');
      this.eGui.className = 'd-flex align-items-center gap-1';
      const row = params.data || {};
      const sid = encodeURIComponent(row.va_sid || '');
      if (!sid) {
        this.eGui.textContent = '-';
        return;
      }

      const viewButton = `<a href="/reviewing/view/${sid}" class="btn btn-sm btn-outline-primary py-0 px-2">View</a>`;
      if (row.va_review_status === 'Reviewed') {
        this.eGui.innerHTML = viewButton;
        return;
      }

      if (activeAllocationSid && activeAllocationSid === row.va_sid) {
        this.eGui.innerHTML = `${viewButton}<a href="/reviewing/resume" class="btn btn-sm btn-warning py-0 px-2">Continue QA</a>`;
        return;
      }

      if (activeAllocationSid || row.va_review_status === 'In Progress') {
        this.eGui.innerHTML = `${viewButton}<span class="text-muted small">Unavailable</span>`;
        return;
      }

      this.eGui.innerHTML = `
        ${viewButton}
        <a href="/reviewing/start/${sid}"
           class="btn btn-sm btn-primary py-0 px-2"
           onclick="return confirm('Are you sure you want to initiate QA for this form?');">Initiate QA</a>`;
    }
    getGui() {
      return this.eGui;
    }
  }

  function buildColumnDefs() {
    return [
      { field: 'project_id', headerName: 'Project', width: 95 },
      { field: 'site_id', headerName: 'Project Site', width: 115 },
      { field: 'va_coded_at', headerName: 'Date Coded', width: 115 },
      { field: 'va_narration_language', headerName: 'Language', width: 115 },
      { field: 'va_uniqueid_masked', headerName: 'VA Platform ID', width: 150 },
      { field: '_age_gender', headerName: 'Age / Gender', width: 115, cellRenderer: AgeGenderRenderer },
      { field: 'va_review_status', headerName: 'Review Status', width: 135, cellRenderer: StatusRenderer },
      { field: 'va_reviewed_at', headerName: 'Reviewed At', width: 115 },
      { field: '_actions', headerName: 'Reviewer QA', width: 150, cellRenderer: ActionsRenderer, sortable: false },
    ];
  }

  function initGrid() {
    gridApi = agGrid.createGrid(gridEl, {
      theme: agGrid.themeAlpine,
      rowData: rows,
      columnDefs: buildColumnDefs(),
      defaultColDef: {
        sortable: true,
        resizable: true,
        filter: false,
      },
      pagination: true,
      paginationPageSize: 25,
      paginationPageSizeSelector: [10, 25, 50, 100],
      getRowId: params => params.data && params.data.va_sid,
    });
  }

  function init() {
    filterDefs.forEach(initFilter);
    refreshFilterOptions();
    initGrid();

    document.getElementById('reviewer-search-input').addEventListener('input', applyFilters);
    document.getElementById('reviewer-clear-filters-btn').addEventListener('click', clearFilters);
  }

  init();
}());
