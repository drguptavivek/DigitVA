(function () {
  'use strict';

  // HTMX evaluates this static script for every swapped fragment. Keep one
  // manager and one set of document listeners for the page.
  if (window.DigitvaEctAssessment && window.DigitvaEctAssessment.version === 1) {
    window.DigitvaEctAssessment.boot();
    return;
  }

  var RELEASE = '2026-01';
  var LANGUAGE = 'en';
  var stateByRoot = new WeakMap();
  var nextInstance = 0;

  function text(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function setStatus(element, message, kind) {
    if (!element) return;
    element.textContent = message || '';
    element.className = 'digitva-ect-status small';
    if (kind === 'error') element.classList.add('text-danger');
    if (kind === 'success') element.classList.add('text-success');
    if (kind === 'muted') element.classList.add('text-muted');
  }

  function fieldLabel(select) {
    var label = document.querySelector('label[for="' + select.id + '"]');
    if (label) {
      var value = text(Array.prototype.filter.call(label.childNodes, function (node) {
        return node.nodeType === Node.TEXT_NODE;
      }).map(function (node) { return node.textContent; }).join(' '));
      if (value) return value.replace(/\s+/g, ' ');
    }
    return select.id.replace(/-select$/, '').replace(/-/g, ' ');
  }

  function hiddenInput(select) {
    var id = select.dataset.icdHidden;
    return id ? document.getElementById(id) : null;
  }

  function select2Container(select) {
    var sibling = select.nextElementSibling;
    return sibling && sibling.classList.contains('select2-container') ? sibling : null;
  }

  function setIcd11Visibility(state) {
    var isIcd11 = state.root.dataset.icdClassification === 'icd11';
    state.fields.forEach(function (entry) {
      var select = entry.select;
      var container = select2Container(select);
      select.hidden = isIcd11;
      if (container) container.hidden = isIcd11;
      entry.control.hidden = !isIcd11;
    });
    state.panel.hidden = !isIcd11 || !state.activeField;
    if (!isIcd11) state.activeField = null;
  }

  function syncCurrentValue(entry) {
    var hidden = hiddenInput(entry.select);
    var value = hidden && text(hidden.value);
    if (!value || text(entry.status.textContent)) return;
    entry.status.textContent = 'Current selection: ' + value;
    entry.status.className = 'digitva-ect-field-status small text-muted';
  }

  function createPanel(state) {
    var panel = document.createElement('section');
    panel.className = 'digitva-ect-panel';
    panel.hidden = true;
    panel.setAttribute('aria-live', 'polite');

    var heading = document.createElement('h3');
    heading.className = 'h6 mb-2';
    heading.textContent = 'WHO ICD-11 Coding Tool';
    panel.appendChild(heading);

    var hint = document.createElement('p');
    hint.className = 'small text-muted mb-2';
    hint.textContent = 'Search indexed terms, inspect details and postcoordination, then select the complete WHO code expression.';
    panel.appendChild(hint);

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'ctw-input form-control';
    input.autocomplete = 'off';
    input.setAttribute('data-ctw-ino', state.ino);
    input.setAttribute('aria-label', 'Search WHO ICD-11');
    panel.appendChild(input);

    var windowElement = document.createElement('div');
    windowElement.className = 'ctw-window';
    windowElement.setAttribute('data-ctw-ino', state.ino);
    panel.appendChild(windowElement);

    var status = document.createElement('p');
    status.className = 'digitva-ect-status small text-muted';
    panel.appendChild(status);

    var attribution = document.createElement('p');
    attribution.className = 'small text-muted mb-0';
    attribution.textContent = 'WHO ICD-11 Embedded Coding Tool 1.8, MMS ' + RELEASE + ' English.';
    panel.appendChild(attribution);

    state.heading = heading;
    state.input = input;
    state.panel = panel;
    state.status = status;
    state.root.insertAdjacentElement('afterend', panel);
  }

  function renderSelected(entry, value) {
    entry.status.textContent = 'WHO selection: ' + value;
    entry.status.className = 'digitva-ect-field-status small text-success';
    var select = entry.select;
    if (window.jQuery) {
      var $select = window.jQuery(select);
      var option = new Option(value, value, true, true);
      $select.find('option').remove();
      $select.append(option).trigger('change');
    }
  }

  function checkSelection(state, entry, entity) {
    var code = text(entity && entity.code);
    var selectedText = text(entity && entity.selectedText) || text(entity && entity.title);
    if (!code) {
      setStatus(state.status, 'WHO returned no complete code expression. Choose a coded entity or postcoordinated expression.', 'error');
      return;
    }
    var sequence = ++state.selectionSequence;
    setStatus(state.status, 'Checking this WHO selection against DigitVA policy...', 'muted');
    fetch(state.selectionCheckUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': state.csrf
      },
      body: JSON.stringify({ code: code, selectedText: selectedText })
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) throw new Error(data.error || 'DigitVA could not validate this WHO selection.');
          if (data.valid === false || data.allowed === false) {
            throw new Error(data.error || 'This WHO selection is not selectable for this death.');
          }
          return data;
        });
      })
      .then(function (data) {
        if (sequence !== state.selectionSequence || state.activeField !== entry) return;
        var approvedValue = text(data && data.value);
        if (!approvedValue) throw new Error('DigitVA returned no approved ICD-11 value.');
        var hidden = hiddenInput(entry.select);
        if (hidden) hidden.value = approvedValue;
        renderSelected(entry, approvedValue);
        setStatus(state.status, 'Selection accepted. The complete WHO code expression will be saved with this field.', 'success');
      })
      .catch(function (error) {
        if (sequence !== state.selectionSequence || state.activeField !== entry) return;
        setStatus(state.status, error.message || 'WHO selection validation failed.', 'error');
      });
  }

  function configureAndBind(state) {
    if (state.configured) return Promise.resolve();
    if (!window.ECT || !window.ECT.Handler) {
      return Promise.reject(new Error('WHO Embedded Coding Tool assets are unavailable.'));
    }
    setStatus(state.status, 'Connecting to the local WHO ICD-11 API...', 'muted');
    var probeUrl = state.apiUrl.replace(/\/$/, '') +
      '/icd/release/11/' + RELEASE + '/mms/search?q=diabetes';
    return fetch(probeUrl, {
      credentials: 'same-origin',
      headers: {
        'API-Version': 'v2',
        'Accept-Language': LANGUAGE,
        'Accept': 'application/json'
      }
    })
      .then(function (response) {
        if (!response.ok) throw new Error('The local WHO ICD-11 API is unavailable (' + response.status + ').');
        ECT.Handler.configure({
          apiServerUrl: state.apiUrl,
          apiSecured: false,
          source: 'mms',
          minorVersion: RELEASE,
          language: LANGUAGE,
          simplifiedMode: false,
          autoBind: false
        }, {
          selectedEntityFunction: function (entity) {
            if (state.activeField) checkSelection(state, state.activeField, entity || {});
          }
        });
        state.configured = true;
        return ECT.Handler.bind(state.ino);
      })
      .catch(function (error) {
        setStatus(state.status, error.message || 'The WHO ICD-11 API could not be reached.', 'error');
        throw error;
      });
  }

  function activateField(state, entry) {
    state.activeField = entry;
    state.panel.hidden = false;
    state.heading.textContent = 'WHO ICD-11 Coding Tool — ' + fieldLabel(entry.select);
    setStatus(state.status, 'Loading the WHO Coding Tool...', 'muted');
    setIcd11Visibility(state);
    configureAndBind(state).then(function () {
      if (state.activeField === entry) {
        setStatus(state.status, 'Type a diagnosis or search term, then inspect the WHO result details.', 'muted');
        state.input.focus();
      }
    }).catch(function () {});
  }

  function init(root) {
    if (!root || !root.dataset.icd11WhoApiUrl) return;
    var state = stateByRoot.get(root);
    var fields = Array.prototype.slice.call(document.querySelectorAll('select[data-icd-ect]'));
    if (!fields.length) return;
    if (!state) {
      state = {
        root: root,
        apiUrl: root.dataset.icd11WhoApiUrl,
        selectionCheckUrl: root.dataset.icd11SelectionCheckUrl,
        csrf: root.dataset.icd11Csrf || '',
        fields: [],
        activeField: null,
        configured: false,
        selectionSequence: 0,
        ino: 'digitva-assessment-' + (++nextInstance)
      };
      stateByRoot.set(root, state);
      createPanel(state);
    }
    state.fields = fields.map(function (select) {
      var existing = state.fields.find(function (entry) { return entry.select === select; });
      if (existing) return existing;
      var control = document.createElement('button');
      control.type = 'button';
      control.className = 'btn btn-sm btn-outline-primary digitva-ect-open';
      control.textContent = 'Search with WHO ICD-11 Coding Tool';
      control.addEventListener('click', function () { activateField(state, entry); });
      var status = document.createElement('div');
      status.className = 'digitva-ect-field-status small';
      select.insertAdjacentElement('afterend', control);
      control.insertAdjacentElement('afterend', status);
      var entry = { select: select, control: control, status: status };
      syncCurrentValue(entry);
      return entry;
    });
    // The assessment templates populate saved values during delayed Select2
    // initialisation. Pick those values up without overwriting a WHO pick.
    state.fields.forEach(syncCurrentValue);
    setIcd11Visibility(state);
  }

  function boot() {
    document.querySelectorAll('[data-icd11-who-api-url]').forEach(init);
  }

  window.DigitvaEctAssessment = { init: init, boot: boot, version: 1 };
  document.addEventListener('DOMContentLoaded', boot);
  document.body.addEventListener('htmx:afterSwap', function () { window.setTimeout(boot, 150); });
  document.body.addEventListener('digitva:icd-classification-change', function (event) {
    var state = stateByRoot.get(event.detail && event.detail.root);
    if (state) {
      state.activeField = null;
      state.fields.forEach(function (entry) {
        entry.status.textContent = '';
        entry.status.className = 'digitva-ect-field-status small';
      });
      setStatus(state.status, '', 'muted');
      setIcd11Visibility(state);
    }
  });
  window.setTimeout(boot, 0);
}());
