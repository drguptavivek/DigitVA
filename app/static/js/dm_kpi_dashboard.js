/**
 * DM KPI Dashboard — Real-time data manager analytics
 * Fetches from /api/v1/analytics/dm-kpi/* endpoints and renders charts/tables
 * Covers: C-01 through C-24 + D-series drill-downs
 */
(function () {
  'use strict';

  // ─────────────────────────────────────────────────────────────
  // CONFIG & STATE
  // ─────────────────────────────────────────────────────────────

  const CONFIG = window.DM_KPI_CONFIG || {};
  const CSRF = CONFIG.csrfToken || '';
  const CHARTJS_SRC = CONFIG.chartJsSrc || '';

  let dayWindow = 7;
  let coderRange = '7d';
  let burndownData = null;
  let chartBurndown = null;
  let chartInflow = null;
  let chartBacklog = null;
  let agGridInstance = null;

  // Chart.js lazy loader
  let chartJsPromise = null;
  function loadChartJs() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (!chartJsPromise) {
      chartJsPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = CHARTJS_SRC;
        script.async = true;
        script.onload = () => resolve(window.Chart);
        script.onerror = () => reject(new Error('Failed to load Chart.js'));
        document.head.appendChild(script);
      });
    }
    return chartJsPromise;
  }

  // ─────────────────────────────────────────────────────────────
  // FETCH HELPER
  // ─────────────────────────────────────────────────────────────

  function jsonFetch(url) {
    return fetch(url, {
      method: 'GET',
      headers: { 'X-CSRFToken': CSRF },
    })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .catch(error => {
        console.error('Fetch error:', error);
        throw error;
      });
  }

  function showContent(containerId) {
    const loadingEl = document.getElementById(containerId + '-loading');
    const contentEl = document.getElementById(containerId + '-content');
    if (loadingEl) loadingEl.style.display = 'none';
    if (contentEl) contentEl.style.display = 'block';
  }

  function showError(containerId, message) {
    const loadingEl = document.getElementById(containerId + '-loading');
    if (loadingEl) {
      loadingEl.innerHTML = '<div class="alert alert-danger mb-0 py-2"><small>' + (message || 'Could not load data') + '</small></div>';
    }
  }

  function formatHours(seconds) {
    if (!seconds || seconds === null) return '—';
    const h = Math.round(seconds / 3600);
    if (h < 24) return h + 'h';
    return (h / 24).toFixed(1) + 'd';
  }

  function formatRate(val) {
    if (val === null || val === undefined) return '—';
    return val.toFixed(1) + '%';
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: OVERVIEW CARDS (C-04 pending, C-16 rate, C-17 days, C-21 utilization)
  // ─────────────────────────────────────────────────────────────

  function loadOverviewCards() {
    return Promise.all([
      jsonFetch('/api/v1/analytics/dm-kpi/burndown/'),
      jsonFetch('/api/v1/analytics/dm-kpi/coders/utilization'),
    ])
      .then(([burndown, utilization]) => {
        burndownData = burndown;
        document.getElementById('kpi-pending-value').textContent = burndown.c17_pending || 0;
        document.getElementById('kpi-rate-value').textContent = (burndown.c16_mean_daily_rate || 0).toFixed(1);

        const daysVal = burndown.c17_predicted_days;
        if (daysVal === 'infinite' || daysVal === Infinity) {
          document.getElementById('kpi-days-value').textContent = '∞';
        } else if (daysVal === null) {
          document.getElementById('kpi-days-value').textContent = '—';
        } else {
          document.getElementById('kpi-days-value').textContent = daysVal.toFixed(1);
        }

        document.getElementById('kpi-utilization-value').textContent = (utilization.rate || 0).toFixed(1) + '%';

        document.querySelectorAll('.dm-kpi-card .dm-kpi-loading').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.dm-kpi-card .dm-kpi-content').forEach(el => el.style.display = 'block');
      })
      .catch(error => {
        console.error('Error loading overview cards:', error);
        document.querySelectorAll('.dm-kpi-card .dm-kpi-loading').forEach(el => {
          el.innerHTML = '<div class="alert alert-danger mb-0 py-2"><small>Could not load data</small></div>';
        });
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: DAILY GRID (C-01)
  // ─────────────────────────────────────────────────────────────

  function loadDailyGrid() {
    return jsonFetch('/api/v1/analytics/dm-kpi/grid/?days=8')
      .then(response => {
        const { data = [] } = response;
        const gridData = data.map(row => ({
          date: row.date,
          new: row.new_from_odk || 0,
          updated: row.updated_from_odk || 0,
          coded: row.coded || 0,
          pending: row.pending || 0,
          consent_refused: row.consent_refused || 0,
        }));

        // Destroy previous grid instance before recreating
        if (agGridInstance) {
          agGridInstance.destroy();
          agGridInstance = null;
        }

        const gridContainer = document.getElementById('dm-kpi-daily-grid');
        const gridOptions = {
          columnDefs: [
            { field: 'date', headerName: 'Date', flex: 1, sort: 'desc' },
            { field: 'new', headerName: 'New', flex: 1, type: 'rightAligned' },
            { field: 'updated', headerName: 'Updated', flex: 1, type: 'rightAligned' },
            { field: 'coded', headerName: 'Coded', flex: 1, type: 'rightAligned' },
            { field: 'pending', headerName: 'Pending', flex: 1, type: 'rightAligned' },
            { field: 'consent_refused', headerName: 'Consent Refused', flex: 1, type: 'rightAligned' },
          ],
          rowData: gridData,
          domLayout: 'normal',
          defaultColDef: { resizable: true, sortable: true },
        };

        agGridInstance = agGrid.createGrid(gridContainer, gridOptions);
      })
      .catch(error => {
        console.error('Error loading daily grid:', error);
        document.getElementById('dm-kpi-daily-grid').innerHTML =
          '<div class="alert alert-danger m-3">Could not load daily grid</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: SYNC HEALTH (C-02, C-03, C-13, C-14)
  // ─────────────────────────────────────────────────────────────

  function loadSyncHealth() {
    return Promise.all([
      jsonFetch('/api/v1/analytics/dm-kpi/sync/status'),
      jsonFetch('/api/v1/analytics/dm-kpi/sync/latency'),
      jsonFetch('/api/v1/analytics/dm-kpi/sync/attachment-health'),
    ])
      .then(([status, latency, attachment]) => {
        // C-02: Last sync — API returns latest_run, not last_sync_run
        const lastRun = status.latest_run || {};
        const lastTime = lastRun.started_at;
        if (lastTime) {
          document.getElementById('dm-kpi-sync-last-time').textContent =
            new Date(lastTime).toLocaleString();
        } else {
          document.getElementById('dm-kpi-sync-last-time').textContent = 'Never';
        }
        const statusBadge = document.getElementById('dm-kpi-sync-last-status');
        const syncStatus = lastRun.status || 'unknown';
        statusBadge.textContent = syncStatus;
        statusBadge.className = 'badge ' + (syncStatus === 'completed' ? 'bg-success' : syncStatus === 'failed' ? 'bg-danger' : 'bg-secondary');

        // C-03: Error rate — API returns runs_7d.total/errors, error_rate_7d
        const errorRate7d = status.error_rate_7d;
        document.getElementById('dm-kpi-sync-error-rate').textContent = formatRate(errorRate7d);
        const runs7d = status.runs_7d || {};
        const errorDetail = (runs7d.errors || 0) + ' errors / ' + (runs7d.total || 0) + ' runs';
        document.getElementById('dm-kpi-sync-error-detail').textContent = errorDetail;

        // C-13: Sync latency
        document.getElementById('dm-kpi-sync-latency-p50').textContent = formatHours(latency.p50_seconds);
        document.getElementById('dm-kpi-sync-latency-p90').textContent = formatHours(latency.p90_seconds);
        document.getElementById('dm-kpi-sync-latency-p99').textContent = formatHours(latency.p99_seconds);

        showContent('dm-kpi-sync');

        // C-14: Attachment health — API returns c14.total_past_smartva/missing_attachments/rate
        const c14 = attachment.c14 || {};
        const expected = c14.total_past_smartva || 0;
        const missing = c14.missing_attachments || 0;
        const present = expected - missing;
        document.getElementById('dm-kpi-attach-expected').textContent = expected;
        document.getElementById('dm-kpi-attach-present').textContent = present;
        document.getElementById('dm-kpi-attach-missing').textContent = missing;
        document.getElementById('dm-kpi-attach-health').textContent =
          c14.rate !== null && c14.rate !== undefined ? (100 - c14.rate).toFixed(1) + '%' : '—';

        showContent('dm-kpi-attachment');
      })
      .catch(error => {
        console.error('Error loading sync health:', error);
        showError('dm-kpi-sync');
        showError('dm-kpi-attachment');
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: QUALITY GATES (C-05, C-06, C-09, C-10, C-11, C-23)
  // ─────────────────────────────────────────────────────────────

  function loadQualityGates() {
    return Promise.all([
      jsonFetch('/api/v1/analytics/dm-kpi/exclusions/rates'),
      jsonFetch('/api/v1/analytics/dm-kpi/exclusions/blocked'),
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/reviewed'),
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/upstream-changes'),
    ])
      .then(([rates, blocked, reviewed, upstream]) => {
        // C-05: Not codeable rate — API: rates.not_codeable_overall.rate
        const nc = rates.not_codeable_overall || {};
        document.getElementById('dm-kpi-not-codeable-rate').textContent =
          formatRate(nc.rate);

        // C-06: Consent refused rate — API: rates.consent_refused.rate
        const cr = rates.consent_refused || {};
        document.getElementById('dm-kpi-consent-refused-rate').textContent =
          formatRate(cr.rate);

        // C-09: % reviewed — API: reviewed.rate
        document.getElementById('dm-kpi-reviewed-rate').textContent =
          formatRate(reviewed.rate);

        // C-10: Upstream queue — API: upstream.c10_queue_count
        document.getElementById('dm-kpi-upstream-queue').textContent =
          upstream.c10_queue_count || 0;

        // C-11: Upstream rate — API: upstream.c11_rate
        document.getElementById('dm-kpi-upstream-rate').textContent =
          formatRate(upstream.c11_rate);

        // C-23: Blocked forms — API: blocked.total_blocked, blocked.breakdown
        const blockedTotal = blocked.total_blocked || 0;
        document.getElementById('dm-kpi-blocked-total').textContent = blockedTotal;

        // Blocked forms breakdown table
        if (blocked.breakdown && blocked.breakdown.length > 0) {
          const tbody = document.getElementById('dm-kpi-blocked-tbody');
          tbody.innerHTML = '';
          blocked.breakdown.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML =
              '<td>' + (item.label || item.blockage_reason) + '</td>' +
              '<td class="text-end">' + item.count + '</td>';
            tbody.appendChild(row);
          });
          document.getElementById('dm-kpi-blocked-detail').style.display = 'block';
        }

        showContent('dm-kpi-quality');
      })
      .catch(error => {
        console.error('Error loading quality gates:', error);
        showError('dm-kpi-quality');
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: BURNDOWN CHART (C-18)
  // ─────────────────────────────────────────────────────────────

  function loadBurndownChart() {
    if (!burndownData) return Promise.resolve();
    if (!burndownData.c18_burndown_available) {
      document.getElementById('dm-kpi-burndown-loading').style.display = 'none';
      document.getElementById('dm-kpi-burndown-fallback').style.display = 'block';
      const days = burndownData.c17_predicted_days;
      if (days === 'infinite' || days === Infinity) {
        document.getElementById('dm-kpi-fallback-days').textContent = '∞';
      } else if (days !== null) {
        document.getElementById('dm-kpi-fallback-days').textContent = days.toFixed(1);
      }
      return Promise.resolve();
    }

    return loadChartJs().then(Chart => {
      const achieved = burndownData.c18_achieved || [];
      const projected = burndownData.c18_projected || [];
      const dates = projected.map(p => p.date).slice(-30);

      const achievedMap = {};
      achieved.forEach(a => { achievedMap[a.date] = a.remaining_achieved; });

      const achievedData = dates.map(d => achievedMap[d] || 0);
      const projectedData = projected
        .filter(p => dates.includes(p.date))
        .map(p => p.remaining_projected);

      const ctx = document.getElementById('dm-kpi-burndown-chart').getContext('2d');
      if (chartBurndown) chartBurndown.destroy();
      chartBurndown = new Chart(ctx, {
        type: 'line',
        data: {
          labels: dates,
          datasets: [
            {
              label: 'Projected',
              data: projectedData,
              borderColor: '#0066cc',
              borderDash: [5, 5],
              fill: false,
              tension: 0.1,
              pointRadius: 0,
            },
            {
              label: 'Achieved',
              data: achievedData,
              borderColor: '#28a745',
              fill: false,
              tension: 0.1,
              pointRadius: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: {
            legend: { display: true, position: 'top' },
          },
          scales: {
            y: { beginAtZero: true, title: { display: true, text: 'Remaining Forms' } },
          },
        },
      });

      document.getElementById('dm-kpi-burndown-loading').style.display = 'none';
      document.getElementById('dm-kpi-burndown-chart').style.display = 'block';
    }).catch(error => {
      console.error('Error loading burndown chart:', error);
      document.getElementById('dm-kpi-burndown-loading').innerHTML =
        '<div class="alert alert-danger mb-0">Could not load chart</div>';
    });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: INFLOW/OUTFLOW CHART (C-19)
  // ─────────────────────────────────────────────────────────────

  function loadInflowChart() {
    return loadChartJs()
      .then(() => jsonFetch('/api/v1/analytics/dm-kpi/pipeline/inflow-outflow?days=' + dayWindow))
      .then(response => {
        const { data = [] } = response;
        const dates = data.map(d => d.date);
        const inflow = data.map(d => d.inflow || 0);
        const outflow = data.map(d => d.outflow || 0);

        const ctx = document.getElementById('dm-kpi-inflow-chart').getContext('2d');
        if (chartInflow) chartInflow.destroy();
        chartInflow = new window.Chart(ctx, {
          type: 'bar',
          data: {
            labels: dates,
            datasets: [
              {
                label: 'Inflow',
                data: inflow,
                backgroundColor: '#0066cc',
                stack: 'stack',
              },
              {
                label: 'Outflow',
                data: outflow,
                backgroundColor: '#28a745',
                stack: 'stack',
              },
            ],
          },
          options: {
            indexAxis: undefined,
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
              legend: { display: true, position: 'top' },
            },
            scales: {
              x: { stacked: true },
              y: { stacked: true, title: { display: true, text: 'Submissions' } },
            },
          },
        });

        document.getElementById('dm-kpi-inflow-loading').style.display = 'none';
        document.getElementById('dm-kpi-inflow-chart').style.display = 'block';
      })
      .catch(error => {
        console.error('Error loading inflow chart:', error);
        document.getElementById('dm-kpi-inflow-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load chart</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: PIPELINE AGING (C-07) + TIME-TO-CODE (C-08)
  // ─────────────────────────────────────────────────────────────

  function loadAgingSection() {
    return Promise.all([
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/aging'),
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/time-to-code?range=' + (dayWindow <= 7 ? '7d' : '7d')),
    ])
      .then(([aging, ttc]) => {
        document.getElementById('dm-kpi-aging-48h').textContent = (aging.gt_48h || 0).toString();
        document.getElementById('dm-kpi-aging-7d').textContent = (aging.gt_7d || 0).toString();
        document.getElementById('dm-kpi-aging-30d').textContent = (aging.gt_30d || 0).toString();

        const p50 = ttc.p50_seconds;
        if (p50) {
          document.getElementById('dm-kpi-time-to-code-p50').textContent = formatHours(p50);
        }

        showContent('dm-kpi-aging');
      })
      .catch(error => {
        console.error('Error loading aging section:', error);
        showError('dm-kpi-aging');
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: SITE BOTTLENECK (C-22)
  // ─────────────────────────────────────────────────────────────

  function loadSiteBottleneck() {
    return jsonFetch('/api/v1/analytics/dm-kpi/pipeline/site-bottleneck')
      .then(response => {
        const { sites = [] } = response;
        const tbody = document.getElementById('dm-kpi-bottleneck-tbody');
        tbody.innerHTML = '';

        sites.forEach(site => {
          const row = document.createElement('tr');
          const pctClass = site.pct_uncoded > 80 ? 'text-danger fw-bold' :
                           site.pct_uncoded > 50 ? 'text-warning' : '';
          row.innerHTML =
            '<td>' + site.site_id + '</td>' +
            '<td class="text-end ' + pctClass + '">' + (site.pct_uncoded || 0).toFixed(1) + '%</td>' +
            '<td class="text-end">' + (site.pending || 0) + '</td>';
          tbody.appendChild(row);
        });

        showContent('dm-kpi-bottleneck');
      })
      .catch(error => {
        console.error('Error loading site bottleneck:', error);
        showError('dm-kpi-bottleneck');
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: BACKLOG TREND (D-WT-03)
  // ─────────────────────────────────────────────────────────────

  function loadBacklogChart() {
    return loadChartJs()
      .then(() => jsonFetch('/api/v1/analytics/dm-kpi/pipeline/backlog-trend?days=' + dayWindow))
      .then(response => {
        const { data = [] } = response;
        const dates = data.map(d => d.date);
        const pending = data.map(d => d.pending || 0);

        const ctx = document.getElementById('dm-kpi-backlog-chart').getContext('2d');
        if (chartBacklog) chartBacklog.destroy();
        chartBacklog = new window.Chart(ctx, {
          type: 'line',
          data: {
            labels: dates,
            datasets: [
              {
                label: 'Pending',
                data: pending,
                borderColor: '#ff9800',
                fill: true,
                backgroundColor: 'rgba(255, 152, 0, 0.1)',
                tension: 0.1,
                pointRadius: 0,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
              legend: { display: true, position: 'top' },
            },
            scales: {
              y: { beginAtZero: true, title: { display: true, text: 'Pending Count' } },
            },
          },
        });

        document.getElementById('dm-kpi-backlog-loading').style.display = 'none';
        document.getElementById('dm-kpi-backlog-chart').style.display = 'block';
      })
      .catch(error => {
        console.error('Error loading backlog chart:', error);
        document.getElementById('dm-kpi-backlog-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load chart</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: LANGUAGE GAP (C-15, C-20)
  // ─────────────────────────────────────────────────────────────

  function loadLanguageGap() {
    return jsonFetch('/api/v1/analytics/dm-kpi/language/gap')
      .then(response => {
        const { languages = [] } = response;
        const tbody = document.getElementById('dm-kpi-language-tbody');
        tbody.innerHTML = '';

        languages.forEach(lang => {
          const row = document.createElement('tr');
          const daysText = lang.predicted_days_to_clear === 'infinite' || lang.predicted_days_to_clear === Infinity ? '∞'
            : lang.predicted_days_to_clear === null ? '—'
            : lang.predicted_days_to_clear.toFixed(1);

          const gapBadge = lang.gap ? '<span class="badge bg-danger ms-2">GAP</span>' : '';

          row.innerHTML =
            '<td>' + lang.language + gapBadge + '</td>' +
            '<td>' + lang.pending_count + '</td>' +
            '<td>' + lang.coders_available + '</td>' +
            '<td>' + (lang.daily_coding_rate || 0).toFixed(1) + '</td>' +
            '<td>' + daysText + '</td>';
          tbody.appendChild(row);
        });

        document.getElementById('dm-kpi-language-loading').style.display = 'none';
        document.getElementById('dm-kpi-language-table').style.display = 'table';
      })
      .catch(error => {
        console.error('Error loading language gap:', error);
        document.getElementById('dm-kpi-language-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load data</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: CODER PERFORMANCE (C-12, C-16, C-24)
  // ─────────────────────────────────────────────────────────────

  function loadCoderTable() {
    // Use burndown per-coder for C-16 rates, and coders/output for C-12/C-24
    const rangeParam = coderRange === '7d' ? '7d' : 'cumulative';

    return Promise.all([
      Promise.resolve(burndownData ? burndownData.c16_per_coder || [] : []),
      jsonFetch('/api/v1/analytics/dm-kpi/coders/output?range=' + rangeParam),
    ])
      .then(([perCoder, output]) => {
        const tbody = document.getElementById('dm-kpi-coders-tbody');
        tbody.innerHTML = '';

        // API returns per_coder array with total and by_language
        const apiCoders = output.per_coder || [];

        // Build map from API output for language info (C-24)
        const outputMap = {};
        apiCoders.forEach(c => {
          outputMap[c.coder_name] = c;
        });

        // Use burndown per-coder for rates if available, else API output
        const coders = perCoder.length > 0 ? perCoder : apiCoders;

        coders.forEach(coder => {
          const name = coder.coder_name || 'Unknown';
          const outputInfo = outputMap[name] || {};
          const coded = coderRange === '7d'
            ? (coder.coded_7d || outputInfo.total || 0)
            : (outputInfo.total || coder.coded_7d || 0);
          const rate = coder.daily_rate || 0;
          const byLang = outputInfo.by_language || {};
          const langList = Object.keys(byLang).length > 0
            ? Object.entries(byLang).map(([l, c]) => l + '(' + c + ')').join(', ')
            : '—';

          const row = document.createElement('tr');
          row.innerHTML =
            '<td>' + name + '</td>' +
            '<td>' + coded + '</td>' +
            '<td>' + rate.toFixed(1) + '</td>' +
            '<td><small>' + langList + '</small></td>';
          tbody.appendChild(row);
        });

        document.getElementById('dm-kpi-coders-loading').style.display = 'none';
        document.getElementById('dm-kpi-coders-table').style.display = 'table';
      })
      .catch(error => {
        console.error('Error loading coder table:', error);
        document.getElementById('dm-kpi-coders-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load data</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: WORKFLOW FLOWCHART (D-WF-01)
  // ─────────────────────────────────────────────────────────────

  function renderFlowchart(data) {
    var container = document.getElementById('wf-flowchart-content');
    var s = data.stages || {};
    var total = data.total_synced || 0;

    var html = '<div class="wf-flowchart">';

    // Row 1: All Synced
    html += '<div class="wf-node wf-entry">';
    html += '<div class="wf-node-label">All Synced Submissions</div>';
    html += '<div class="wf-node-count">' + total + '</div>';
    html += '</div>';

    // Row 2: Excluded at entry (left) + Eligible for Coding (trunk)
    var excEntry = s.excluded_entry || {};
    var excEntryTotal = excEntry.total || 0;
    if (excEntryTotal > 0) {
      html += '<div class="wf-connector-down"></div>';
      html += '<div class="wf-branch-row">';
      html += '<div class="wf-branch-side wf-branch-left">';
      html += '<div class="wf-node wf-terminal">';
      html += '<div class="wf-node-label">Excluded</div>';
      if (excEntry.consent_refused > 0) {
        html += '<div class="wf-excl-line"><small>Consent Refused: <strong>' + excEntry.consent_refused + '</strong></small></div>';
      }
      if (excEntry.not_codeable_dm > 0) {
        html += '<div class="wf-excl-line"><small>Not Codeable (DM): <strong>' + excEntry.not_codeable_dm + '</strong></small></div>';
      }
      html += '<div class="wf-excl-total">' + excEntryTotal + '</div>';
      html += '</div>';
      html += '</div>';
      html += '<div class="wf-branch-main">';
      html += '<div class="wf-node wf-trunk">';
      html += '<div class="wf-node-label">Eligible for Coding</div>';
      html += '<div class="wf-node-count">' + (s.eligible_for_coding || 0) + '</div>';
      html += '</div>';
      html += '</div>';
      html += '</div>';
    } else {
      html += '<div class="wf-connector-down"></div>';
      html += '<div class="wf-node wf-trunk">';
      html += '<div class="wf-node-label">Eligible for Coding</div>';
      html += '<div class="wf-node-count">' + (s.eligible_for_coding || 0) + '</div>';
      html += '</div>';
    }

    // Row 3: Uncoded breakdown
    html += '<div class="wf-connector-down"></div>';
    html += '<div class="wf-node wf-pending">';
    html += '<div class="wf-node-label">Uncoded (In Pipeline)</div>';
    html += '<div class="wf-node-count">' + (s.uncoded_eligible || 0) + '</div>';
    html += '</div>';

    // Row 4: Excluded during coding (left) + Coded (trunk)
    var excCoding = s.excluded_coding || {};
    var excCodingTotal = excCoding.not_codeable_coder || 0;
    if (excCodingTotal > 0) {
      html += '<div class="wf-connector-down"></div>';
      html += '<div class="wf-branch-row">';
      html += '<div class="wf-branch-side wf-branch-left">';
      html += '<div class="wf-node wf-terminal">';
      html += '<div class="wf-node-label">Excluded</div>';
      html += '<div class="wf-excl-line"><small>Not Codeable (Coder): <strong>' + excCoding.not_codeable_coder + '</strong></small></div>';
      html += '<div class="wf-excl-total">' + excCodingTotal + '</div>';
      html += '</div>';
      html += '</div>';
      html += '<div class="wf-branch-main">';
      html += renderCodedNode(s);
      html += '</div>';
      html += '</div>';
    } else {
      html += '<div class="wf-connector-down"></div>';
      html += renderCodedNode(s);
    }

    // Row 5: Reviewed
    if ((s.reviewed || 0) > 0 || (s.upstream_changed || 0) > 0) {
      html += '<div class="wf-connector-down"></div>';

      var hasUpstream = (s.upstream_changed || 0) > 0;
      if (hasUpstream) {
        html += '<div class="wf-branch-row">';
        html += '<div class="wf-branch-side wf-branch-left">';
        html += '<div class="wf-node wf-exception">';
        html += '<div class="wf-node-label"><small>Upstream Changed</small></div>';
        html += '<div class="wf-node-count-small">' + s.upstream_changed + '</div>';
        html += '</div>';
        html += '</div>';
        html += '<div class="wf-branch-main">';
        html += '<div class="wf-node wf-review">';
        html += '<div class="wf-node-label">Reviewed <small class="text-muted">(optional)</small></div>';
        html += '<div class="wf-node-count">' + (s.reviewed || 0) + '</div>';
        html += '</div>';
        html += '</div>';
        html += '</div>';
      } else {
        html += '<div class="wf-node wf-review">';
        html += '<div class="wf-node-label">Reviewed <small class="text-muted">(optional)</small></div>';
        html += '<div class="wf-node-count">' + (s.reviewed || 0) + '</div>';
        html += '</div>';
      }
    }

    html += '</div>';

    // Conversion summary bar
    var conv = data.conversion || {};
    html += '<div class="wf-conversion-bar mt-3">';
    html += '<span class="wf-conv-item"><strong>' + ((conv.eligible_rate || 0) * 100).toFixed(1) + '%</strong> eligible</span>';
    html += '<span class="wf-conv-item"><strong>' + ((conv.coding_rate || 0) * 100).toFixed(1) + '%</strong> coded</span>';
    html += '<span class="wf-conv-item"><strong>' + ((conv.review_rate || 0) * 100).toFixed(1) + '%</strong> reviewed</span>';
    html += '</div>';

    container.innerHTML = html;
    document.getElementById('wf-flowchart-loading').style.display = 'none';
    container.style.display = 'block';
  }

  function renderCodedNode(s) {
    var cf = s.coder_finalized || {};
    var html = '<div class="wf-node wf-coded">';
    html += '<div class="wf-node-label">Coded</div>';
    html += '<div class="wf-node-count">' + (s.coded || 0) + '</div>';
    if (cf.total > 0) {
      html += '<div class="wf-sub-phases">';
      html += '<div class="wf-sub-phase"><small>Within 24h: <strong>' + (cf.within_24h || 0) + '</strong></small></div>';
      html += '<div class="wf-sub-phase"><small>Beyond 24h: <strong>' + (cf.beyond_24h || 0) + '</strong></small></div>';
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(String(value || '')));
    return div.innerHTML;
  }

  function loadFlowchart() {
    return jsonFetch('/api/v1/analytics/dm-kpi/workflow/flowchart')
      .then(function (response) {
        renderFlowchart(response);
      })
      .catch(function (error) {
        console.error('Error loading flowchart:', error);
        document.getElementById('wf-flowchart-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load pipeline flowchart</div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: STAGNATION ALERTS (D-WF-03)
  // ─────────────────────────────────────────────────────────────

  function loadStagnationAlerts() {
    return jsonFetch('/api/v1/analytics/dm-kpi/workflow/stagnation')
      .then(function (response) {
        var alerts = response.alerts || [];
        var tbody = document.getElementById('wf-stagnation-tbody');
        tbody.innerHTML = '';

        alerts.forEach(function (alert) {
          // Skip states with no stagnation
          if (alert.alert_level === 'normal') return;

          var row = document.createElement('tr');
          var levelClass = alert.alert_level === 'critical' ? 'table-danger' :
                           alert.alert_level === 'warning' ? 'table-warning' : '';
          if (levelClass) row.className = levelClass;

          var levelBadge = alert.alert_level === 'critical' ? '<span class="badge bg-danger">Critical</span>' :
                           alert.alert_level === 'warning' ? '<span class="badge bg-warning text-dark">Warning</span>' :
                           alert.alert_level === 'info' ? '<span class="badge bg-info">Info</span>' : '';

          row.innerHTML =
            '<td>' + levelBadge + ' ' + escapeHtml(alert.label) + '</td>' +
            '<td class="text-end">' + alert.total + '</td>' +
            '<td class="text-end">' + (alert.gt_48h || 0) + '</td>' +
            '<td class="text-end">' + (alert.gt_7d || 0) + '</td>' +
            '<td>' + formatHours(alert.p50_age_hours * 3600) + '</td>';
          tbody.appendChild(row);
        });

        // Summary badge
        var summaryEl = document.getElementById('wf-stagnation-summary');
        if (response.total_stagnant_gt_7d > 0) {
          summaryEl.textContent = response.total_stagnant_gt_7d + ' stale >7d';
          summaryEl.className = 'badge bg-danger';
        } else if (response.total_stagnant_gt_48h > 0) {
          summaryEl.textContent = response.total_stagnant_gt_48h + ' stale >48h';
          summaryEl.className = 'badge bg-warning text-dark';
        } else {
          summaryEl.textContent = 'No alerts';
          summaryEl.className = 'badge bg-success';
        }
        summaryEl.style.display = 'inline';

        document.getElementById('wf-stagnation-loading').style.display = 'none';
        document.getElementById('wf-stagnation-content').style.display = 'block';
      })
      .catch(function (error) {
        console.error('Error loading stagnation alerts:', error);
        document.getElementById('wf-stagnation-loading').innerHTML =
          '<div class="alert alert-danger mb-0 py-2"><small>Could not load stagnation data</small></div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: STATE VELOCITY (D-WF-02)
  // ─────────────────────────────────────────────────────────────

  function loadStateVelocity() {
    return jsonFetch('/api/v1/analytics/dm-kpi/workflow/state-velocity?days=30')
      .then(function (response) {
        var states = response.states || [];
        var rangeEl = document.getElementById('wf-velocity-range');
        rangeEl.textContent = 'Last ' + response.range_days + ' days';

        var tbody = document.getElementById('wf-velocity-tbody');
        tbody.innerHTML = '';

        states.forEach(function (s) {
          var row = document.createElement('tr');
          // Highlight slow states
          var rowClass = s.p50_hours > 72 ? 'table-warning' : '';
          if (rowClass) row.className = rowClass;

          row.innerHTML =
            '<td>' + escapeHtml(s.label) + '</td>' +
            '<td class="text-end">' + s.transition_count + '</td>' +
            '<td class="text-end">' + s.avg_hours + 'h</td>' +
            '<td class="text-end">' + s.p50_hours + 'h</td>' +
            '<td class="text-end">' + s.p90_hours + 'h</td>';
          tbody.appendChild(row);
        });

        document.getElementById('wf-velocity-loading').style.display = 'none';
        document.getElementById('wf-velocity-content').style.display = 'block';
      })
      .catch(function (error) {
        console.error('Error loading state velocity:', error);
        document.getElementById('wf-velocity-loading').innerHTML =
          '<div class="alert alert-danger mb-0 py-2"><small>Could not load velocity data</small></div>';
      });
  }

  // ─────────────────────────────────────────────────────────────
  // SECTION: DAILY TRANSITIONS (D-WF-04)
  // ─────────────────────────────────────────────────────────────

  var chartTransitions = null;

  var PHASE_COLORS = {
    intake: '#6c757d',
    preprocessing: '#17a2b8',
    coding: '#ffc107',
    finalization: '#28a745',
    review: '#0066cc',
    exception: '#fd7e14',
    exclusion: '#dc3545',
  };

  function loadDailyTransitions() {
    return loadChartJs()
      .then(function () {
        return jsonFetch('/api/v1/analytics/dm-kpi/workflow/daily-transitions?days=' + dayWindow);
      })
      .then(function (response) {
        var days = response.days || [];
        var dates = days.map(function (d) { return d.date; });

        // Collect all unique states across days
        var allStates = {};
        days.forEach(function (d) {
          Object.keys(d.transitions || {}).forEach(function (s) {
            if (!allStates[s]) allStates[s] = PHASE_COLORS[STATE_PHASES[s] || 'intake'] || '#6c757d';
          });
        });

        var stateOrder = ['consent_refused', 'attachment_sync_pending', 'screening_pending',
          'smartva_pending', 'ready_for_coding', 'coding_in_progress', 'coder_step1_saved',
          'coder_finalized', 'reviewer_eligible', 'reviewer_coding_in_progress',
          'reviewer_finalized', 'finalized_upstream_changed',
          'not_codeable_by_coder', 'not_codeable_by_data_manager'];

        var datasets = stateOrder
          .filter(function (s) { return allStates[s]; })
          .map(function (state) {
            return {
              label: STATE_LABELS[state] || state,
              data: dates.map(function (date) {
                var day = days.find(function (d) { return d.date === date; });
                return day && day.transitions ? (day.transitions[state] || 0) : 0;
              }),
              backgroundColor: allStates[state],
              stack: 'stack',
            };
          });

        var ctx = document.getElementById('wf-transitions-chart').getContext('2d');
        if (chartTransitions) chartTransitions.destroy();
        chartTransitions = new window.Chart(ctx, {
          type: 'bar',
          data: { labels: dates, datasets: datasets },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 12, font: { size: 10 } } } },
            scales: {
              x: { stacked: true },
              y: { stacked: true, title: { display: true, text: 'Transitions' } },
            },
          },
        });

        document.getElementById('wf-transitions-loading').style.display = 'none';
        document.getElementById('wf-transitions-chart').style.display = 'block';
      })
      .catch(function (error) {
        console.error('Error loading daily transitions:', error);
        document.getElementById('wf-transitions-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load transitions chart</div>';
      });
  }

  // State label and phase lookups for JS
  var STATE_LABELS = {
    screening_pending: 'DM Screening',
    attachment_sync_pending: 'Attachment Sync',
    smartva_pending: 'SmartVA Processing',
    ready_for_coding: 'Ready for Coding',
    coding_in_progress: 'Coding in Progress',
    coder_step1_saved: 'Step 1 Saved',
    coder_finalized: 'Coder Finalized',
    reviewer_eligible: 'Reviewer Eligible',
    reviewer_coding_in_progress: 'Reviewer in Progress',
    reviewer_finalized: 'Reviewer Finalized',
    finalized_upstream_changed: 'Upstream Changed',
    not_codeable_by_coder: 'Not Codeable (Coder)',
    not_codeable_by_data_manager: 'Not Codeable (DM)',
    consent_refused: 'Consent Refused',
  };

  var STATE_PHASES = {
    screening_pending: 'intake',
    attachment_sync_pending: 'intake',
    smartva_pending: 'preprocessing',
    ready_for_coding: 'coding',
    coding_in_progress: 'coding',
    coder_step1_saved: 'coding',
    coder_finalized: 'finalization',
    reviewer_eligible: 'review',
    reviewer_coding_in_progress: 'review',
    reviewer_finalized: 'review',
    finalized_upstream_changed: 'exception',
    not_codeable_by_coder: 'exclusion',
    not_codeable_by_data_manager: 'exclusion',
    consent_refused: 'exclusion',
  };

  // ─────────────────────────────────────────────────────────────
  // WINDOW SELECTOR (7/30/90 days)
  // ─────────────────────────────────────────────────────────────

  function onWindowChange(days) {
    dayWindow = days;

    // Update button states
    document.querySelectorAll('[data-window]').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.window) === days);
      btn.classList.toggle('btn-primary', parseInt(btn.dataset.window) === days);
      btn.classList.toggle('btn-outline-primary', parseInt(btn.dataset.window) !== days);
    });

    // Reload time-series sections affected by day window
    Promise.all([loadInflowChart(), loadBacklogChart()]);
  }

  // ─────────────────────────────────────────────────────────────
  // CODER RANGE SELECTOR (7d / cumulative)
  // ─────────────────────────────────────────────────────────────

  function onCoderRangeChange(range) {
    coderRange = range;

    // Update button states
    document.querySelectorAll('[data-coder-range]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.coderRange === range);
      btn.classList.toggle('btn-secondary', btn.dataset.coderRange === range);
      btn.classList.toggle('btn-outline-secondary', btn.dataset.coderRange !== range);
    });

    loadCoderTable();
  }

  // ─────────────────────────────────────────────────────────────
  // REFRESH: MV refresh + dashboard reload
  // ─────────────────────────────────────────────────────────────

  function onRefreshDashboard() {
    var btn = document.getElementById('dm-kpi-refresh-btn');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Refreshing...';

    // Single endpoint: recompute KPIs + refresh MVs + bust cache
    fetch('/api/v1/analytics/dm-kpi/refresh', {
      method: 'POST',
      headers: {
        'X-CSRFToken': CSRF,
        'Content-Type': 'application/json',
      },
    })
      .then(function (response) {
        if (!response.ok) throw new Error('Refresh failed: HTTP ' + response.status);
        return response.json();
      })
      .then(function () {
        // Reload the entire dashboard with fresh data
        return loadOverviewCards()
          .then(function () {
            return Promise.all([
              loadDailyGrid(),
              loadFlowchart(),
              loadStagnationAlerts(),
              loadStateVelocity(),
              loadDailyTransitions(),
              loadSyncHealth(),
              loadQualityGates(),
              loadBurndownChart(),
              loadInflowChart(),
              loadAgingSection(),
              loadSiteBottleneck(),
              loadBacklogChart(),
              loadLanguageGap(),
              loadCoderTable(),
            ]);
          });
      })
      .then(function () {
        btn.innerHTML = '<i class="fa-solid fa-check me-1"></i>Done';
        setTimeout(function () {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-arrows-rotate me-1"></i>Refresh';
        }, 2000);
      })
      .catch(function (error) {
        console.error('Dashboard refresh error:', error);
        btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-1"></i>Error';
        setTimeout(function () {
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-arrows-rotate me-1"></i>Refresh';
        }, 3000);
      });
  }

  // ─────────────────────────────────────────────────────────────
  // INIT
  // ─────────────────────────────────────────────────────────────

  function init() {
    // Wire up day-window buttons
    document.querySelectorAll('[data-window]').forEach(btn => {
      btn.addEventListener('click', () => onWindowChange(parseInt(btn.dataset.window)));
      if (parseInt(btn.dataset.window) === dayWindow) {
        btn.classList.add('active', 'btn-primary');
        btn.classList.remove('btn-outline-primary');
      }
    });

    // Wire up coder-range buttons
    document.querySelectorAll('[data-coder-range]').forEach(btn => {
      btn.addEventListener('click', () => onCoderRangeChange(btn.dataset.coderRange));
      if (btn.dataset.coderRange === coderRange) {
        btn.classList.add('active', 'btn-secondary');
        btn.classList.remove('btn-outline-secondary');
      }
    });

    // Wire up refresh button
    var refreshBtn = document.getElementById('dm-kpi-refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', onRefreshDashboard);
    }

    // Load overview cards first (needed by other sections)
    loadOverviewCards()
      .then(() => {
        // Then load everything else in parallel
        return Promise.all([
          loadDailyGrid(),
          loadFlowchart(),
          loadStagnationAlerts(),
          loadStateVelocity(),
          loadDailyTransitions(),
          loadSyncHealth(),
          loadQualityGates(),
          loadBurndownChart(),
          loadInflowChart(),
          loadAgingSection(),
          loadSiteBottleneck(),
          loadBacklogChart(),
          loadLanguageGap(),
          loadCoderTable(),
        ]);
      })
      .catch(error => console.error('Dashboard init error:', error));
  }

  // ─────────────────────────────────────────────────────────────
  // START
  // ─────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', init);
})();
