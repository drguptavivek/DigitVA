import { createIcd11Picker, attachAutoSearch } from './digitva_icd11_picker.js?v=5';
import { mount as mountInterval } from './doris_interval.js?v=4';
import * as Rules from './doris_rules.js?v=4';
import * as Fields from './doris_fields.js?v=2';
import { renderSummary, usableDorisCode } from './doris_result_summary.js?v=6';

(function () {
  'use strict';

  var MAX_LINES = 5;
  var mounted = new WeakSet();
  function text(value) { return typeof value === 'string' ? value.trim() : ''; }
  function post(editor, url, body) {
    return fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': editor.dataset.csrf}, body: JSON.stringify(body)})
      .then(function (response) { return response.json().catch(function () { throw new Error('The server returned an invalid response.'); }).then(function (data) { if (!data || typeof data !== 'object') throw new Error('The server returned an invalid response.'); return {ok: response.ok, status: response.status, data: data}; }); });
  }
  function query(editor, selector) { return editor.querySelector(selector); }
  function hidden(editor, selector, value) { var node = query(editor, selector); if (node) node.value = value || ''; }
  function finalInput(editor) { return document.getElementById(editor.dataset.finalCodInput); }
  function numberOrNull(element) { return element.value === '' ? null : Number(element.value); }
  // Controls a hide rule (V1-V6, docs/policy/doris-certificate-rules.md) has
  // hidden are emptied, so they start blank if the rule later shows them.
  function clearControls(node) {
    Fields.removePrefillMarkers(node);
    node.querySelectorAll('input,select,textarea').forEach(function (control) {
      if (control.hasAttribute('data-doris-precision')) return;
      if (control.hasAttribute('data-doris-date')) Fields.resetDate(control); else control.value = '';
    });
  }
  // Certificate sections the editor carries beyond Part I/II, fetal and
  // maternal: [DORIS field, control selector, 'number' | 'text'].
  var EXTRA_SECTIONS = [
    {name: 'MannerOfDeath', fields: [['MannerOfDeath', '[data-doris-manner-of-death]', 'number'], ['DateOfExternalCauseOrPoisoning', '[data-doris-external-date]', 'text'], ['DescriptionExternalCause', '[data-doris-external-description]', 'text'], ['PlaceOfOccuranceExternalCause', '[data-doris-external-place]', 'number']]},
    {name: 'Surgery', fields: [['WasPerformed', '[data-doris-surgery-performed]', 'number'], ['Date', '[data-doris-surgery-date]', 'text'], ['Reason', '[data-doris-surgery-reason]', 'text']]},
    {name: 'Autopsy', fields: [['WasRequested', '[data-doris-autopsy-requested]', 'number'], ['Findings', '[data-doris-autopsy-findings]', 'number']]}
  ];
  // "from interview (Id10019)" beside each field the interview prefilled.
  // The map comes from the server (doris_prefill_from_payload); text only.
  function showPrefillMarkers(editor) {
    var prefill;
    try { prefill = JSON.parse((editor.querySelector('[data-doris-prefill]') || {}).textContent || '{}'); } catch (_error) { prefill = null; }
    if (!prefill || typeof prefill !== 'object' || Array.isArray(prefill)) return;
    editor.querySelectorAll('[data-doris-field]').forEach(function (host) {
      var entry = prefill[host.dataset.dorisField];
      if (!entry || !Array.isArray(entry.sources) || !entry.sources.length) return;
      var marker = document.createElement('span');
      marker.className = 'badge text-bg-light border fw-normal ms-1';
      marker.dataset.dorisPrefillMarker = host.dataset.dorisField;
      marker.textContent = 'from interview (' + entry.sources.join(', ') + (typeof entry.note === 'string' && entry.note ? '; ' + entry.note : '') + ')';
      (host.querySelector('label') || host).appendChild(marker);
    });
  }

  // Logical picker path -> the editor's own dataset URL attribute.
  var TRANSPORT_ENDPOINTS = {
    terms: 'termsUrl', codeinfo: 'codeinfoUrl', 'selection-check': 'selectionUrl',
    postcoordination: 'postcoordinationUrl', 'postcoordination-options': 'postcoordinationOptionsUrl',
    hierarchy: 'hierarchyUrl', related: 'relatedUrl', details: 'detailsUrl'
  };

  function mount(editor) {
    if (mounted.has(editor)) return;
    mounted.add(editor);
    var state = {revision: 0, processingRevision: 0, searchRequest: 0, processing: null, lines: [], part2: null};
    editor._dorisState = state;
    // Referenced by the module-level htmx:beforeSwap handler below, which
    // is the clinical page's own hook (a mobile WebView host must not
    // inherit it, so the picker no longer owns it).
    var initial;
    try {
      initial = JSON.parse(query(editor, '[data-doris-initial]').textContent);
      if (!initial || typeof initial !== 'object' || Array.isArray(initial)) throw new Error('Invalid certificate');
    } catch (_error) {
      query(editor, '[data-doris-status]').textContent = 'The certificate could not be loaded. Refresh the page before coding.';
      query(editor, '[data-doris-process]').disabled = true;
      var initialForm = document.getElementById(editor.dataset.formId);
      var initialSave = initialForm && initialForm.querySelector('[type="submit"]');
      if (initialSave) initialSave.disabled = true;
      return;
    }

    var transport = {
      post: function (path, body) {
        return post(editor, editor.dataset[TRANSPORT_ENDPOINTS[path]], body).then(function (result) {
          if (result.ok) return result.data;
          var error = new Error((result.data.error && result.data.error.message) || 'Request failed (' + result.status + ')');
          error.response = result.data;
          throw error;
        });
      }
    };
    // `line` for a certificate line, or the final-UCOD panel container for
    // the confirmed-cause search; the picker treats both the same way.
    var picker = createIcd11Picker({
      mount: editor,
      transport: transport,
      // Combine the edit-revision with the processing-revision: a final
      // UCOD selection started against one processed result must not
      // confirm after a reprocess (e.g. a 409 conflict install) replaces
      // it -- even though the certificate itself did not change.
      revision: function () { return state.revision + ':' + state.processingRevision; },
      onSelect: function (choice, container) {
        if (container === query(editor, '[data-doris-final-panel]')) {
          selectFinal(choice);
          return;
        }
        var line = state.lines.concat(state.part2 ? [state.part2] : []).find(function (candidate) { return candidate.element === container; });
        if (line) selectForLine(line, choice);
      }
    });
    editor._dorisPicker = picker;

    function status(message) { query(editor, '[data-doris-status]').textContent = message || ''; }
    // "Continue to Step 2" is offered only while a saved Step 1 is shown unchanged.
    function hideContinue() { var form = document.getElementById(editor.dataset.formId); var button = form && form.querySelector('[data-doris-continue]'); if (button) button.hidden = true; }
    // The floating VA definition for a picked ICD-11 cause (va_definition_panel.js; absent on pages without it).
    function showDefinition(code, fieldLabel) {
      var stem = String(code || '').split('/').map(function (part) { return part.split('&')[0]; }).join('/');
      if (window.DigitVADefinitionPanel && stem) window.DigitVADefinitionPanel.lookup(stem, fieldLabel, 'icd11');
    }
    // The picker's "causing condition not known" choice travels with the final as a form field.
    function setUnknownCause(flag) {
      var target = finalInput(editor); var form = target && target.form; if (!form) return;
      var field = form.querySelector('input[name="causing_condition_unknown"]');
      if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = 'causing_condition_unknown'; form.appendChild(field); }
      field.value = flag ? 'true' : 'false';
    }
    function selectFinal(choice) {
      showDefinition(choice.code, 'Final underlying cause');
      var target = finalInput(editor); if (target) target.value = choice.code + ' ' + (choice.title || '');
      setUnknownCause(choice.causing_condition_unknown === true);
      query(editor, '[data-doris-final-choice]').textContent = 'Confirmed final UCOD: ' + choice.code + ' — ' + (choice.title || '');
      query(editor, '[data-doris-final-results]').replaceChildren();
      query(editor, '[data-doris-final-search]').focus();
      // A saved result has no process token, so it cannot be saved again.
      if (state.savedOnly) { hideContinue(); status('To save a different underlying cause, process the certificate again. You can also change it in Step 2.'); return; }
      var form = document.getElementById(editor.dataset.formId); var save = form && form.querySelector('[type="submit"]');
      if (save) { save.disabled = false; delete save.dataset.dorisNeedsConfirmation; }
    }
    function selectForLine(line, choice) {
      showDefinition(choice.code, 'Certificate line');
      var condition = {Text: choice.selected_text || choice.matching_text || choice.title, Code: choice.code, LinearizationURI: choice.uri};
      line.conditions.push(condition); chip(line, condition);
      var input = line.element.querySelector('[data-doris-search]');
      input.value = ''; if (line.resetAuto) line.resetAuto(); line.element.querySelector('[data-doris-search-results]').replaceChildren(); input.focus();
      invalidate('Certificate changed. Process it again.');
    }
    function clearFinal() {
      var input = finalInput(editor); if (input) input.value = '';
      setUnknownCause(false);
      query(editor, '[data-doris-final-choice]').textContent = '';
      query(editor, '[data-doris-final-results]').replaceChildren();
      editor.querySelectorAll('[data-doris-related-window]').forEach(function (windowNode) { windowNode.remove(); });
      picker.closePostcoordination(query(editor, '[data-doris-final-panel]'));
    }
    function invalidate(message) {
      var hadResult = state.processing !== null;
      state.revision += 1; state.processing = null; state.savedOnly = false; hideContinue();
      query(editor, '[data-doris-results]').hidden = true;
      query(editor, '[data-doris-final-panel]').hidden = true; query(editor, '[data-doris-final-wait]').hidden = false; query(editor, '[data-doris-technical]').hidden = true;
      hidden(editor, '[data-doris-certificate]', ''); hidden(editor, '[data-doris-result]', ''); hidden(editor, '[data-codedit-result]', ''); hidden(editor, '[data-doris-token]', ''); hidden(editor, '[data-doris-digest]', '');
      clearFinal();
      var form = document.getElementById(editor.dataset.formId);
      var save = form && form.querySelector('[type="submit"]'); if (save) save.disabled = true;
      if (message) status(message);
      else if (hadResult) status('Certificate changed. Process it again before saving.');
      applyRules();
    }
    function chip(line, condition) {
      var item = document.createElement('span'); item.className = 'badge text-bg-light border text-wrap';
      var label = document.createElement('span'); label.textContent = (condition.Code ? condition.Code + ' — ' : 'Uncoded — ') + condition.Text;
      var remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn btn-sm p-0 ms-2'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove ' + label.textContent);
      remove.addEventListener('click', function () { line.conditions.splice(line.conditions.indexOf(condition), 1); item.remove(); line.element.querySelector('[data-doris-interval-control]').hidden = !line.conditions.length; invalidate('Certificate changed. Process it again.'); });
      item.append(label, remove); line.element.querySelector('[data-doris-chips]').appendChild(item);
      line.element.querySelector('[data-doris-interval-control]').hidden = false;
    }
    function lookup(url, body) {
      return post(editor, url, body).then(function (result) { if (!result.ok) throw new Error((result.data.error && result.data.error.message) || result.data.error || 'Lookup failed.'); return result.data; });
    }
    function search(line, finalMode) {
      var input = finalMode ? query(editor, '[data-doris-final-search]') : line.element.querySelector('[data-doris-search]');
      var resultList = finalMode ? query(editor, '[data-doris-final-results]') : line.element.querySelector('[data-doris-search-results]');
      var message = finalMode ? query(editor, '[data-doris-final-choice]') : line.element.querySelector('[data-doris-search-status]');
      var container = finalMode ? query(editor, '[data-doris-final-panel]') : line.element;
      var value = text(input.value); picker.clearPanels(container); resultList.replaceChildren();
      if (value.length < 2) { message.textContent = 'Type at least 2 characters.'; return; }
      var currentRequest = ++state.searchRequest;
      var sentRevision = state.revision;
      message.textContent = 'Searching…';
      var looksCode = /\d/.test(value) && !/\s/.test(value);
      var promise = looksCode && editor.dataset.codeinfoUrl
        ? lookup(editor.dataset.codeinfoUrl, {schema_version: 1, code: value}).then(function (data) { return data.item ? [data.item] : []; })
        : lookup(editor.dataset.termsUrl, {schema_version: 1, query: value, limit: 20, cursor: null}).then(function (data) { return data.items || []; });
      promise.then(function (items) {
        if (currentRequest !== state.searchRequest || sentRevision !== state.revision || value !== text(input.value)) return;
        picker.renderResults(container, items, {input: input, statusEl: message, resultList: resultList, finalMode: finalMode, onRequery: function () { search(line, finalMode); }});
      }).catch(function (error) { if (currentRequest === state.searchRequest && sentRevision === state.revision) message.textContent = error.message; });
    }
    function makeLine(source, isPart2) {
      var element = query(editor, '[data-doris-line-template]').content.firstElementChild.cloneNode(true);
      var conditions = source && Array.isArray(source.Conditions) ? source.Conditions.map(function (condition) { return Object.assign({}, condition); }) : [];
      var line = {element: element, conditions: conditions};
      line.interval = mountInterval(element.querySelector('[data-doris-interval-control]'), conditions[0] ? conditions[0].Interval || '' : '');
      conditions.forEach(function (condition) { chip(line, condition); });
      if (line.interval.value) line.interval.value.addEventListener('input', function () { invalidate(); });
      if (line.interval.unit) line.interval.unit.addEventListener('change', function () { invalidate(); });
      var searchInput = element.querySelector('[data-doris-search]');
      var searchTimer = null; var modalOpen = false;
      // The box only opens the search modal on Search/Enter or once 3+ characters rest for 500 ms; inside the open modal each pause searches (250 ms) as before.
      var auto = attachAutoSearch(searchInput, function () { if (modalOpen) return; openSearch(); search(line, false); });
      function openSearch() {
        clearTimeout(searchTimer); auto.cancel(); modalOpen = true;
        picker.open(element, searchInput, function () {
          modalOpen = false; clearTimeout(searchTimer); state.searchRequest += 1;
          element.querySelector('[data-doris-search-results]').replaceChildren();
        }, function () {
          auto.reset(); clearTimeout(searchTimer); state.searchRequest += 1;
          element.querySelector('[data-doris-search-results]').replaceChildren();
          element.querySelector('[data-doris-search-status]').textContent = '';
          picker.closePostcoordination(element);
        });
      }
      line.resetAuto = auto.reset;
      function runSearch() { auto.mark(); clearTimeout(searchTimer); openSearch(); search(line, false); }
      element.querySelector('[data-doris-search-button]').addEventListener('click', runSearch);
      element.querySelector('[data-doris-add-uncoded]').addEventListener('click', function () { var value = text(searchInput.value); if (!value) { element.querySelector('[data-doris-search-status]').textContent = 'Enter the condition text first.'; return; } var condition = {Text:value,Code:'',LinearizationURI:''}; line.conditions.push(condition); chip(line, condition); searchInput.value=''; auto.reset(); element.querySelector('[data-doris-search-status]').textContent='Uncoded text added. DORIS may reject it.'; invalidate(); picker.close(); });
      searchInput.addEventListener('input', function () { if (!modalOpen) return; picker.clearSelection(element); picker.clearDetails(element); clearTimeout(searchTimer); if (text(searchInput.value).length >= 2) searchTimer = setTimeout(function () { search(line, false); }, 250); else { state.searchRequest += 1; element.querySelector('[data-doris-search-results]').replaceChildren(); picker.closePostcoordination(element); } });
      searchInput.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); runSearch(); } });
      if (isPart2) { element.querySelector('[data-doris-line-title]').textContent = 'Significant conditions contributing to death'; element.querySelector('[data-doris-line-letter]').remove(); element.querySelector('[data-doris-up]').remove(); element.querySelector('[data-doris-down]').remove(); element.querySelector('[data-doris-remove]').remove(); element.querySelector('[data-doris-add-below-row]').remove(); }
      else {
        element.querySelector('[data-doris-up]').addEventListener('click', function () { var index = state.lines.indexOf(line); if (index > 0) { state.lines.splice(index, 1); state.lines.splice(index - 1, 0, line); renderOrder(); invalidate('Line moved. Process again.'); } });
        element.querySelector('[data-doris-down]').addEventListener('click', function () { var index = state.lines.indexOf(line); if (index < state.lines.length - 1) { state.lines.splice(index, 1); state.lines.splice(index + 1, 0, line); renderOrder(); invalidate('Line moved. Process again.'); } });
        element.querySelector('[data-doris-add-below]').addEventListener('click', function () {
          var index = state.lines.indexOf(line); if (state.lines.length >= MAX_LINES) return;
          var added = makeLine({Conditions: []}, false); state.lines.splice(index + 1, 0, added); renderOrder(); invalidate('Line added. Process again.');
          added.element.querySelector('[data-doris-search]').focus();
        });
        element.querySelector('[data-doris-remove]').addEventListener('click', function () { if (state.lines.length === 1) return; picker.close(); state.lines.splice(state.lines.indexOf(line), 1); renderOrder(); invalidate('Line removed. Process again.'); });
      }
      return line;
    }
    function renderOrder() {
      var container = query(editor, '[data-doris-part1]'); container.replaceChildren();
      state.lines.forEach(function (line, index) { line.element.querySelector('[data-doris-line-letter]').textContent = String.fromCharCode(65 + index); line.element.querySelector('[data-doris-line-title]').textContent = (index === 0 ? 'Immediate cause' : 'Due to'); line.element.querySelector('[data-doris-up]').disabled = index === 0; line.element.querySelector('[data-doris-down]').disabled = index === state.lines.length - 1; line.element.querySelector('[data-doris-remove]').disabled = state.lines.length === 1; line.element.querySelector('[data-doris-add-below]').disabled = state.lines.length >= MAX_LINES; container.appendChild(line.element); });
      query(editor, '[data-doris-add-line]').disabled = state.lines.length >= MAX_LINES;
    }
    function serializeLine(line) {
      var interval = line.interval ? line.interval.read().value : '';
      return {Conditions: line.conditions.map(function (condition) { var item={Text:condition.Text,Interval:interval}; if(condition.Code)item.Code=condition.Code;if(condition.LinearizationURI)item.LinearizationURI=condition.LinearizationURI;return item; })};
    }
    function certificate() { return Rules.dropHidden(rawCertificate()); }
    function rawCertificate() {
      var result = {ICDVersion: 'ICD11', ICDMinorVersion: '2026-01', Part1: state.lines.filter(function (line) { return line.conditions.length; }).map(serializeLine)};
      var sex = query(editor, '[data-doris-sex]').value; var age = ageControl.peek();
      var admin = {}; if (sex) admin.Sex = Number(sex); if (age) admin.EstimatedAge = age;
      putText(admin, 'DateBirth', '[data-doris-date-birth]'); putText(admin, 'DateDeath', '[data-doris-date-death]');
      if (Object.keys(admin).length) result.AdministrativeData = admin;
      var other = serializeLine(state.part2); if (other.Conditions.length) result.Part2 = other;
      var fetal = {};
      [['Stillborn','[data-doris-stillborn]'],['MultiplePregnancy','[data-doris-multiple]'],['DeathWithin24h','[data-doris-within24]'],['BirthWeight','[data-doris-birth-weight]'],['PregnancyWeeks','[data-doris-pregnancy-weeks]'],['AgeMother','[data-doris-mother-age]']].forEach(function(entry){var value=numberOrNull(query(editor,entry[1]));if(value!==null)fetal[entry[0]]=value;});
      var perinatal=text(query(editor,'[data-doris-perinatal]').value);if(perinatal)fetal.PerinatalDescription=perinatal;if(Object.keys(fetal).length)result.FetalOrInfantDeath=fetal;
      { var pregnant=numberOrNull(query(editor,'[data-doris-pregnant]'));if(pregnant!==null){result.MaternalDeath={WasPregnant:pregnant};if(pregnant===1){var timing=numberOrNull(query(editor,'[data-doris-pregnancy-time]'));var contribute=numberOrNull(query(editor,'[data-doris-pregnancy-contribute]'));if(timing!==null)result.MaternalDeath.TimeFromPregnancy=timing;if(contribute!==null)result.MaternalDeath.PregnancyContribute=contribute;}} }
      EXTRA_SECTIONS.forEach(function (section) {
        var values = {};
        section.fields.forEach(function (field) { if (field[2] === 'number') { var value = numberOrNull(query(editor, field[1])); if (value !== null) values[field[0]] = value; } else putText(values, field[0], field[1]); });
        if (Object.keys(values).length) result[section.name] = values;
      });
      return result;
    }
    // A date is sent only when complete for its precision: a half-typed year is not a date.
    function putText(target, key, selector) {
      var control = query(editor, selector); var value = text(control.value);
      if (control.hasAttribute('data-doris-date') || control.hasAttribute('data-doris-date-plain')) { if (Fields.isDate(value)) target[key] = value; return; }
      if (value) target[key] = value;
    }
    function part1Gap() {
      var firstBlank = -1;
      for (var index = 0; index < state.lines.length; index += 1) {
        if (!state.lines[index].conditions.length && firstBlank === -1) firstBlank = index;
        else if (state.lines[index].conditions.length && firstBlank !== -1) return firstBlank;
      }
      return -1;
    }
    function intervalError() {
      var lines = state.lines.concat(state.part2 ? [state.part2] : []);
      for (var index = 0; index < lines.length; index += 1) {
        if (!lines[index].conditions.length || !lines[index].interval) continue;
        var result = lines[index].interval.validate();
        if (result.error) return {line: lines[index], message: result.error};
      }
      return null;
    }
    function renderProcessing(processing, requireReconfirm) {
      state.processing = processing;
      state.processingRevision += 1;
      state.savedOnly = !processing.process_token; if (!state.savedOnly) hideContinue();
      var doris = processing.doris || {}; var codedit = processing.codedit || {}; var dr = doris.result || {}; var cr = codedit.result || {};
      renderSummary(query(editor, '[data-doris-summary]'), processing, processing.certificate || certificate(), editor.dataset.codeinfoUrl ? function (code) {
        return post(editor, editor.dataset.codeinfoUrl, {schema_version: 1, code: code}).then(function (result) { return result.data && result.data.item ? result.data.item.title : ''; });
      } : null);
      var useDoris = query(editor, '[data-doris-final-use]'); var shownRevision = state.processingRevision;
      state.dorisCode = ''; useDoris.hidden = true;
      if (editor.dataset.codeinfoUrl) {
        usableDorisCode(processing, function (code) {
          return post(editor, editor.dataset.codeinfoUrl, {schema_version: 1, code: code}).then(function (result) { return Boolean(result.ok && result.data && result.data.item); }, function () { return false; });
        }).then(function (code) {
          if (state.processingRevision !== shownRevision) return;
          state.dorisCode = code; useDoris.hidden = !code; useDoris.textContent = 'Use DORIS result: ' + code;
        });
      }
      query(editor, '[data-doris-engine-status]').textContent = 'Status: ' + (doris.status || 'unavailable');
      query(editor, '[data-codedit-engine-status]').textContent = 'Status: ' + (codedit.status || 'unavailable');
      var dl = query(editor, '[data-doris-computed]'); dl.replaceChildren();
      [['Computed stem', dr.stemCode], ['Complete code', dr.code], ['Complete URI', dr.uri]].forEach(function (entry) { var dt = document.createElement('dt'); var dd = document.createElement('dd'); dt.className = 'col-4'; dd.className = 'col-8 text-break'; dt.textContent = entry[0]; dd.textContent = entry[1] || 'None'; dl.append(dt, dd); });
      var messages = query(editor, '[data-doris-messages]'); messages.replaceChildren();
      [['Rejected', dr.reject ? 'Yes — no reliable computed UCOD' : ''], ['Warning', dr.warning], ['Error', dr.error]].forEach(function (entry) { if (!entry[1]) return; var p = document.createElement('p'); p.className = 'alert alert-warning py-2'; p.textContent = entry[0] + ': ' + entry[1]; messages.appendChild(p); });
      query(editor, '[data-doris-report]').textContent = dr.report || 'No report returned.'; query(editor, '[data-codedit-report]').textContent = cr.report || 'No report returned.';
      query(editor, '[data-codedit-issues]').textContent = cr.issueIds ? 'WHO issue IDs: ' + JSON.stringify(cr.issueIds) : 'No issues reported.';
      query(editor, '[data-doris-results]').hidden = false; query(editor, '[data-doris-final-panel]').hidden = false; query(editor, '[data-doris-final-wait]').hidden = true; query(editor, '[data-doris-technical]').hidden = false;
      hidden(editor, '[data-doris-certificate]', JSON.stringify(processing.certificate || certificate())); hidden(editor, '[data-doris-result]', JSON.stringify(doris)); hidden(editor, '[data-codedit-result]', JSON.stringify(codedit)); hidden(editor, '[data-doris-token]', processing.process_token); hidden(editor, '[data-doris-digest]', processing.result_digest);
      clearFinal(); status(requireReconfirm ? 'The certificate changed during submission. Fresh results are shown; review them and reconfirm your final UCOD.' : 'Processing complete. Review the results and confirm your final UCOD.');
    }
    function process() {
      var gap = part1Gap();
      if (gap !== -1) { status('Fill or remove Part I line ' + (gap + 1) + ' before processing; blank lines cannot separate causes.'); return; }
      var invalidInterval = intervalError();
      if (invalidInterval) { invalidInterval.line.interval.value.focus(); status(invalidInterval.message); return; }
      var ageCheck = ageControl.validate();
      if (ageCheck.error) { ageControl.value.focus(); status('Estimated age: ' + ageCheck.error); return; }
      var payload = {schema_version: 1, client_revision: state.revision, role: editor.dataset.role, certificate: certificate()}; var sent = state.revision;
      var button = query(editor, '[data-doris-process]'); button.disabled = true; status('Processing with DORIS and CoDEdit…');
      post(editor, editor.dataset.processUrl, payload).then(function (result) {
        if (sent !== state.revision) return;
        if (!result.ok) throw new Error((result.data.error && result.data.error.message) || 'Processing failed.');
        if (!result.data || !result.data.certificate || !result.data.doris || !result.data.codedit || !result.data.process_token || !result.data.result_digest) {
          throw new Error('The server returned an incomplete processing response.');
        }
        renderProcessing(result.data, false);
      }).catch(function (error) { status(error.message); }).finally(function () { button.disabled = false; });
    }
    var initialPart1 = Array.isArray(initial.Part1) && initial.Part1.length ? initial.Part1 : [{Conditions: []}, {Conditions: []}, {Conditions: []}];
    state.lines = initialPart1.slice(0, MAX_LINES).map(function (line) { return makeLine(line, false); });
    state.part2 = makeLine(initial.Part2 || {Conditions: []}, true); query(editor, '[data-doris-part2]').appendChild(state.part2.element); renderOrder();
    var admin = initial.AdministrativeData || {}; query(editor, '[data-doris-sex]').value = admin.Sex == null ? '' : String(admin.Sex); var ageControl = mountInterval(query(editor, '[data-doris-age-control]'), admin.EstimatedAge || '');
    var fetal=initial.FetalOrInfantDeath||{};[['[data-doris-stillborn]',fetal.Stillborn],['[data-doris-multiple]',fetal.MultiplePregnancy],['[data-doris-within24]',fetal.DeathWithin24h],['[data-doris-birth-weight]',fetal.BirthWeight],['[data-doris-pregnancy-weeks]',fetal.PregnancyWeeks],['[data-doris-mother-age]',fetal.AgeMother],['[data-doris-perinatal]',fetal.PerinatalDescription]].forEach(function(entry){query(editor,entry[0]).value=entry[1]==null?'':String(entry[1]);});
    Fields.mountDates(editor);
    Fields.setDate(query(editor, '[data-doris-date-birth]'), admin.DateBirth || ''); Fields.setPlainDate(query(editor, '[data-doris-date-death]'), admin.DateDeath || '');
    // EstimatedAge is derived from the two dates when blank or still the value derived last time (Rules.ageFromDates);
    // a value the coder typed or cleared is left alone until a date changes.
    var derivedAge = null;
    function syncDerivedAge() {
      var current = ageControl.peek();
      // A half-typed age (a number without a unit reads as '') is user input too: a date change never replaces it.
      if (!Rules.mayRefillAge(current, ageControl.typed(), derivedAge)) { derivedAge = null; return; }
      var dates = rawCertificate().AdministrativeData || {};
      var next = Rules.ageFromDates(dates.DateBirth || '', dates.DateDeath || '');
      if (next !== current) ageControl.set(next);
      derivedAge = next || null;
    }
    // Load-time derive only for a fresh prefill seed. A restored processing (data-doris-initial-processing) or a
    // saved certificate (no prefill provenance) keeps the EstimatedAge it was saved with.
    var prefillProvenance = {};
    try { prefillProvenance = JSON.parse((query(editor, '[data-doris-prefill]') || {}).textContent || '{}') || {}; } catch (_error) { prefillProvenance = {}; }
    var restored = null;
    try { restored = JSON.parse((query(editor, '[data-doris-initial-processing]') || {}).textContent || 'null'); } catch (_error) { restored = null; }
    if (Rules.derivesAtLoad(prefillProvenance, restored)) syncDerivedAge();
    EXTRA_SECTIONS.forEach(function (section) { var saved = initial[section.name] || {}; section.fields.forEach(function (field) { var control = query(editor, field[1]); var value = saved[field[0]] == null ? '' : String(saved[field[0]]); if (control.hasAttribute('data-doris-date')) Fields.setDate(control, value); else control.value = value; }); });
    var maternal=initial.MaternalDeath||{};[['[data-doris-pregnant]',maternal.WasPregnant],['[data-doris-pregnancy-time]',maternal.TimeFromPregnancy],['[data-doris-pregnancy-contribute]',maternal.PregnancyContribute]].forEach(function(entry){query(editor,entry[0]).value=entry[1]==null?'':String(entry[1]);});
    var rulesReady = false;
    function warningNode(message) { var node = document.createElement('div'); node.className = 'form-text doris-warning'; node.setAttribute('role', 'status'); node.dataset.dorisWarning = ''; node.textContent = message; return node; }
    // Rules V1-V6 hide (and empty) controls, V9 greys oversized interval units,
    // V3/V9-V11 write soft warnings. Never blocks Process or Save.
    function applyRules() {
      if (!rulesReady) return;
      var shown = Rules.visibility(rawCertificate());
      editor.querySelectorAll('[data-doris-rule]').forEach(function (node) {
        if (!shown[node.dataset.dorisRule]) clearControls(node);
        node.hidden = !shown[node.dataset.dorisRule];
      });
      var raw = rawCertificate(); shown = Rules.visibility(raw);
      var sex = (raw.AdministrativeData || {}).Sex;
      editor.querySelectorAll('[data-doris-na]').forEach(function (note) {
        var key = note.dataset.dorisNa; note.hidden = shown[key];
        note.textContent = key === 'maternal' ? (sex === 1 ? Rules.NOT_APPLICABLE.maternalMale : Rules.NOT_APPLICABLE.maternal) : Rules.NOT_APPLICABLE[key];
      });
      editor.querySelectorAll('[data-doris-maternal-followup] select').forEach(function (select) { select.disabled = !shown.pregnancyFollowup; if (!shown.pregnancyFollowup) select.value = ''; });
      var all = state.lines.map(function (line, index) { return {key: index, line: line, part1: true}; }).concat(state.part2 ? [{key: 'p2', line: state.part2, part1: false}] : []);
      var oversized = Rules.oversizedUnits(raw);
      all.forEach(function (entry) {
        var unit = entry.line.interval.unit;
        unit.querySelectorAll('option').forEach(function (option) { option.disabled = oversized.indexOf(option.value) !== -1 && option.value !== unit.value; });
        entry.line.element.querySelector('[data-doris-interval-warning]').textContent = '';
      });
      editor.querySelectorAll('[data-doris-warning]').forEach(function (node) { node.remove(); });
      var intervals = all.filter(function (entry) { return entry.line.conditions.length; }).map(function (entry) { return {key: entry.key, iso: entry.line.interval.peek(), part1: entry.part1}; });
      Rules.warnings(raw, {today: editor.dataset.today, intervals: intervals}).forEach(function (warning) {
        if (warning.path.indexOf('interval:') === 0) {
          var key = warning.path.slice(9); var target = all.find(function (entry) { return String(entry.key) === key; });
          if (target) target.line.element.querySelector('[data-doris-interval-warning]').textContent = warning.message;
          return;
        }
        var host = editor.querySelector('[data-doris-field="' + warning.path + '"]');
        if (host) host.appendChild(warningNode(warning.message));
      });
      clearButtons.refresh();
    }
    var clearButtons = Fields.mountClear(editor);
    rulesReady = true; applyRules();
    showPrefillMarkers(editor);
    // A date change refills the derived age before the editor invalidates (the date inputs are also data-doris-extra).
    [query(editor, '[data-doris-date-birth]'), query(editor, '[data-doris-date-death]')].forEach(function (input) { input.addEventListener('input', syncDerivedAge); });
    editor.querySelectorAll('[data-doris-fetal] input,[data-doris-fetal] select,[data-doris-fetal] textarea,[data-doris-maternal] select,[data-doris-extra]').forEach(function(field){field.addEventListener('input',function(){invalidate();});});
    query(editor, '[data-doris-sex]').addEventListener('change', function () { invalidate(); }); ageControl.value.addEventListener('input', function () { derivedAge = null; invalidate(); }); ageControl.unit.addEventListener('change', function () { derivedAge = null; invalidate(); });
    query(editor, '[data-doris-add-line]').addEventListener('click', function () { if (state.lines.length < MAX_LINES) { state.lines.push(makeLine({Conditions: []}, false)); renderOrder(); invalidate('Line added. Process again.'); } });
    query(editor, '[data-doris-process]').addEventListener('click', process);
    var finalBox = query(editor, '[data-doris-final-search]');
    var autoFinal = attachAutoSearch(finalBox, function () { search(null, true); });
    query(editor, '[data-doris-final-search-button]').addEventListener('click', function () { autoFinal.mark(); search(null, true); });
    // Copies DORIS's suggestion into Step 2 only on this click, verified like a searched code.
    query(editor, '[data-doris-final-use]').addEventListener('click', function () {
      if (state.dorisCode) picker.resolveAndStage(query(editor, '[data-doris-final-panel]'), state.dorisCode, query(editor, '[data-doris-final-choice]'));
    });
    finalBox.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); autoFinal.mark(); search(null, true); } });
    var form = document.getElementById(editor.dataset.formId); var save = form && form.querySelector('[type="submit"]'); if (save) save.disabled = true;
    editor._installFreshDorisResults = function (processing) { renderProcessing(processing, true); };
    // After a save refused for another reason, the server sends back the
    // processed result and final choice; its token is re-checked at save.
    if (restored && restored.certificate && restored.doris && restored.codedit && restored.process_token && restored.result_digest) {
      renderProcessing(restored, false);
      var restoredFinal = text(restored.final_choice);
      if (restoredFinal) {
        var target = finalInput(editor); if (target) target.value = restoredFinal;
        setUnknownCause(false);
        query(editor, '[data-doris-final-choice]').textContent = 'Confirmed final UCOD: ' + restoredFinal;
        if (save) { save.disabled = false; delete save.dataset.dorisNeedsConfirmation; }
      }
      status('Your processed certificate was kept. Resolve the items above, then save again.');
    } else if (restored && restored.certificate && restored.doris && restored.codedit) {
      // A saved masked Step 1 (no token): show it read-only; Save stays
      // disabled until the certificate is processed again.
      renderProcessing(restored, false);
      var savedFinal = text(restored.final_choice);
      if (savedFinal) {
        var savedTarget = finalInput(editor); if (savedTarget) savedTarget.value = savedFinal;
        setUnknownCause(false);
        query(editor, '[data-doris-final-choice]').textContent = 'Saved underlying cause: ' + savedFinal;
      }
      status('Step 1 is saved. Continue to Step 2, or edit the certificate and process it again to change it.');
    }
  }

  function boot(root) { (root || document).querySelectorAll('[data-doris-editor]').forEach(mount); }
  function conflict(event) {
    var xhr = event.detail && event.detail.xhr; if (!xhr || xhr.status !== 409) return;
    try { var data = JSON.parse(xhr.responseText); if (!data.error || data.error.code !== 'DORIS_CERTIFICATE_CHANGED' || !data.processing) return; var editor = event.target.querySelector && event.target.querySelector('[data-doris-editor]'); if (!editor) editor = document.querySelector('[data-doris-editor]'); if (editor && editor._installFreshDorisResults) { event.preventDefault(); editor._installFreshDorisResults(data.processing); } } catch (_error) {}
  }
  document.addEventListener('DOMContentLoaded', function () { boot(); });
  document.body.addEventListener('htmx:afterSwap', function (event) { boot(event.target); });
  document.body.addEventListener('htmx:responseError', conflict);
  // The picker no longer owns this hook (a mobile WebView host must not
  // inherit it); the clinical page is the one HTMX-driven host, so it
  // closes any open picker modal on every swap.
  document.body.addEventListener('htmx:beforeSwap', function () {
    document.querySelectorAll('[data-doris-editor]').forEach(function (editor) {
      if (editor._dorisPicker) editor._dorisPicker.close();
    });
  });
  window.setTimeout(function () { boot(); }, 0);
}());
