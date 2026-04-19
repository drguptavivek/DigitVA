(function () {
  'use strict';

  const config = window.DM_DASHBOARD_CONFIG || {};
  const MERMAID_SRC = config.mermaidSrc || '';
  let mermaidReady = false;
  let mermaidLoader = null;
  let workflowCounts = {};
  const WORKFLOW_NODE_STATE_MAP = {
    CR: 'consent_refused',
    SP: 'screening_pending',
    ASP: 'attachment_sync_pending',
    RFC: 'ready_for_coding',
    NCDM: 'not_codeable_by_data_manager',
    SVP: 'smartva_pending',
    CIP: 'coding_in_progress',
    CSS: 'coder_step1_saved',
    NCC: 'not_codeable_by_coder',
    CF: 'coder_finalized',
    RE: 'reviewer_eligible',
    RCI: 'reviewer_coding_in_progress',
    RF: 'reviewer_finalized',
    RVK: 'finalized_upstream_changed',
  };

  function loadMermaid() {
    if (window.mermaid) {
      return Promise.resolve(window.mermaid);
    }
    if (mermaidLoader) {
      return mermaidLoader;
    }
    mermaidLoader = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = MERMAID_SRC;
      script.async = true;
      script.onload = () => resolve(window.mermaid);
      script.onerror = () => reject(new Error('Failed to load Mermaid'));
      document.head.appendChild(script);
    });
    return mermaidLoader;
  }

  function buildChartDef() {
    const count = state => (workflowCounts[state] ?? 0).toLocaleString();
    return `flowchart TD
    ODK(["🔄 ODK Sync"])

    subgraph intake ["Intake / Gate"]
      direction LR
      CR["Consent Refused\n(${count('consent_refused')})"]
      SP["Screening Pending\n(${count('screening_pending')})"]
      ASP["Attachment Sync Queue\n(${count('attachment_sync_pending')})"]
      RFC["Ready for Coding\n(${count('ready_for_coding')})"]
      NCDM["Not Codeable — DM\n(${count('not_codeable_by_data_manager')})"]
    end

    subgraph automation ["SmartVA Automation"]
      SVP["SmartVA Queue\n(${count('smartva_pending')})"]
    end

    subgraph coding ["Coder Pipeline"]
      direction LR
      CIP["Coding In Progress\n(${count('coding_in_progress')})"]
      CSS["Step 1 Saved\n(${count('coder_step1_saved')})"]
      NCC["Not Codeable — Coder\n(${count('not_codeable_by_coder')})"]
    end

    subgraph review ["Review Track"]
      direction LR
      RE["Reviewer Eligible\n(${count('reviewer_eligible')})"]
      RCI["Reviewer Coding\n(${count('reviewer_coding_in_progress')})"]
      RF["Reviewer Finalized\n(${count('reviewer_finalized')})"]
    end

    CF(["✅ Coder Finalized\n(${count('coder_finalized')})"])
    RVK(["⚠️ Upstream Changed\n(${count('finalized_upstream_changed')})"])

    ODK -->|"no / missing consent"| CR
    ODK -->|"consent valid, DM screening"| SP
    SP -->|"passes screening"| ASP
    SP -->|"DM flags"| NCDM
    CR -.->|"consent corrected in ODK"| ASP
    ASP -->|"attachments synced"| SVP
    ASP -->|"DM flags"| NCDM
    RFC -->|"DM flags"| NCDM
    RFC -->|"coder allocated"| CIP
    SVP -->|"SmartVA complete"| RFC

    CIP -->|"step 1 saved"| CSS
    CIP -->|"not codeable"| NCC
    CIP -->|"finalize COD"| CF
    CSS -->|"continue"| CIP
    CSS -->|"finalize COD"| CF

    NCC -->|"DM overrides"| RFC
    NCC -->|"DM confirms"| NCDM

    CF -->|"reviewer track"| RE
    CF -->|"ODK data changed"| RVK
    RE -->|"reviewer allocated"| RCI
    RCI -->|"reviewer finalized"| RF
    RF -->|"ODK data changed"| RVK
    RVK -.->|"accept — recode"| RFC
    RVK -.->|"reject — restore"| CF

    click CR __dm_workflow_click
    click SP __dm_workflow_click
    click ASP __dm_workflow_click
    click RFC __dm_workflow_click
    click NCDM __dm_workflow_click
    click SVP __dm_workflow_click
    click CIP __dm_workflow_click
    click CSS __dm_workflow_click
    click NCC __dm_workflow_click
    click CF __dm_workflow_click
    click RE __dm_workflow_click
    click RCI __dm_workflow_click
    click RF __dm_workflow_click
    click RVK __dm_workflow_click

    style CR   fill:#fff7ed,stroke:#ea580c,color:#9a3412
    style SP   fill:#f1f5f9,stroke:#64748b,color:#334155
    style ASP  fill:#eef2ff,stroke:#6366f1,color:#312e81
    style RFC  fill:#eff6ff,stroke:#3b82f6,color:#1e3a8a
    style NCDM fill:#fef3c7,stroke:#d97706,color:#78350f
    style SVP  fill:#ecfeff,stroke:#0891b2,color:#0e4f63
    style CIP  fill:#fefce8,stroke:#ca8a04,color:#713f12
    style CSS  fill:#fef9c3,stroke:#ca8a04,color:#713f12
    style NCC  fill:#fef3c7,stroke:#d97706,color:#78350f
    style CF   fill:#d1fae5,stroke:#059669,color:#065f46
    style RE   fill:#d1fae5,stroke:#047857,color:#064e3b
    style RCI  fill:#a7f3d0,stroke:#047857,color:#064e3b
    style RF   fill:#6ee7b7,stroke:#065f46,color:#064e3b
    style RVK  fill:#fdf4ff,stroke:#9333ea,color:#581c87
`;
  }

  function renderChart() {
    const container = document.getElementById('dm-mermaid-container');
    if (!container || !window.mermaid) return;
    const renderId = 'dm-workflow-svg-' + Date.now();
    window.mermaid.render(renderId, buildChartDef())
      .then(({ svg }) => {
        container.innerHTML = svg;
        const svgEl = container.querySelector('svg');
        if (svgEl) {
          svgEl.removeAttribute('width');
          svgEl.style.maxWidth = '100%';
          svgEl.style.height = 'auto';
        }
      })
      .catch(err => {
        container.innerHTML = `<p class="text-danger small">Flowchart render error: ${err.message}</p>`;
      });
  }

  function initMermaid() {
    if (mermaidReady) return;
    loadMermaid()
      .then(mermaid => {
        if (mermaidReady) return;
        mermaidReady = true;
        mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          flowchart: { curve: 'basis', useMaxWidth: true },
          securityLevel: 'loose',
        });
        renderChart();
      })
      .catch(err => {
        const container = document.getElementById('dm-mermaid-container');
        if (container) {
          container.innerHTML = `<p class="text-danger small">Flowchart render error: ${err.message}</p>`;
        }
      });
  }

  window.__dm_update_workflow_counts = function (counts) {
    workflowCounts = counts || {};
    const collapseEl = document.getElementById('dm-workflow-chart-body');
    if (collapseEl && collapseEl.classList.contains('show')) {
      renderChart();
    }
  };

  window.__dm_workflow_click = function (nodeId) {
    const state = WORKFLOW_NODE_STATE_MAP[nodeId];
    if (!state) return;
    if (window.DM_DASHBOARD_API && typeof window.DM_DASHBOARD_API.applyWorkflowFilter === 'function') {
      window.DM_DASHBOARD_API.applyWorkflowFilter(state);
    }
    const collapseEl = document.getElementById('dm-workflow-chart-body');
    if (collapseEl) {
      bootstrap.Collapse.getOrCreateInstance(collapseEl).hide();
    }
    const table = document.getElementById('dm-table');
    if (table) {
      table.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('dm-workflow-chart-toggle');
    const collapseEl = document.getElementById('dm-workflow-chart-body');
    if (!toggleBtn || !collapseEl) return;

    let rendered = false;
    collapseEl.addEventListener('show.bs.collapse', () => {
      const chevron = toggleBtn.querySelector('#dm-workflow-chevron');
      if (chevron) {
        chevron.style.transform = 'rotate(180deg)';
      }
      if (!rendered) {
        rendered = true;
        initMermaid();
      }
    });
    collapseEl.addEventListener('hide.bs.collapse', () => {
      const chevron = toggleBtn.querySelector('#dm-workflow-chevron');
      if (chevron) {
        chevron.style.transform = 'rotate(0deg)';
      }
    });
  });
})();
