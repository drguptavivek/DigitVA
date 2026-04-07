/**
 * DM KPI Dashboard — Real-time data manager analytics
 * Fetches from /api/v1/analytics/dm-kpi/* endpoints and renders charts/tables
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
  let burndownData = null;  // shared cache for overview cards + burndown chart
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

  // ─────────────────────────────────────────────────────────────
  // SECTION LOADERS
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
        if (daysVal === Infinity) {
          document.getElementById('kpi-days-value').textContent = '∞';
        } else if (daysVal === null) {
          document.getElementById('kpi-days-value').textContent = '—';
        } else {
          document.getElementById('kpi-days-value').textContent = daysVal.toFixed(1);
        }

        document.getElementById('kpi-utilization-value').textContent = (utilization.rate || 0).toFixed(1) + '%';

        // Show content, hide spinners
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

        const gridContainer = document.getElementById('dm-kpi-daily-grid');
        const gridOptions = {
          columnDefs: [
            { field: 'date', headerName: 'Date', width: 100, sort: 'desc' },
            { field: 'new', headerName: 'New', width: 80, type: 'rightAligned' },
            { field: 'updated', headerName: 'Updated', width: 80, type: 'rightAligned' },
            { field: 'coded', headerName: 'Coded', width: 80, type: 'rightAligned' },
            { field: 'pending', headerName: 'Pending', width: 80, type: 'rightAligned' },
            { field: 'consent_refused', headerName: 'Consent Refused', width: 110, type: 'rightAligned' },
          ],
          rowData: gridData,
          domLayout: 'fill',
          defaultColDef: { resizable: false, sortable: true },
        };

        agGridInstance = agGrid.createGrid(gridContainer, gridOptions);
      })
      .catch(error => {
        console.error('Error loading daily grid:', error);
        document.getElementById('dm-kpi-daily-grid').innerHTML =
          '<div class="alert alert-danger m-3">Could not load daily grid</div>';
      });
  }

  function loadBurndownChart() {
    if (!burndownData) return Promise.resolve();
    if (!burndownData.c18_burndown_available) {
      document.getElementById('dm-kpi-burndown-loading').style.display = 'none';
      document.getElementById('dm-kpi-burndown-fallback').style.display = 'block';
      const days = burndownData.c17_predicted_days;
      if (days === Infinity) {
        document.getElementById('dm-kpi-fallback-days').textContent = '∞';
      } else if (days !== null) {
        document.getElementById('dm-kpi-fallback-days').textContent = days.toFixed(1);
      }
      return Promise.resolve();
    }

    return loadChartJs().then(Chart => {
      const achieved = burndownData.c18_achieved || [];
      const projected = burndownData.c18_projected || [];
      const dates = projected.map(p => p.date).slice(-30);  // limit to 30 points

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

  function loadInflowChart() {
    return loadChartJs()
      .then(() => jsonFetch(`/api/v1/analytics/dm-kpi/pipeline/inflow-outflow?days=${dayWindow}`))
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

  function loadAgingSection() {
    return Promise.all([
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/aging'),
      jsonFetch('/api/v1/analytics/dm-kpi/pipeline/time-to-code'),
    ])
      .then(([aging, ttc]) => {
        document.getElementById('dm-kpi-aging-48h').textContent = (aging.gt_48h || 0).toString();
        document.getElementById('dm-kpi-aging-7d').textContent = (aging.gt_7d || 0).toString();
        document.getElementById('dm-kpi-aging-30d').textContent = (aging.gt_30d || 0).toString();

        const p50 = ttc.p50_seconds;
        if (p50) {
          const hours = Math.round(p50 / 3600);
          document.getElementById('dm-kpi-time-to-code-p50').textContent = `${hours}h`;
        }

        document.getElementById('dm-kpi-aging-loading').style.display = 'none';
        document.getElementById('dm-kpi-aging-content').style.display = 'block';
      })
      .catch(error => {
        console.error('Error loading aging section:', error);
        document.getElementById('dm-kpi-aging-loading').innerHTML =
          '<div class="alert alert-danger mb-0">Could not load data</div>';
      });
  }

  function loadBacklogChart() {
    return loadChartJs()
      .then(() => jsonFetch(`/api/v1/analytics/dm-kpi/pipeline/backlog-trend?days=90`))
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

  function loadLanguageGap() {
    return jsonFetch('/api/v1/analytics/dm-kpi/language/gap')
      .then(response => {
        const { languages = [] } = response;
        const tbody = document.getElementById('dm-kpi-language-tbody');
        tbody.innerHTML = '';

        languages.forEach(lang => {
          const row = document.createElement('tr');
          const daysText = lang.predicted_days_to_clear === Infinity ? '∞'
            : lang.predicted_days_to_clear === null ? '—'
            : lang.predicted_days_to_clear.toFixed(1);

          const gapBadge = lang.gap ? '<span class="badge bg-danger ms-2">GAP</span>' : '';

          row.innerHTML = `
            <td>${lang.language}${gapBadge}</td>
            <td>${lang.pending_count}</td>
            <td>${lang.coders_available}</td>
            <td>${lang.daily_coding_rate.toFixed(1)}</td>
            <td>${daysText}</td>
          `;
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

  function loadCoderTable() {
    if (!burndownData || !burndownData.c16_per_coder) return Promise.resolve();

    const coders = burndownData.c16_per_coder || [];
    const tbody = document.getElementById('dm-kpi-coders-tbody');
    tbody.innerHTML = '';

    coders.forEach(coder => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${coder.coder_name || 'Unknown'}</td>
        <td>${coder.coded_7d}</td>
        <td>${coder.daily_rate.toFixed(1)}</td>
      `;
      tbody.appendChild(row);
    });

    document.getElementById('dm-kpi-coders-loading').style.display = 'none';
    document.getElementById('dm-kpi-coders-table').style.display = 'table';

    return Promise.resolve();
  }

  // ─────────────────────────────────────────────────────────────
  // WINDOW SELECTOR
  // ─────────────────────────────────────────────────────────────

  function onWindowChange(days) {
    dayWindow = days;

    // Update button states
    document.querySelectorAll('[data-window]').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.window) === days);
      btn.classList.toggle('btn-primary', parseInt(btn.dataset.window) === days);
      btn.classList.toggle('btn-outline-primary', parseInt(btn.dataset.window) !== days);
    });

    // Reload time-series sections
    Promise.all([loadInflowChart(), loadBacklogChart()]);
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

    // Load overview cards first (needed by other sections)
    loadOverviewCards()
      .then(() => {
        // Then load everything else in parallel
        return Promise.all([
          loadDailyGrid(),
          loadBurndownChart(),
          loadInflowChart(),
          loadAgingSection(),
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
