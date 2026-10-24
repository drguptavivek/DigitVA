// Masked ICD-11 Step 2 host (digitva-0n3): confirms the final underlying
// cause with the shared ICD-11 picker. No certificate and no Process; the
// Step 1 DORIS run is shown read-only through renderSummary. The server
// derives which choice was used, so nothing here reports provenance.
import { createIcd11Picker, attachAutoSearch } from './digitva_icd11_picker.js?v=4';
import { renderSummary } from './doris_result_summary.js?v=6';

(function () {
  'use strict';

  var ENDPOINTS = {
    terms: 'termsUrl', codeinfo: 'codeinfoUrl', 'selection-check': 'selectionUrl',
    postcoordination: 'postcoordinationUrl', 'postcoordination-options': 'postcoordinationOptionsUrl',
    hierarchy: 'hierarchyUrl', related: 'relatedUrl', details: 'detailsUrl'
  };
  var mounted = new WeakSet();
  function text(value) { return typeof value === 'string' ? value.trim() : ''; }
  function parsed(node) { try { return JSON.parse(node.textContent); } catch (_error) { return null; } }

  function mount(host) {
    if (mounted.has(host)) return;
    mounted.add(host);
    var panel = host.querySelector('[data-doris-final-panel]');
    var input = host.querySelector('[data-doris-final-search]');
    var results = host.querySelector('[data-doris-final-results]');
    var message = host.querySelector('[data-doris-final-choice]');
    var target = document.getElementById(host.dataset.finalCodInput);
    var form = document.getElementById(host.dataset.formId);
    var save = form && form.querySelector('[type="submit"]');
    var searchRequest = 0;

    var transport = {
      post: function (path, body) {
        return fetch(host.dataset[ENDPOINTS[path]], {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': host.dataset.csrf}, body: JSON.stringify(body)})
          .then(function (response) {
            return response.json().catch(function () { throw new Error('The server returned an invalid response.'); }).then(function (data) {
              if (response.ok) return data;
              var error = new Error((data && data.error && data.error.message) || 'Request failed (' + response.status + ')');
              error.response = data;
              throw error;
            });
          });
      }
    };
    function confirm(value) {
      // The floating VA definition for the confirmed cause (va_definition_panel.js; absent on pages without it).
      var code = text(value).split(/\s+/)[0].split(/[&/]/)[0];
      if (window.DigitVADefinitionPanel && code) window.DigitVADefinitionPanel.lookup(code, 'Final underlying cause', 'icd11');
      target.value = value;
      message.textContent = 'Confirmed final UCOD: ' + value;
      results.replaceChildren();
      if (save) save.disabled = false;
    }
    var picker = createIcd11Picker({
      mount: host,
      transport: transport,
      onSelect: function (choice) { confirm(choice.code + ' ' + (choice.title || '')); }
    });

    // The same search as the DORIS editor's final box: WHO terms, or codeinfo for a code, then the shared rows.
    function search() {
      var value = text(input.value); picker.clearPanels(panel); results.replaceChildren();
      if (value.length < 2) { message.textContent = 'Type at least 2 characters.'; return; }
      var current = ++searchRequest;
      message.textContent = 'Searching…';
      var looksCode = /\d/.test(value) && !/\s/.test(value);
      var request = looksCode
        ? transport.post('codeinfo', {schema_version: 1, code: value}).then(function (data) { return data.item ? [data.item] : []; })
        : transport.post('terms', {schema_version: 1, query: value, limit: 20, cursor: null}).then(function (data) { return data.items || []; });
      request.then(function (items) {
        if (current !== searchRequest) return;
        picker.renderResults(panel, items, {input: input, statusEl: message, resultList: results, finalMode: true, onRequery: search});
      }).catch(function (error) { if (current === searchRequest) message.textContent = error.message; });
    }

    var processing = parsed(host.querySelector('[data-step1-processing]'));
    if (processing) {
      renderSummary(host.querySelector('[data-doris-summary]'), processing, parsed(host.querySelector('[data-step1-certificate]')) || {}, function (code) {
        return transport.post('codeinfo', {schema_version: 1, code: code}).then(function (data) { return data.item ? data.item.title : ''; });
      });
    }
    // The Step 1 underlying cause was validated when Step 1 was saved.
    host.querySelectorAll('[data-final-use-value]').forEach(function (node) {
      node.addEventListener('click', function () { confirm(node.dataset.finalUseValue); });
    });
    // A single WHO target is checked with WHO on the click, like any search pick.
    host.querySelectorAll('[data-final-use-code]').forEach(function (node) {
      node.addEventListener('click', function () { picker.resolveAndStage(panel, node.dataset.finalUseCode, message); });
    });
    // Several WHO alternatives: the coder chooses, starting from the first.
    host.querySelectorAll('[data-final-search-code]').forEach(function (node) {
      node.addEventListener('click', function () { input.value = node.dataset.finalSearchCode; auto.mark(); search(); input.focus(); });
    });
    // 3+ characters resting 500 ms search without a click; Search/Enter stay immediate.
    var auto = attachAutoSearch(input, search);
    host.querySelector('[data-doris-final-search-button]').addEventListener('click', function () { auto.mark(); search(); });
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); auto.mark(); search(); } });

    // A refused save re-renders with the submitted choice kept; a recode
    // starts from the previous final code, as the masked simple picker does.
    if (target && !text(target.value) && text(host.dataset.presetFinal)) target.value = text(host.dataset.presetFinal);
    if (target && text(target.value)) message.textContent = 'Confirmed final UCOD: ' + text(target.value);
    else if (save) save.disabled = true;
  }

  function boot(root) { (root || document).querySelectorAll('[data-doris-final-host]').forEach(mount); }
  document.addEventListener('DOMContentLoaded', function () { boot(); });
  document.body.addEventListener('htmx:afterSwap', function (event) { boot(event.target); });
  window.setTimeout(function () { boot(); }, 0);
}());
