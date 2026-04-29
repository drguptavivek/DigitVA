(function () {
  'use strict';

  const bootstrapData = window.COD_BUCKET_REPORTING_BOOTSTRAP || { forms: [], schemes: [] };
  const forms = bootstrapData.forms || [];
  const schemes = bootstrapData.schemes || [];
  const chartJsSrc = bootstrapData.chartJsSrc || '';
  const palette = [
    '#0f4c81', '#2e7d5b', '#d97706', '#b91c1c', '#7c3aed',
    '#0f766e', '#be185d', '#475569', '#65a30d', '#0284c7',
  ];
  const treemapPalette = ['#1d4ed8', '#0f766e', '#dc2626', '#65a30d', '#7c3aed', '#c2410c', '#0891b2'];
  const ageScopeLabels = {
    __none__: 'All Ages',
    adult_over5y: 'Adult / Over 5 Years',
    child_1_59m: 'Child / 1-59 Months',
    neonate: 'Neonate',
  };
  const ageScopeOrder = ['adult_over5y', 'child_1_59m', 'neonate'];

  const els = {
    scheme: document.getElementById('cod-bucket-scheme'),
    project: document.getElementById('cod-bucket-project'),
    site: document.getElementById('cod-bucket-site'),
    form: document.getElementById('cod-bucket-form'),
    dateFrom: document.getElementById('cod-bucket-date-from'),
    dateTo: document.getElementById('cod-bucket-date-to'),
    apply: document.getElementById('cod-bucket-apply'),
    export: document.getElementById('cod-bucket-export'),
    coded: document.getElementById('cod-bucket-kpi-coded'),
    schemeKpi: document.getElementById('cod-bucket-kpi-scheme'),
    scope: document.getElementById('cod-bucket-kpi-scope'),
    printSummaryLine: document.getElementById('cod-bucket-print-summary-line'),
    topCausesChart: document.getElementById('cod-bucket-top-causes-chart'),
    topCausesChartEmpty: document.getElementById('cod-bucket-top-causes-chart-empty'),
    topCausesBody: document.getElementById('cod-bucket-top-causes-body'),
    topCausesTitle: document.getElementById('cod-bucket-top-causes-title'),
    topCausesAgeFilter: document.getElementById('cod-bucket-top-causes-age-filter'),
    firstLevelChart: document.getElementById('cod-bucket-first-level-chart'),
    firstLevelChartEmpty: document.getElementById('cod-bucket-first-level-chart-empty'),
    firstLevelBody: document.getElementById('cod-bucket-first-level-body'),
    firstLevelTitle: document.getElementById('cod-bucket-first-level-title'),
    firstLevelAgeFilter: document.getElementById('cod-bucket-first-level-age-filter'),
    agePyramidChart: document.getElementById('cod-bucket-age-pyramid-chart'),
    agePyramidChartEmpty: document.getElementById('cod-bucket-age-pyramid-chart-empty'),
    genderPieChart: document.getElementById('cod-bucket-gender-pie-chart'),
    genderPieChartEmpty: document.getElementById('cod-bucket-gender-pie-chart-empty'),
    ageSexBody: document.getElementById('cod-bucket-age-sex-body'),
    heatmapView: document.getElementById('cod-bucket-heatmap-view'),
    heatmapDimension: document.getElementById('cod-bucket-heatmap-dimension'),
    heatmapWrap: document.getElementById('cod-bucket-heatmap-wrap'),
    heatmapEmpty: document.getElementById('cod-bucket-heatmap-empty'),
    treemap: document.getElementById('cod-bucket-treemap'),
    treemapEmpty: document.getElementById('cod-bucket-treemap-empty'),
    treemapTooltip: null,
    ageTables: document.getElementById('cod-bucket-age-tables'),
    droppedModal: document.getElementById('cod-bucket-dropped-modal'),
    droppedModalScope: document.getElementById('cod-bucket-dropped-modal-scope'),
    droppedModalBody: document.getElementById('cod-bucket-dropped-modal-body'),
  };

  let chartJsPromise = null;
  let droppedModal = null;
  let latestSummary = null;
  const droppedIcdRowsByScope = new Map();

  function uniq(values) {
    return Array.from(new Set(values.filter(Boolean)));
  }

  function optionHtml(value, label, selected) {
    const isSelected = String(selected || '') === String(value || '') ? ' selected' : '';
    return `<option value="${String(value || '').replace(/"/g, '&quot;')}"${isSelected}>${label}</option>`;
  }

  function populateAgeFilterOptions(selectEl, filters) {
    const selected = filters.some(item => item.key === selectEl.value) ? selectEl.value : 'all';
    selectEl.innerHTML = filters.map(item => optionHtml(item.key, item.label, selected)).join('');
  }

  function getAgeFilterLabel(filters, key) {
    const match = (filters || []).find(item => item.key === key);
    return match ? match.label : 'All ages';
  }

  function refreshProjectOptions() {
    const projects = uniq(forms.map(row => row.project_id)).sort();
    els.project.innerHTML = optionHtml('', 'All projects', els.project.value) + projects.map(
      value => optionHtml(value, value, els.project.value)
    ).join('');
  }

  function refreshSiteOptions() {
    const sites = uniq(forms.filter(row => !els.project.value || row.project_id === els.project.value).map(row => row.site_id)).sort();
    const selected = sites.includes(els.site.value) ? els.site.value : '';
    els.site.innerHTML = optionHtml('', 'All sites', selected) + sites.map(
      value => optionHtml(value, value, selected)
    ).join('');
  }

  function refreshFormOptions() {
    const scopedForms = forms.filter(row => {
      if (els.project.value && row.project_id !== els.project.value) return false;
      if (els.site.value && row.site_id !== els.site.value) return false;
      return true;
    });
    const selected = scopedForms.some(row => row.form_id === els.form.value) ? els.form.value : '';
    els.form.innerHTML = optionHtml('', 'All forms', selected) + scopedForms.map(
      row => optionHtml(row.form_id, `${row.form_id} - ${row.project_id}/${row.site_id}`, selected)
    ).join('');
  }

  function syncSelectors() {
    refreshProjectOptions();
    refreshSiteOptions();
    refreshFormOptions();
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatPercent(value) {
    return `${Number(value || 0).toFixed(1)}%`;
  }

  function formatTodayDate() {
    return new Intl.DateTimeFormat('en-GB', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(new Date());
  }

  function formatCountPercent(count, percent) {
    return `${count} (${formatPercent(percent)})`;
  }

  function formatCountColumnPercent(count, columnPercent) {
    return `${count} (${formatPercent(columnPercent)})`;
  }

  function formatInlineMetricHtml(count, percent) {
    return `
      <span class="cod-bucket-metric-inline">
        <span class="cod-bucket-metric-count">${escapeHtml(count)}</span>
        <span class="cod-bucket-metric-percent">(${escapeHtml(formatPercent(percent))})</span>
      </span>
    `;
  }

  function displayLabel(value) {
    if (value === null || value === undefined) return 'Unknown';
    const text = String(value).trim();
    return text || 'Unknown';
  }

  function wrapAxisLabel(value, maxLineLength = 30) {
    const text = String(value || '');
    if (text.length <= maxLineLength) {
      return text;
    }
    const words = text.split(/\s+/);
    const lines = [];
    let current = '';
    words.forEach(word => {
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length > maxLineLength && current) {
        lines.push(current);
        current = word;
      } else {
        current = candidate;
      }
    });
    if (current) {
      lines.push(current);
    }
    return lines;
  }

  function normalizeScopeKey(value) {
    return value === null || value === undefined || value === '' ? '__none__' : String(value);
  }

  function getSelectedSchemeName() {
    return els.scheme.options[els.scheme.selectedIndex]?.text || els.scheme.value || '—';
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

  function destroyChart(canvas) {
    if (canvas && canvas._chartInstance) {
      canvas._chartInstance.destroy();
      canvas._chartInstance = null;
    }
  }

  async function renderBarChart({ canvas, emptyEl, series, datasetLabel, indexAxis = 'x', stacked = false, datasets = null, emptyMessage, showBarLabels = false }) {
    destroyChart(canvas);
    if ((!series || !series.length) && !datasets) {
      canvas.classList.add('d-none');
      emptyEl.textContent = emptyMessage;
      emptyEl.classList.remove('d-none');
      return;
    }
    let Chart;
    try {
      Chart = await loadChartJs();
    } catch (error) {
      console.error(error);
      canvas.classList.add('d-none');
      emptyEl.textContent = 'Chart could not be loaded.';
      emptyEl.classList.remove('d-none');
      return;
    }

    canvas.classList.remove('d-none');
    emptyEl.classList.add('d-none');
    const rawLabels = datasets ? datasets.labels : series.map(item => item.label);
    const labels = indexAxis === 'y'
      ? rawLabels.map(label => wrapAxisLabel(label, 28))
      : rawLabels;
    const maxLabelLineLength = indexAxis === 'y'
      ? labels.reduce((max, label) => {
          const lines = Array.isArray(label) ? label : [label];
          const lineMax = lines.reduce((lineMaxValue, line) => Math.max(lineMaxValue, String(line).length), 0);
          return Math.max(max, lineMax);
        }, 0)
      : 0;
    const estimatedYAxisWidth = indexAxis === 'y'
      ? Math.min(360, Math.max(160, (maxLabelLineLength * 7) + 28))
      : 0;
    if (indexAxis === 'y') {
      const rowHeight = 52;
      const baseHeight = Math.max(420, (rawLabels.length * rowHeight) + 48);
      const rowEl = canvas.closest('.row');
      const siblingTableWrap = rowEl ? rowEl.querySelector('.cod-bucket-summary-table-wrap') : null;
      const siblingHeight = siblingTableWrap ? siblingTableWrap.getBoundingClientRect().height : 0;
      const computedHeight = Math.max(baseHeight, Math.ceil(siblingHeight));
      canvas.style.setProperty('height', `${computedHeight}px`, 'important');
      if (canvas.parentElement) {
        canvas.parentElement.style.minHeight = `${computedHeight}px`;
      }
    } else {
      canvas.style.removeProperty('height');
      if (canvas.parentElement) {
        canvas.parentElement.style.removeProperty('min-height');
      }
    }
    const chartDatasets = datasets ? datasets.datasets : [{
      label: datasetLabel,
      data: series.map(item => item.value),
      backgroundColor: series.map((_, index) => palette[index % palette.length]),
      borderRadius: 6,
    }];
    const barLabels = !datasets && showBarLabels ? series.map(item => item.dataLabel || '') : [];

    canvas._chartInstance = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets: chartDatasets },
      plugins: showBarLabels && !datasets ? [{
        id: 'codBucketBarLabels',
        afterDatasetsDraw(chart) {
          const { ctx } = chart;
          const meta = chart.getDatasetMeta(0);
          ctx.save();
          ctx.font = '600 12px sans-serif';
          ctx.textBaseline = 'middle';
          meta.data.forEach((bar, index) => {
            const label = barLabels[index];
            if (!label) return;
            const textWidth = ctx.measureText(label).width;
            const insideX = bar.x - 10;
            const outsideX = Math.min(bar.x + 8, chart.chartArea.right - 4);
            const canFitInside = insideX - textWidth >= chart.chartArea.left + 8;
            const y = bar.y;
            if (canFitInside) {
              ctx.textAlign = 'right';
              ctx.fillStyle = '#ffffff';
              ctx.fillText(label, insideX, y);
            } else {
              ctx.textAlign = outsideX >= chart.chartArea.right - 28 ? 'right' : 'left';
              ctx.fillStyle = '#334155';
              ctx.fillText(
                label,
                ctx.textAlign === 'right' ? chart.chartArea.right - 4 : outsideX,
                y,
              );
            }
          });
          ctx.restore();
        },
      }] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis,
        scales: {
          x: {
            stacked,
            ticks: { autoSkip: false, callback: value => stacked ? Math.abs(value) : value },
          },
          y: {
            stacked,
            afterFit(scale) {
              if (indexAxis === 'y') {
                scale.width = Math.max(scale.width, estimatedYAxisWidth);
              }
            },
            ticks: { autoSkip: false, font: { size: 12 } },
          },
        },
        plugins: {
          legend: { display: !!datasets },
          tooltip: {
            callbacks: {
              title(context) {
                return rawLabels[context[0].dataIndex];
              },
              label(context) {
                const value = datasets ? Math.abs(context.raw) : context.raw;
                return `${context.dataset.label}: ${value}`;
              },
            },
          },
        },
      },
    });
  }

  async function renderPieChart({ canvas, emptyEl, rows, labelKey, valueKey, emptyMessage }) {
    destroyChart(canvas);
    if (!rows.length) {
      canvas.classList.add('d-none');
      emptyEl.textContent = emptyMessage;
      emptyEl.classList.remove('d-none');
      return;
    }
    let Chart;
    try {
      Chart = await loadChartJs();
    } catch (error) {
      console.error(error);
      canvas.classList.add('d-none');
      emptyEl.textContent = 'Chart could not be loaded.';
      emptyEl.classList.remove('d-none');
      return;
    }
    canvas.classList.remove('d-none');
    emptyEl.classList.add('d-none');
    const values = rows.map(row => row[valueKey]);
    const total = values.reduce((sum, value) => sum + value, 0);
    canvas._chartInstance = new Chart(canvas.getContext('2d'), {
      type: 'pie',
      data: {
        labels: rows.map(row => row[labelKey]),
        datasets: [{
          data: values,
          backgroundColor: rows.map((_, index) => palette[index % palette.length]),
          borderColor: '#ffffff',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right' },
          tooltip: {
            callbacks: {
              label(context) {
                const value = context.raw || 0;
                const percent = total ? (value / total) * 100 : 0;
                return `${context.label}: ${value} (${formatPercent(percent)})`;
              },
            },
          },
        },
      },
    });
  }

  function renderSummaryTable(bodyEl, rows, columns, emptyMessage) {
    if (!rows.length) {
      bodyEl.innerHTML = `<tr><td colspan="${columns.length}" class="text-center text-muted py-3">${escapeHtml(emptyMessage)}</td></tr>`;
      return;
    }
    bodyEl.innerHTML = rows.map(row => `
      <tr>
        ${columns.map(column => `<td${column.className ? ` class="${column.className}"` : ''}>${column.render(row)}</td>`).join('')}
      </tr>
    `).join('');
  }

  function updateScopeText(summary) {
    const parts = [getSelectedSchemeName()];
    if (els.project.value) parts.push(els.project.value);
    if (els.site.value) parts.push(els.site.value);
    if (els.form.value) parts.push(els.form.value);
    if (els.dateFrom.value || els.dateTo.value) {
      parts.push(`${els.dateFrom.value || '...'} to ${els.dateTo.value || '...'}`);
    }
    els.scope.textContent = parts.join(' / ') || 'All in-scope coded submissions';
    els.schemeKpi.textContent = summary?.scheme_used || getSelectedSchemeName();
    if (els.printSummaryLine) {
      const filtersText = parts.join(' / ') || 'All in-scope coded submissions';
      const codedText = els.coded.textContent || '0';
      const schemeText = summary?.scheme_used || getSelectedSchemeName();
      els.printSummaryLine.textContent = `${formatTodayDate()} | Coded: ${codedText}, Scheme: ${schemeText}; Filters: ${filtersText}`;
    }
  }

  function currentFilterParams() {
    const params = new URLSearchParams();
    if (els.scheme.value) params.set('scheme_code', els.scheme.value);
    if (els.project.value) params.set('project_id', els.project.value);
    if (els.site.value) params.set('site_id', els.site.value);
    if (els.form.value) params.set('form_id', els.form.value);
    if (els.dateFrom.value) params.set('date_from', els.dateFrom.value);
    if (els.dateTo.value) params.set('date_to', els.dateTo.value);
    return params;
  }

  function buildHierarchyRows(scopeRows, scopeTotal, scopeColumnTotals) {
    const groups = new Map();
    scopeRows.forEach(row => {
      const category = displayLabel(row.bucket_category);
      const subcategory = row.bucket_subcategory ? displayLabel(row.bucket_subcategory) : null;
      const disease = displayLabel(row.bucket_field);
      if (!groups.has(category)) {
        groups.set(category, { label: category, male: 0, female: 0, unknown: 0, total: 0, subgroups: new Map(), diseases: [] });
      }
      const group = groups.get(category);
      group.male += row.male_count || 0;
      group.female += row.female_count || 0;
      group.unknown += row.unknown_count || 0;
      group.total += row.coded_count || 0;
      if (subcategory) {
        if (!group.subgroups.has(subcategory)) {
          group.subgroups.set(subcategory, { label: subcategory, male: 0, female: 0, unknown: 0, total: 0, diseases: [] });
        }
        const subgroup = group.subgroups.get(subcategory);
        subgroup.male += row.male_count || 0;
        subgroup.female += row.female_count || 0;
        subgroup.unknown += row.unknown_count || 0;
        subgroup.total += row.coded_count || 0;
        subgroup.diseases.push({ label: disease, male: row.male_count || 0, female: row.female_count || 0, unknown: row.unknown_count || 0, total: row.coded_count || 0 });
      } else {
        group.diseases.push({ label: disease, male: row.male_count || 0, female: row.female_count || 0, unknown: row.unknown_count || 0, total: row.coded_count || 0 });
      }
    });

    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const rows = [];
    Array.from(groups.values()).forEach((group, groupIndex) => {
      const groupCode = letters[groupIndex] || `${groupIndex + 1}`;
      rows.push({ code: groupCode, level: 0, label: group.label, male: group.male, female: group.female, unknown: group.unknown, total: group.total });
      Array.from(group.subgroups.values()).forEach((subgroup, subgroupIndex) => {
        const subgroupCode = `${groupCode}.${subgroupIndex + 1}`;
        rows.push({ code: subgroupCode, level: 1, label: subgroup.label, male: subgroup.male, female: subgroup.female, unknown: subgroup.unknown, total: subgroup.total });
        subgroup.diseases.forEach((disease, diseaseIndex) => {
          rows.push({ code: `${subgroupCode}.${diseaseIndex + 1}`, level: 2, label: disease.label, male: disease.male, female: disease.female, unknown: disease.unknown, total: disease.total });
        });
      });
      group.diseases.forEach((disease, diseaseIndex) => {
        rows.push({ code: `${groupCode}.${diseaseIndex + 1}`, level: 2, label: disease.label, male: disease.male, female: disease.female, unknown: disease.unknown, total: disease.total });
      });
    });

    return rows.map(row => ({
      ...row,
      maleHtml: formatInlineMetricHtml(
        row.male,
        scopeColumnTotals.male ? (row.male / scopeColumnTotals.male) * 100 : 0,
      ),
      femaleHtml: formatInlineMetricHtml(
        row.female,
        scopeColumnTotals.female ? (row.female / scopeColumnTotals.female) * 100 : 0,
      ),
      unknownHtml: formatInlineMetricHtml(
        row.unknown,
        scopeColumnTotals.unknown ? (row.unknown / scopeColumnTotals.unknown) * 100 : 0,
      ),
      totalHtml: formatInlineMetricHtml(
        row.total,
        scopeTotal ? (row.total / scopeTotal) * 100 : 0,
      ),
    }));
  }

  function renderRows(rows, unmatchedSummary, unmatchedIcdBreakdown) {
    const unmatchedByScope = new Map((unmatchedSummary || []).map(row => [normalizeScopeKey(row.age_scope), row.unmatched_count || 0]));
    droppedIcdRowsByScope.clear();
    (unmatchedIcdBreakdown || []).forEach(row => {
      const key = normalizeScopeKey(row.age_scope);
      if (!droppedIcdRowsByScope.has(key)) droppedIcdRowsByScope.set(key, []);
      droppedIcdRowsByScope.get(key).push(row);
    });
    if (!rows.length && !unmatchedByScope.size) {
      els.ageTables.innerHTML = '<div class="text-center text-muted py-4">No detailed cause rows found.</div>';
      return;
    }

    const rowsByScope = rows.reduce((acc, row) => {
      const key = normalizeScopeKey(row.age_scope);
      if (!acc[key]) acc[key] = [];
      acc[key].push(row);
      return acc;
    }, {});
    const scopeMeta = new Map();
    rows.forEach(row => {
      const key = normalizeScopeKey(row.age_scope);
      if (!scopeMeta.has(key)) {
        scopeMeta.set(key, {
          label: row.age_scope_label || ageScopeLabels[key] || key,
          sortOrder: Number(row.age_scope_sort_order || (key === '__none__' ? 1 : 999)),
        });
      }
    });
    (unmatchedSummary || []).forEach(row => {
      const key = normalizeScopeKey(row.age_scope);
      if (!scopeMeta.has(key)) {
        scopeMeta.set(key, {
          label: row.age_scope_label || ageScopeLabels[key] || key,
          sortOrder: Number(row.age_scope_sort_order || (key === '__none__' ? 1 : 999)),
        });
      }
    });
    const scopes = new Set([...Object.keys(rowsByScope), ...Array.from(unmatchedByScope.keys())]);
    const sectionOrder = Array.from(scopes).sort((left, right) => {
      if (left === '__none__' && right !== '__none__') return -1;
      if (right === '__none__' && left !== '__none__') return 1;
      const leftMeta = scopeMeta.get(left) || { label: ageScopeLabels[left] || left, sortOrder: 999 };
      const rightMeta = scopeMeta.get(right) || { label: ageScopeLabels[right] || right, sortOrder: 999 };
      if (leftMeta.sortOrder !== rightMeta.sortOrder) {
        return leftMeta.sortOrder - rightMeta.sortOrder;
      }
      const leftFallback = ageScopeOrder.includes(left) ? ageScopeOrder.indexOf(left) : 999;
      const rightFallback = ageScopeOrder.includes(right) ? ageScopeOrder.indexOf(right) : 999;
      if (leftFallback !== rightFallback) {
        return leftFallback - rightFallback;
      }
      return leftMeta.label.localeCompare(rightMeta.label);
    });

    els.ageTables.innerHTML = sectionOrder.map(scope => {
      const scopeRows = rowsByScope[scope] || [];
      const scopeTotal = scopeRows.reduce((sum, row) => sum + (row.coded_count || 0), 0);
      const scopeColumnTotals = {
        male: scopeRows.reduce((sum, row) => sum + (row.male_count || 0), 0),
        female: scopeRows.reduce((sum, row) => sum + (row.female_count || 0), 0),
        unknown: scopeRows.reduce((sum, row) => sum + (row.unknown_count || 0), 0),
      };
      const hierarchy = buildHierarchyRows(scopeRows, scopeTotal, scopeColumnTotals);
      const unmatchedCount = unmatchedByScope.get(scope) || 0;
      return `
        <section class="cod-bucket-age-section">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
            <div>
              <h6 class="mb-0">${escapeHtml((scopeMeta.get(scope) || {}).label || ageScopeLabels[scope] || scope)}</h6>
              <div class="small cod-bucket-muted">Total coded deaths: ${scopeTotal}</div>
            </div>
          </div>
          <div class="table-responsive cod-bucket-table-wrap">
            <table class="table table-sm align-middle cod-bucket-table">
              <thead>
                <tr>
                  <th class="cod-bucket-code-col">No.</th>
                  <th>Cause grouping</th>
                  <th class="text-end cod-bucket-col-metric">Male</th>
                  <th class="text-end cod-bucket-col-metric">Female</th>
                  <th class="text-end cod-bucket-col-metric">Unknown</th>
                  <th class="text-end cod-bucket-col-metric">Total</th>
                </tr>
              </thead>
              <tbody>
                ${hierarchy.length ? hierarchy.map(row => `
                  <tr class="cod-bucket-row-level-${row.level}">
                    <td class="cod-bucket-code-col">${escapeHtml(row.code)}</td>
                    <td class="cod-bucket-label-cell"><span class="cod-bucket-tree-label cod-bucket-level-${row.level}">${escapeHtml(row.label)}</span></td>
                    <td class="text-end cod-bucket-value-cell">${row.maleHtml}</td>
                    <td class="text-end cod-bucket-value-cell">${row.femaleHtml}</td>
                    <td class="text-end cod-bucket-value-cell">${row.unknownHtml}</td>
                    <td class="text-end cod-bucket-value-cell">${row.totalHtml}</td>
                  </tr>
                `).join('') : '<tr><td colspan="6" class="text-center text-muted py-3">No matched category rows.</td></tr>'}
              </tbody>
            </table>
          </div>
          ${unmatchedCount ? `
            <div class="small cod-bucket-muted mt-2">
              ${unmatchedCount} coded deaths in this section did not match any reporting category.
              <button type="button" class="btn btn-link btn-sm p-0 align-baseline ms-1 cod-bucket-dropped-link" data-age-scope="${escapeHtml(scope)}">View dropped CoDs</button>
            </div>
          ` : ''}
        </section>
      `;
    }).join('');
  }

  function renderDroppedModal(scope) {
    const rows = droppedIcdRowsByScope.get(scope) || [];
    const scopeLabel = ageScopeLabels[scope] || scope;
    els.droppedModalScope.textContent = scopeLabel;
    if (!rows.length) {
      els.droppedModalBody.innerHTML = '<div class="text-center text-muted py-4">No dropped CODs found.</div>';
      return;
    }
    const sections = [
      { key: 'not_included_in_scheme', heading: `ICD codes not included in ${getSelectedSchemeName()}` },
      { key: 'not_eligible_for_coding', heading: 'ICD codes not eligible for coding' },
    ];
    els.droppedModalBody.innerHTML = sections.map(section => {
      const sectionRows = rows.filter(row => row.category === section.key);
      if (!sectionRows.length) {
        return `<section class="mb-4"><h6 class="mb-2">${escapeHtml(section.heading)}</h6><div class="text-muted small">None.</div></section>`;
      }
      return `
        <section class="mb-4">
          <h6 class="mb-2">${escapeHtml(section.heading)}</h6>
          <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead><tr><th style="width:5rem;">No.</th><th>ICD code</th><th class="text-end">Count</th></tr></thead>
              <tbody>
                ${sectionRows.map((row, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(row.icd_code || '—')}</td><td class="text-end">${row.unmatched_count || 0}</td></tr>`).join('')}
              </tbody>
            </table>
          </div>
        </section>
      `;
    }).join('');
  }

  function renderHeatmap(summary) {
    const view = els.heatmapView.value || summary.heatmap?.view || 'top_causes';
    const dimension = els.heatmapDimension.value || summary.heatmap?.dimension || 'country';
    const dimensionRows = summary.heatmap?.views?.[view]?.[dimension] || [];
    if (!dimensionRows.length) {
      els.heatmapWrap.innerHTML = '';
      els.heatmapEmpty.classList.remove('d-none');
      return;
    }
    els.heatmapEmpty.classList.add('d-none');
    const dimensionLabel = dimension.charAt(0).toUpperCase() + dimension.slice(1);
    const causes = (dimensionRows[0]?.values || []).map(item => ({
      cause: item.cause,
      display_label: item.display_label,
    }));
    const maxValue = dimensionRows.reduce(
      (max, row) => Math.max(max, ...row.values.map(item => item.coded_count || 0)),
      0,
    ) || 1;
    const valuesByDimension = new Map(
      dimensionRows.map(row => [
        row.label,
        new Map(
          row.values.map(item => [item.cause, item])
        ),
      ]),
    );
    const columnTotals = new Map(
      dimensionRows.map(row => [
        row.label,
        row.values.reduce((sum, item) => sum + (item.coded_count || 0), 0),
      ]),
    );
    els.heatmapWrap.innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm align-middle cod-bucket-heatmap-table mb-0">
          <thead>
            <tr>
              <th>Cause</th>
              ${dimensionRows.map(row => `<th>${escapeHtml(row.label)}</th>`).join('')}
            </tr>
          </thead>
          <tbody>
            ${causes.map(cause => `
              <tr>
                <th>${escapeHtml(cause.display_label)}</th>
                ${dimensionRows.map(row => {
                  const cell = valuesByDimension.get(row.label)?.get(cause.cause) || {
                    coded_count: 0,
                    percent: 0,
                    display_label: cause.display_label,
                  };
                  const columnTotal = columnTotals.get(row.label) || 0;
                  const columnPercent = columnTotal ? ((cell.coded_count || 0) / columnTotal) * 100 : 0;
                  const ratio = (cell.coded_count || 0) / maxValue;
                  const bg = `rgba(15, 76, 129, ${Math.max(0.08, ratio)})`;
                  const title = `${cause.display_label} / ${dimensionLabel}: ${row.label} / ${cell.coded_count} (${formatPercent(columnPercent)})`;
                  return `<td class="cod-bucket-heatmap-cell" style="background:${bg}" title="${escapeHtml(title)}">${cell.coded_count}<div class="small">${formatPercent(columnPercent)}</div></td>`;
                }).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderTreemap(summary) {
    const rows = summary.treemap || [];
    if (!rows.length) {
      els.treemap.innerHTML = '';
      els.treemapEmpty.classList.remove('d-none');
      return;
    }
    els.treemapEmpty.classList.add('d-none');
    const total = rows.reduce((sum, row) => sum + (row.coded_count || 0), 0) || 1;
    const groupColors = new Map();
    rows.forEach(row => {
      if (!groupColors.has(row.group)) {
        groupColors.set(row.group, treemapPalette[groupColors.size % treemapPalette.length]);
      }
    });

    function computeTreemapLayout(items, x, y, width, height) {
      if (!items.length) {
        return [];
      }
      if (items.length === 1) {
        return [{ ...items[0], x, y, width, height }];
      }

      const sum = items.reduce((acc, item) => acc + (item.coded_count || 0), 0);
      let running = 0;
      let splitIndex = 1;
      for (let index = 0; index < items.length; index += 1) {
        running += items[index].coded_count || 0;
        if (running >= sum / 2) {
          splitIndex = index + 1;
          break;
        }
      }
      const first = items.slice(0, splitIndex);
      const second = items.slice(splitIndex);
      const firstSum = first.reduce((acc, item) => acc + (item.coded_count || 0), 0);
      const ratio = sum ? firstSum / sum : 0.5;

      if (width >= height) {
        const firstWidth = width * ratio;
        return [
          ...computeTreemapLayout(first, x, y, firstWidth, height),
          ...computeTreemapLayout(second, x + firstWidth, y, width - firstWidth, height),
        ];
      }

      const firstHeight = height * ratio;
      return [
        ...computeTreemapLayout(first, x, y, width, firstHeight),
        ...computeTreemapLayout(second, x, y + firstHeight, width, height - firstHeight),
      ];
    }

    const layout = computeTreemapLayout(
      [...rows].sort((a, b) => (b.coded_count || 0) - (a.coded_count || 0)),
      0,
      0,
      100,
      100,
    );

    els.treemap.innerHTML = layout.map(row => {
      const tooSmallForGroup = row.width < 10 || row.height < 10;
      const tooSmallForValue = row.width < 14 || row.height < 14;
      const tooltipText = `${row.group}\n${row.label}\n${row.coded_count} (${formatPercent(row.percent)})`;
      return `
        <div
          class="cod-bucket-treemap-node"
          style="left:${row.x}%;top:${row.y}%;width:${row.width}%;height:${row.height}%;background:${groupColors.get(row.group)}"
          title="${escapeHtml(`${row.label}: ${row.coded_count} (${formatPercent(row.percent)})`)}"
          data-treemap-tooltip="${escapeHtml(tooltipText)}"
        >
          <div class="cod-bucket-treemap-group${tooSmallForGroup ? ' d-none' : ''}">${escapeHtml(row.group)}</div>
          <div class="cod-bucket-treemap-label">${escapeHtml(row.label)}</div>
          <div class="cod-bucket-treemap-value${tooSmallForValue ? ' d-none' : ''}">${row.coded_count} (${formatPercent(row.percent)})</div>
        </div>
      `;
    }).join('');
  }

  async function renderTopCauses(rows, ageLabel = 'All ages') {
    els.topCausesTitle.textContent = ageLabel === 'All ages'
      ? 'Top 10 Causes of Death'
      : `Top 10 Causes of Death: ${ageLabel}`;
    renderSummaryTable(
      els.topCausesBody,
      rows,
      [
        { render: row => escapeHtml(row.rank), className: 'text-muted' },
        { render: row => escapeHtml(row.display_label) },
        { render: row => escapeHtml(formatCountPercent(row.coded_count, row.percent)), className: 'text-end' },
      ],
      'No matched cause rows for the current filters.',
    );
    await renderBarChart({
      canvas: els.topCausesChart,
      emptyEl: els.topCausesChartEmpty,
      series: rows.map(row => ({ label: row.display_label, value: row.coded_count, dataLabel: formatCountPercent(row.coded_count, row.percent) })),
      datasetLabel: 'Coded deaths',
      indexAxis: 'y',
      emptyMessage: 'No matched cause rows for the current filters.',
      showBarLabels: true,
    });
  }

  async function renderFirstLevel(rows, ageLabel = 'All ages') {
    els.firstLevelTitle.textContent = ageLabel === 'All ages'
      ? 'Main Cause Groups'
      : `Main Cause Groups: ${ageLabel}`;
    renderSummaryTable(
      els.firstLevelBody,
      rows,
      [
        { render: row => escapeHtml(row.label) },
        { render: row => escapeHtml(formatCountPercent(row.coded_count, row.percent)), className: 'text-end' },
      ],
      'No grouped cause rows for the current filters.',
    );
    await renderBarChart({
      canvas: els.firstLevelChart,
      emptyEl: els.firstLevelChartEmpty,
      series: rows.map(row => ({ label: row.label, value: row.coded_count, dataLabel: formatCountPercent(row.coded_count, row.percent) })),
      datasetLabel: 'Coded deaths',
      indexAxis: 'y',
      emptyMessage: 'No grouped cause rows for the current filters.',
      showBarLabels: true,
    });
  }

  async function renderAgeSex(rows) {
    const maleTotal = rows.reduce((sum, row) => sum + (row.male_count || 0), 0);
    const femaleTotal = rows.reduce((sum, row) => sum + (row.female_count || 0), 0);
    const unknownTotal = rows.reduce((sum, row) => sum + (row.unknown_count || 0), 0);
    renderSummaryTable(
      els.ageSexBody,
      rows,
      [
        { render: row => escapeHtml(row.age_band) },
        {
          render: row => escapeHtml(
            formatCountColumnPercent(
              row.male_count,
              maleTotal ? (row.male_count / maleTotal) * 100 : 0,
            )
          ),
          className: 'text-end',
        },
        {
          render: row => escapeHtml(
            formatCountColumnPercent(
              row.female_count,
              femaleTotal ? (row.female_count / femaleTotal) * 100 : 0,
            )
          ),
          className: 'text-end',
        },
        {
          render: row => escapeHtml(
            formatCountColumnPercent(
              row.unknown_count,
              unknownTotal ? (row.unknown_count / unknownTotal) * 100 : 0,
            )
          ),
          className: 'text-end',
        },
        { render: row => escapeHtml(formatCountPercent(row.total_count, row.total_percent)), className: 'text-end' },
      ],
      'No age and sex rows for the current filters.',
    );
    await renderBarChart({
      canvas: els.agePyramidChart,
      emptyEl: els.agePyramidChartEmpty,
      datasets: {
        labels: rows.map(row => row.age_band),
        datasets: [
          { label: 'Male', data: rows.map(row => -(row.male_count || 0)), backgroundColor: '#2563eb' },
          { label: 'Female', data: rows.map(row => row.female_count || 0), backgroundColor: '#db2777' },
          { label: 'Unknown', data: rows.map(row => row.unknown_count || 0), backgroundColor: '#64748b' },
        ],
      },
      indexAxis: 'y',
      stacked: true,
      emptyMessage: 'No age and sex rows for the current filters.',
    });
  }

  async function renderGenderPie(rows) {
    await renderPieChart({
      canvas: els.genderPieChart,
      emptyEl: els.genderPieChartEmpty,
      rows,
      labelKey: 'gender',
      valueKey: 'coded_count',
      emptyMessage: 'No sex rows for the current filters.',
    });
  }

  function renderLoadingState() {
    els.topCausesBody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">Loading...</td></tr>';
    els.firstLevelBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted py-3">Loading...</td></tr>';
    els.ageSexBody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">Loading...</td></tr>';
    els.ageTables.innerHTML = '<div class="text-center text-muted py-4">Loading...</div>';
    els.heatmapWrap.innerHTML = '';
    els.treemap.innerHTML = '';
    destroyChart(els.topCausesChart);
    destroyChart(els.firstLevelChart);
    destroyChart(els.agePyramidChart);
    destroyChart(els.genderPieChart);
  }

  async function loadAggregates() {
    renderLoadingState();
    updateScopeText();
    const params = currentFilterParams();

    const response = await fetch(`/api/v1/cod-buckets/aggregates?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });
    const payload = await response.json();
    if (!response.ok) {
      els.ageTables.innerHTML = `<div class="text-center text-danger py-4">${escapeHtml(payload.error || 'Failed to load aggregates.')}</div>`;
      els.coded.textContent = '0';
      return;
    }
    const rows = payload.data || [];
    const summary = payload.summary || {};
    latestSummary = summary;
    const ageFilters = summary.age_filters || [{ key: 'all', label: 'All ages' }];
    populateAgeFilterOptions(els.topCausesAgeFilter, ageFilters);
    populateAgeFilterOptions(els.firstLevelAgeFilter, ageFilters);
    const topCausesAgeKey = els.topCausesAgeFilter.value || 'all';
    const firstLevelAgeKey = els.firstLevelAgeFilter.value || 'all';
    els.coded.textContent = String(summary.matched_total || rows.reduce((sum, row) => sum + (row.coded_count || 0), 0));
    updateScopeText(summary);
    await renderTopCauses(
      (summary.top_causes_by_age && summary.top_causes_by_age[topCausesAgeKey]) || summary.top_causes || [],
      getAgeFilterLabel(ageFilters, topCausesAgeKey),
    );
    await renderFirstLevel(
      (summary.first_level_counts_by_age && summary.first_level_counts_by_age[firstLevelAgeKey]) || summary.first_level_counts || [],
      getAgeFilterLabel(ageFilters, firstLevelAgeKey),
    );
    await renderAgeSex(summary.age_sex_distribution || []);
    await renderGenderPie(summary.gender_distribution || []);
    renderHeatmap(summary);
    renderTreemap(summary);
    renderRows(rows, summary.unmatched_by_age_scope || [], summary.unmatched_icd_breakdown || []);
  }

  els.project.addEventListener('change', () => {
    refreshSiteOptions();
    refreshFormOptions();
    updateScopeText(latestSummary);
  });
  els.site.addEventListener('change', () => {
    refreshFormOptions();
    updateScopeText(latestSummary);
  });
  [els.form, els.scheme, els.dateFrom, els.dateTo].forEach(el => {
    el.addEventListener('change', () => updateScopeText(latestSummary));
  });
  els.apply.addEventListener('click', loadAggregates);
  els.export.addEventListener('click', () => {
    const params = currentFilterParams();
    window.location.assign(`/api/v1/cod-buckets/export.csv?${params.toString()}`);
  });
  els.topCausesAgeFilter.addEventListener('change', async () => {
    if (!latestSummary) return;
    const filters = latestSummary.age_filters || [{ key: 'all', label: 'All ages' }];
    const ageKey = els.topCausesAgeFilter.value || 'all';
    await renderTopCauses(
      (latestSummary.top_causes_by_age && latestSummary.top_causes_by_age[ageKey]) || latestSummary.top_causes || [],
      getAgeFilterLabel(filters, ageKey),
    );
  });
  els.firstLevelAgeFilter.addEventListener('change', async () => {
    if (!latestSummary) return;
    const filters = latestSummary.age_filters || [{ key: 'all', label: 'All ages' }];
    const ageKey = els.firstLevelAgeFilter.value || 'all';
    await renderFirstLevel(
      (latestSummary.first_level_counts_by_age && latestSummary.first_level_counts_by_age[ageKey]) || latestSummary.first_level_counts || [],
      getAgeFilterLabel(filters, ageKey),
    );
  });
  els.heatmapView.addEventListener('change', () => {
    if (latestSummary) renderHeatmap(latestSummary);
  });
  els.heatmapDimension.addEventListener('change', () => {
    if (latestSummary) renderHeatmap(latestSummary);
  });
  els.treemap.addEventListener('mousemove', event => {
    const tile = event.target.closest('.cod-bucket-treemap-node');
    if (!tile || !els.treemapTooltip) return;
    const tooltip = els.treemapTooltip;
    tooltip.textContent = tile.dataset.treemapTooltip || '';
    tooltip.classList.add('is-visible');
    tooltip.style.left = `${event.clientX + 14}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
  });
  els.treemap.addEventListener('mouseleave', () => {
    if (els.treemapTooltip) {
      els.treemapTooltip.classList.remove('is-visible');
    }
  });
  els.treemap.addEventListener('mouseover', event => {
    const tile = event.target.closest('.cod-bucket-treemap-node');
    if (!tile || !els.treemapTooltip) return;
    els.treemapTooltip.textContent = tile.dataset.treemapTooltip || '';
    els.treemapTooltip.classList.add('is-visible');
  });
  els.treemap.addEventListener('mouseout', event => {
    if (!event.relatedTarget || !event.relatedTarget.closest('.cod-bucket-treemap-node')) {
      if (els.treemapTooltip) {
        els.treemapTooltip.classList.remove('is-visible');
      }
    }
  });
  els.ageTables.addEventListener('click', event => {
    const trigger = event.target.closest('.cod-bucket-dropped-link');
    if (!trigger) return;
    renderDroppedModal(normalizeScopeKey(trigger.dataset.ageScope));
    if (!droppedModal) droppedModal = new bootstrap.Modal(els.droppedModal);
    droppedModal.show();
  });

  syncSelectors();
  els.treemapTooltip = document.createElement('div');
  els.treemapTooltip.className = 'cod-bucket-treemap-tooltip';
  document.body.appendChild(els.treemapTooltip);
  updateScopeText();
  loadAggregates();
})();
