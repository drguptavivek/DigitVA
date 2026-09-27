// Masked ICD-11 Step 2 host (digitva-0n3): confirms the final underlying
// cause with the shared ICD-11 picker. No certificate and no Process; the
// Step 1 DORIS run is shown read-only through renderSummary. The server
// derives which choice was used, so nothing here reports provenance.
import { createIcd11Picker } from './digitva_icd11_picker.js';
import { renderSummary } from './doris_result_summary.js';

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
  function button(label, className) {
    var node = document.createElement('button'); node.type = 'button';
    node.className = className || 'btn btn-sm btn-outline-secondary'; node.textContent = label;
    return node;
  }

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

    function search() {
      var value = text(input.value); results.replaceChildren();
      if (value.length < 2) { message.textContent = 'Type at least 2 characters.'; return; }
      var current = ++searchRequest;
      message.textContent = 'Searching…';
      var looksCode = /\d/.test(value) && !/\s/.test(value);
      var request = looksCode
        ? transport.post('codeinfo', {schema_version: 1, code: value}).then(function (data) { return data.item ? [data.item] : []; })
        : transport.post('terms', {schema_version: 1, query: value, limit: 20, cursor: null}).then(function (data) { return data.items || []; });
      request.then(function (items) {
        if (current !== searchRequest) return;
        message.textContent = items.length ? 'Choose a result.' : 'No matching conditions.';
        items.forEach(function (item) {
          var row = document.createElement('div'); row.className = 'list-group-item d-flex flex-wrap justify-content-between align-items-center gap-2';
          var label = document.createElement('span'); label.textContent = (item.code || '') + ' — ' + (item.title || '');
          // A stem WHO requires to be postcoordinated is built first.
          var mustBuild = item.postcoordination_availability === 2 && !picker.isCompleteExpression(item.code);
          var use = button(mustBuild ? 'Build code' : 'Use', 'btn btn-sm btn-outline-primary');
          use.addEventListener('click', function () {
            if (mustBuild) picker.openPostcoordination(panel, item, use);
            else picker.stage(panel, item, message);
          });
          var details = button('Details');
          details.addEventListener('click', function () { picker.showDetails(panel, item); });
          var actions = document.createElement('div'); actions.className = 'd-flex gap-2'; actions.append(use, details);
          row.append(label, actions); results.appendChild(row);
        });
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
      node.addEventListener('click', function () { input.value = node.dataset.finalSearchCode; search(); input.focus(); });
    });
    host.querySelector('[data-doris-final-search-button]').addEventListener('click', search);
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); search(); } });

    // A refused save re-renders with the submitted choice kept.
    if (target && text(target.value)) message.textContent = 'Confirmed final UCOD: ' + text(target.value);
    else if (save) save.disabled = true;
  }

  function boot(root) { (root || document).querySelectorAll('[data-doris-final-host]').forEach(mount); }
  document.addEventListener('DOMContentLoaded', function () { boot(); });
  document.body.addEventListener('htmx:afterSwap', function (event) { boot(event.target); });
  window.setTimeout(function () { boot(); }, 0);
}());
