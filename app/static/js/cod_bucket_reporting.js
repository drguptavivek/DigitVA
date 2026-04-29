(function () {
  'use strict';

  const bootstrapData = window.COD_BUCKET_REPORTING_BOOTSTRAP || { forms: [], schemes: [] };
  const forms = bootstrapData.forms || [];
  const chartJsSrc = bootstrapData.chartJsSrc || '';
  const els = {
    scheme: document.getElementById('cod-bucket-scheme'),
    project: document.getElementById('cod-bucket-project'),
    site: document.getElementById('cod-bucket-site'),
    form: document.getElementById('cod-bucket-form'),
    dateFrom: document.getElementById('cod-bucket-date-from'),
    dateTo: document.getElementById('cod-bucket-date-to'),
    apply: document.getElementById('cod-bucket-apply'),
    ageTables: document.getElementById('cod-bucket-age-tables'),
    coded: document.getElementById('cod-bucket-kpi-coded'),
    scope: document.getElementById('cod-bucket-kpi-scope'),
    selectedScheme: document.getElementById('cod-bucket-selected-scheme'),
    mainHeadingChart: document.getElementById('cod-bucket-main-heading-chart'),
    mainHeadingChartEmpty: document.getElementById('cod-bucket-main-heading-chart-empty'),
    topCausesChart: document.getElementById('cod-bucket-top-causes-chart'),
    topCausesChartEmpty: document.getElementById('cod-bucket-top-causes-chart-empty'),
    topCausesBody: document.getElementById('cod-bucket-top-causes-body'),
    ageBandChart: document.getElementById('cod-bucket-age-band-chart'),
    ageBandChartEmpty: document.getElementById('cod-bucket-age-band-chart-empty'),
    ageBandBody: document.getElementById('cod-bucket-age-band-body'),
    genderChart: document.getElementById('cod-bucket-gender-chart'),
    genderChartEmpty: document.getElementById('cod-bucket-gender-chart-empty'),
    genderBody: document.getElementById('cod-bucket-gender-body'),
    droppedModal: document.getElementById('cod-bucket-dropped-modal'),
    droppedModalScope: document.getElementById('cod-bucket-dropped-modal-scope'),
    droppedModalBody: document.getElementById('cod-bucket-dropped-modal-body'),
  };
  const ageScopeLabels = {
    __none__: 'All Ages',
    adult_over5y: 'Adult / Over 5 Years',
    child_1_59m: 'Child / 1–59 Months',
    neonate: 'Neonate',
  };
  const ageScopeOrder = ['adult_over5y', 'child_1_59m', 'neonate'];
  const droppedIcdRowsByScope = new Map();
  const chartPalette = [
    '#0d6efd',
    '#198754',
    '#fd7e14',
    '#dc3545',
    '#20c997',
    '#6f42c1',
    '#ffc107',
    '#0dcaf0',
    '#6610f2',
    '#d63384',
    '#495057',
    '#84cc16',
  ];
  let droppedModal = null;
  let mainHeadingChart = null;
  let topCausesChart = null;
  let ageBandChart = null;
  let genderChart = null;
  let chartJsPromise = null;

  function uniq(values) {
    return Array.from(new Set(values.filter(Boolean)));
  }

  function loadChartJs() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (!chartJsPromise) {
      chartJsPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = chartJsSrc;
        script.async = true;
        script.onload = () => resolve(window.Chart);
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
      });
    }
    return chartJsPromise;
  }

  function optionHtml(value, label, selected) {
    const isSelected = String(selected || '') === String(value || '') ? ' selected' : '';
    return `<option value="${String(value || '').replace(/"/g, '&quot;')}"${isSelected}>${label}</option>`;
  }

  function refreshProjectOptions() {
    const projects = uniq(forms.map(row => row.project_id)).sort();
    els.project.innerHTML = optionHtml('', 'All projects', '') + projects.map(
      projectId => optionHtml(projectId, projectId, els.project.value)
    ).join('');
  }

  function refreshSiteOptions() {
    const sites = uniq(
      forms
        .filter(row => !els.project.value || row.project_id === els.project.value)
        .map(row => row.site_id)
    ).sort();
    const current = sites.includes(els.site.value) ? els.site.value : '';
    els.site.innerHTML = optionHtml('', 'All sites', current) + sites.map(
      siteId => optionHtml(siteId, siteId, current)
    ).join('');
  }

  function refreshFormOptions() {
    const rows = forms.filter(row => {
      if (els.project.value && row.project_id !== els.project.value) return false;
      if (els.site.value && row.site_id !== els.site.value) return false;
      return true;
    });
    const current = rows.some(row => row.form_id === els.form.value) ? els.form.value : '';
    els.form.innerHTML = optionHtml('', 'All forms', current) + rows.map(
      row => optionHtml(row.form_id, `${row.form_id} — ${row.project_id}/${row.site_id}`, current)
    ).join('');
  }

  function syncSelectors() {
    refreshProjectOptions();
    refreshSiteOptions();
    refreshFormOptions();
  }

  function formatPercent(value) {
    return `${Number(value || 0).toFixed(1)}%`;
  }

  function displayLabel(value) {
    if (value === null || value === undefined) return '—';
    const text = String(value).trim();
    return text || '—';
  }

  function normalizeScopeKey(value) {
    if (value === null || value === undefined || value === '') return '__none__';
    return String(value);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatCountPercent(count, total) {
    const pct = total ? (count / total) * 100 : 0;
    return `${count} (${formatPercent(pct)})`;
  }

  function buildHierarchyRows(scopeRows, scopeTotal) {
    const groups = new Map();

    scopeRows.forEach(row => {
      const category = displayLabel(row.bucket_category);
      const subcategory = displayLabel(row.bucket_subcategory);
      const disease = displayLabel(row.bucket_field);

      if (!groups.has(category)) {
        groups.set(category, {
          label: category,
          count: 0,
          maleCount: 0,
          femaleCount: 0,
          unknownCount: 0,
          subgroups: new Map(),
          diseases: [],
        });
      }
      const group = groups.get(category);
      group.count += row.coded_count || 0;
      group.maleCount += row.male_count || 0;
      group.femaleCount += row.female_count || 0;
      group.unknownCount += row.unknown_count || 0;

      if (subcategory !== '—') {
        if (!group.subgroups.has(subcategory)) {
          group.subgroups.set(subcategory, {
            label: subcategory,
            count: 0,
            maleCount: 0,
            femaleCount: 0,
            unknownCount: 0,
            diseases: [],
          });
        }
        const subgroup = group.subgroups.get(subcategory);
        subgroup.count += row.coded_count || 0;
        subgroup.maleCount += row.male_count || 0;
        subgroup.femaleCount += row.female_count || 0;
        subgroup.unknownCount += row.unknown_count || 0;
        subgroup.diseases.push({
          label: disease,
          count: row.coded_count || 0,
          maleCount: row.male_count || 0,
          femaleCount: row.female_count || 0,
          unknownCount: row.unknown_count || 0,
        });
      } else {
        group.diseases.push({
          label: disease,
          count: row.coded_count || 0,
          maleCount: row.male_count || 0,
          femaleCount: row.female_count || 0,
          unknownCount: row.unknown_count || 0,
        });
      }
    });

    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const hierarchyRows = [];

    Array.from(groups.values()).forEach((group, groupIndex) => {
      const groupCode = alphabet[groupIndex] || String(groupIndex + 1);
      hierarchyRows.push({
        code: groupCode,
        label: group.label,
        level: 0,
        maleCount: group.maleCount,
        femaleCount: group.femaleCount,
        unknownCount: group.unknownCount,
        totalText: formatCountPercent(group.count, scopeTotal),
      });

      const subgroupEntries = Array.from(group.subgroups.values());
      const collapseGroupIntoSingleSubgroup = (
        group.diseases.length === 0 &&
        subgroupEntries.length === 1 &&
        subgroupEntries[0].label === group.label
      );

      subgroupEntries.forEach((subgroup, subgroupIndex) => {
        const subgroupCode = `${groupCode}.${subgroupIndex + 1}`;
        const collapseSubgroupIntoDisease = (
          subgroup.diseases.length === 1 &&
          subgroup.diseases[0].label === subgroup.label
        );

        if (!collapseGroupIntoSingleSubgroup) {
          hierarchyRows.push({
            code: subgroupCode,
            label: subgroup.label,
            level: 1,
            maleCount: subgroup.maleCount,
            femaleCount: subgroup.femaleCount,
            unknownCount: subgroup.unknownCount,
            totalText: formatCountPercent(subgroup.count, scopeTotal),
          });
        }

        if (!collapseSubgroupIntoDisease) {
          subgroup.diseases.forEach((disease, diseaseIndex) => {
            const baseCode = collapseGroupIntoSingleSubgroup ? groupCode : subgroupCode;
            const baseLevel = collapseGroupIntoSingleSubgroup ? 1 : 2;
            hierarchyRows.push({
              code: `${baseCode}.${diseaseIndex + 1}`,
              label: disease.label,
              level: baseLevel,
              maleCount: disease.maleCount,
              femaleCount: disease.femaleCount,
              unknownCount: disease.unknownCount,
              totalText: formatCountPercent(disease.count, scopeTotal),
            });
          });
        }
      });

      const collapseGroupIntoDisease = (
        subgroupEntries.length === 0 &&
        group.diseases.length === 1 &&
        group.diseases[0].label === group.label
      );
      if (!collapseGroupIntoDisease) {
        group.diseases.forEach((disease, diseaseIndex) => {
          hierarchyRows.push({
            code: `${groupCode}.${diseaseIndex + 1}`,
            label: disease.label,
            level: 2,
            maleCount: disease.maleCount,
            femaleCount: disease.femaleCount,
            unknownCount: disease.unknownCount,
            totalText: formatCountPercent(disease.count, scopeTotal),
          });
        });
      }
    });

    return hierarchyRows;
  }

  function buildMainHeadingSeries(rows) {
    const totalsByHeading = new Map();
    rows.forEach(row => {
      const heading = displayLabel(row.bucket_category);
      if (heading === '—') return;
      totalsByHeading.set(heading, (totalsByHeading.get(heading) || 0) + (row.coded_count || 0));
    });
    return Array.from(totalsByHeading.entries())
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value);
  }

  function renderSummaryTable(bodyEl, rows, columns, emptyMessage) {
    if (!rows.length) {
      bodyEl.innerHTML = `<tr><td colspan="${columns.length}" class="text-center text-muted py-3">${escapeHtml(emptyMessage)}</td></tr>`;
      return;
    }
    bodyEl.innerHTML = rows.map(row => `
      <tr>
        ${columns.map(column => {
          const value = typeof column.render === 'function' ? column.render(row) : row[column.key];
          const className = column.className ? ` class="${column.className}"` : '';
          return `<td${className}>${value}</td>`;
        }).join('')}
      </tr>
    `).join('');
  }

  async function renderPieChart({ canvas, emptyEl, series, emptyMessage, legendPosition }) {
    if (canvas._chartInstance) {
      canvas._chartInstance.destroy();
      canvas._chartInstance = null;
    }
    if (!series.length) {
      canvas.classList.add('d-none');
      emptyEl.textContent = emptyMessage;
      emptyEl.classList.remove('d-none');
      return null;
    }
    canvas.classList.remove('d-none');
    emptyEl.classList.add('d-none');

    let Chart = null;
    try {
      Chart = await loadChartJs();
    } catch (error) {
      console.error(error);
      canvas.classList.add('d-none');
      emptyEl.textContent = 'Chart could not be loaded.';
      emptyEl.classList.remove('d-none');
      return null;
    }
    const chart = new Chart(canvas.getContext('2d'), {
      type: 'pie',
      data: {
        labels: series.map(item => item.label),
        datasets: [{
          data: series.map(item => item.value),
          backgroundColor: series.map((_, index) => chartPalette[index % chartPalette.length]),
          borderColor: '#ffffff',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: legendPosition || 'right',
            labels: {
              boxWidth: 14,
              boxHeight: 14,
              padding: 14,
              font: { size: 12 },
            },
          },
          tooltip: {
            callbacks: {
              label(context) {
                const total = context.dataset.data.reduce((sum, value) => sum + value, 0);
                return `${context.label}: ${formatCountPercent(context.raw, total)}`;
              },
            },
          },
        },
      },
    });
    canvas._chartInstance = chart;
    return chart;
  }

  async function renderBarChart({ canvas, emptyEl, series, emptyMessage, datasetLabel, indexAxis }) {
    if (canvas._chartInstance) {
      canvas._chartInstance.destroy();
      canvas._chartInstance = null;
    }
    if (!series.length) {
      canvas.classList.add('d-none');
      emptyEl.textContent = emptyMessage;
      emptyEl.classList.remove('d-none');
      return null;
    }
    canvas.classList.remove('d-none');
    emptyEl.classList.add('d-none');

    let Chart = null;
    try {
      Chart = await loadChartJs();
    } catch (error) {
      console.error(error);
      canvas.classList.add('d-none');
      emptyEl.textContent = 'Chart could not be loaded.';
      emptyEl.classList.remove('d-none');
      return null;
    }
    const isHorizontal = indexAxis === 'y';
    const chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: series.map(item => item.label),
        datasets: [{
          label: datasetLabel,
          data: series.map(item => item.value),
          backgroundColor: series.map((_, index) => chartPalette[index % chartPalette.length]),
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: indexAxis || 'x',
        scales: {
          x: {
            beginAtZero: isHorizontal,
            ticks: isHorizontal ? { precision: 0 } : { autoSkip: false },
          },
          y: {
            beginAtZero: !isHorizontal,
            ticks: isHorizontal ? { autoSkip: false } : { precision: 0 },
          },
        },
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            callbacks: {
              label(context) {
                return `${datasetLabel}: ${context.raw}`;
              },
            },
          },
        },
      },
    });
    canvas._chartInstance = chart;
    return chart;
  }

  async function renderMainHeadingChart(rows) {
    const series = buildMainHeadingSeries(rows);
    mainHeadingChart = await renderPieChart({
      canvas: els.mainHeadingChart,
      emptyEl: els.mainHeadingChartEmpty,
      series: series.map(item => ({ label: item.label, value: item.value })),
      emptyMessage: 'No matched category rows for the current filters.',
      legendPosition: 'right',
    });
  }

  async function renderTopCauses(topCauses) {
    renderSummaryTable(
      els.topCausesBody,
      topCauses,
      [
        { render: row => escapeHtml(row.rank), className: 'text-muted' },
        { render: row => escapeHtml(row.display_label) },
        { render: row => escapeHtml(`${row.coded_count} (${formatPercent(row.percent)})`), className: 'text-end' },
      ],
      'No matched cause rows for the current filters.',
    );
    topCausesChart = await renderBarChart({
      canvas: els.topCausesChart,
      emptyEl: els.topCausesChartEmpty,
      series: topCauses.map(row => ({ label: row.display_label, value: row.coded_count })),
      emptyMessage: 'No matched cause rows for the current filters.',
      datasetLabel: 'Coded deaths',
      indexAxis: 'y',
    });
  }

  async function renderAgeBandDistribution(rows) {
    renderSummaryTable(
      els.ageBandBody,
      rows,
      [
        { render: row => escapeHtml(row.age_band) },
        { render: row => escapeHtml(`${row.coded_count} (${formatPercent(row.percent)})`), className: 'text-end' },
      ],
      'No age-group rows for the current filters.',
    );
    ageBandChart = await renderBarChart({
      canvas: els.ageBandChart,
      emptyEl: els.ageBandChartEmpty,
      series: rows.map(row => ({ label: row.age_band, value: row.coded_count })),
      emptyMessage: 'No age-group rows for the current filters.',
      datasetLabel: 'Coded deaths',
      indexAxis: 'x',
    });
  }

  async function renderGenderDistribution(rows) {
    renderSummaryTable(
      els.genderBody,
      rows,
      [
        { render: row => escapeHtml(row.gender) },
        { render: row => escapeHtml(`${row.coded_count} (${formatPercent(row.percent)})`), className: 'text-end' },
      ],
      'No gender rows for the current filters.',
    );
    genderChart = await renderBarChart({
      canvas: els.genderChart,
      emptyEl: els.genderChartEmpty,
      series: rows.map(row => ({ label: row.gender, value: row.coded_count })),
      emptyMessage: 'No gender rows for the current filters.',
      datasetLabel: 'Coded deaths',
      indexAxis: 'x',
    });
  }

  function renderRows(rows, unmatchedSummary, unmatchedIcdBreakdown) {
    const unmatchedByScope = new Map(
      (unmatchedSummary || []).map(row => [normalizeScopeKey(row.age_scope), row.unmatched_count || 0])
    );
    droppedIcdRowsByScope.clear();
    (unmatchedIcdBreakdown || []).forEach(row => {
      const scope = normalizeScopeKey(row.age_scope);
      if (!droppedIcdRowsByScope.has(scope)) {
        droppedIcdRowsByScope.set(scope, []);
      }
      droppedIcdRowsByScope.get(scope).push(row);
    });
    if (!rows.length && unmatchedByScope.size === 0) {
      els.ageTables.innerHTML = '<div class="text-center text-muted py-4">No aggregate rows found.</div>';
      return;
    }
    const rowsByAge = rows.reduce((acc, row) => {
      const scope = normalizeScopeKey(row.age_scope);
      if (!acc[scope]) {
        acc[scope] = [];
      }
      acc[scope].push(row);
      return acc;
    }, {});
    const scopeKeys = new Set([...Object.keys(rowsByAge), ...Array.from(unmatchedByScope.keys())]);
    const sectionOrder = [
      ...ageScopeOrder.filter(scope => scopeKeys.has(scope)),
      ...Array.from(scopeKeys).filter(scope => !ageScopeOrder.includes(scope)).sort(),
    ];
    els.ageTables.innerHTML = sectionOrder.map(scope => {
      const scopeRows = rowsByAge[scope] || [];
      const scopeTotal = scopeRows.reduce((sum, row) => sum + (row.coded_count || 0), 0);
      const hierarchyRows = buildHierarchyRows(scopeRows, scopeTotal);
      const unmatchedCount = unmatchedByScope.get(scope) || 0;
      return `
        <section class="cod-bucket-age-section">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
            <div>
              <h6 class="mb-0">${ageScopeLabels[scope] || scope}</h6>
              <div class="small cod-bucket-muted">Total coded deaths: ${scopeTotal}</div>
            </div>
          </div>
          <div class="table-responsive cod-bucket-table-wrap">
            <table class="table table-sm align-middle cod-bucket-table">
              <thead>
                <tr>
                  <th class="cod-bucket-code-col">No.</th>
                  <th>Cause Grouping</th>
                  <th class="text-end">Male</th>
                  <th class="text-end">Female</th>
                  <th class="text-end">Unknown</th>
                  <th class="text-end">Total N (%)</th>
                </tr>
              </thead>
              <tbody>
                ${hierarchyRows.length ? hierarchyRows.map(row => `
                    <tr>
                      <td class="cod-bucket-code-col">${row.code}</td>
                      <td class="cod-bucket-label-cell">
                        <span class="cod-bucket-tree-label cod-bucket-level-${row.level}">${row.label}</span>
                      </td>
                      <td class="text-end">${row.maleCount || 0}</td>
                      <td class="text-end">${row.femaleCount || 0}</td>
                      <td class="text-end">${row.unknownCount || 0}</td>
                      <td class="text-end">
                        <span class="cod-bucket-tree-label cod-bucket-level-${row.level}">${row.totalText}</span>
                      </td>
                    </tr>
                `).join('') : `
                    <tr>
                      <td colspan="6" class="text-center text-muted py-3">No matched category rows.</td>
                    </tr>
                `}
              </tbody>
            </table>
          </div>
          ${unmatchedCount ? `
            <div class="small cod-bucket-muted mt-2">
              Note: ${unmatchedCount} submitted CoDs in this age group did not match any of the categories and were dropped.
              <button
                type="button"
                class="btn btn-link btn-sm p-0 align-baseline ms-1 cod-bucket-dropped-link"
                data-age-scope="${escapeHtml(scope)}"
              >
                View dropped CoDs
              </button>
            </div>
          ` : ''}
        </section>
      `;
    }).join('');
  }

  function renderDroppedModal(scope) {
    const scopeLabel = ageScopeLabels[scope] || scope;
    const rows = droppedIcdRowsByScope.get(scope) || [];
    els.droppedModalScope.textContent = scopeLabel;
    if (!rows.length) {
      els.droppedModalBody.innerHTML = '<div class="text-center text-muted py-4">No dropped CODs found.</div>';
      return;
    }
    const sectionSpecs = [
      {
        key: 'not_included_in_scheme',
        heading: `ICD codes not included in CoD Categories in ${els.selectedScheme.textContent || 'this'} Scheme for ${scopeLabel}`,
      },
      {
        key: 'not_eligible_for_coding',
        heading: 'ICD codes not eligible for coding',
      },
    ];
    els.droppedModalBody.innerHTML = sectionSpecs.map(section => {
      const sectionRows = rows.filter(row => row.category === section.key);
      if (!sectionRows.length) {
        return `
          <section class="mb-4">
            <h6 class="mb-2">${escapeHtml(section.heading)}</h6>
            <div class="text-muted small">None.</div>
          </section>
        `;
      }
      return `
        <section class="mb-4">
          <h6 class="mb-2">${escapeHtml(section.heading)}</h6>
          <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th style="width: 5rem;">No.</th>
                  <th>ICD Code</th>
                  <th class="text-end">Count</th>
                </tr>
              </thead>
              <tbody>
                ${sectionRows.map((row, index) => `
                  <tr>
                    <td>${index + 1}</td>
                    <td>${escapeHtml(row.icd_code || '—')}</td>
                    <td class="text-end">${row.unmatched_count || 0}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </section>
      `;
    }).join('');
  }

  function updateScopeText() {
    const parts = [];
    const schemeText = els.scheme.options[els.scheme.selectedIndex]?.text || els.scheme.value || 'Scheme';
    els.selectedScheme.textContent = schemeText;
    parts.push(schemeText);
    if (els.project.value) parts.push(els.project.value);
    if (els.site.value) parts.push(els.site.value);
    if (els.form.value) parts.push(els.form.value);
    if (els.dateFrom.value || els.dateTo.value) {
      parts.push(`${els.dateFrom.value || '...'} to ${els.dateTo.value || '...'}`);
    }
    els.scope.textContent = parts.join(' / ') || 'All in-scope coded submissions';
  }

  function renderLoadingState() {
    els.ageTables.innerHTML = '<div class="text-center text-muted py-4">Loading...</div>';
    els.topCausesBody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">Loading...</td></tr>';
    els.ageBandBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted py-3">Loading...</td></tr>';
    els.genderBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted py-3">Loading...</td></tr>';
    els.mainHeadingChartEmpty.textContent = 'No matched category rows for the current filters.';
    els.topCausesChartEmpty.textContent = 'No matched cause rows for the current filters.';
    els.ageBandChartEmpty.textContent = 'No age-group rows for the current filters.';
    els.genderChartEmpty.textContent = 'No gender rows for the current filters.';
  }

  async function loadAggregates() {
    renderLoadingState();
    updateScopeText();
    const params = new URLSearchParams();
    if (els.scheme.value) params.set('scheme_code', els.scheme.value);
    if (els.project.value) params.set('project_id', els.project.value);
    if (els.site.value) params.set('site_id', els.site.value);
    if (els.form.value) params.set('form_id', els.form.value);
    if (els.dateFrom.value) params.set('date_from', els.dateFrom.value);
    if (els.dateTo.value) params.set('date_to', els.dateTo.value);

    const response = await fetch(`/api/v1/cod-buckets/aggregates?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });
    const payload = await response.json();
    if (!response.ok) {
      els.ageTables.innerHTML = `<div class="text-center text-danger py-4">${payload.error || 'Failed to load aggregates.'}</div>`;
      els.coded.textContent = '0';
      await renderMainHeadingChart([]);
      await renderTopCauses([]);
      await renderAgeBandDistribution([]);
      await renderGenderDistribution([]);
      return;
    }
    const rows = payload.data || [];
    const summary = payload.summary || {};
    await renderMainHeadingChart(rows);
    await renderTopCauses(summary.top_causes || []);
    await renderAgeBandDistribution(summary.age_band_distribution || []);
    await renderGenderDistribution(summary.gender_distribution || []);
    renderRows(
      rows,
      summary.unmatched_by_age_scope || [],
      summary.unmatched_icd_breakdown || [],
    );
    els.coded.textContent = String(rows.reduce((sum, row) => sum + (row.coded_count || 0), 0));
  }

  els.project.addEventListener('change', () => {
    refreshSiteOptions();
    refreshFormOptions();
    updateScopeText();
  });
  els.site.addEventListener('change', () => {
    refreshFormOptions();
    updateScopeText();
  });
  els.form.addEventListener('change', updateScopeText);
  els.scheme.addEventListener('change', updateScopeText);
  els.dateFrom.addEventListener('change', updateScopeText);
  els.dateTo.addEventListener('change', updateScopeText);
  els.apply.addEventListener('click', loadAggregates);
  els.ageTables.addEventListener('click', event => {
    const trigger = event.target.closest('.cod-bucket-dropped-link');
    if (!trigger) return;
    const scope = normalizeScopeKey(trigger.dataset.ageScope);
    renderDroppedModal(scope);
    if (!droppedModal) {
      droppedModal = new bootstrap.Modal(els.droppedModal);
    }
    droppedModal.show();
  });

  syncSelectors();
  updateScopeText();
  loadAggregates();
})();
