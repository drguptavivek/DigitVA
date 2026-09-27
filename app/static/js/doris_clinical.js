import { createIcd11Picker } from './digitva_icd11_picker.js';
import { mount as mountInterval } from './doris_interval.js';

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
    function selectFinal(choice) {
      var target = finalInput(editor); if (target) target.value = choice.code + ' ' + (choice.title || '');
      query(editor, '[data-doris-final-choice]').textContent = 'Confirmed final UCOD: ' + choice.code + ' — ' + (choice.title || '');
      query(editor, '[data-doris-final-results]').replaceChildren();
      query(editor, '[data-doris-final-search]').focus();
      var form = document.getElementById(editor.dataset.formId); var save = form && form.querySelector('[type="submit"]');
      if (save) { save.disabled = false; delete save.dataset.dorisNeedsConfirmation; }
    }
    function selectForLine(line, choice) {
      var condition = {Text: choice.selected_text || choice.matching_text || choice.title, Code: choice.code, LinearizationURI: choice.uri};
      line.conditions.push(condition); chip(line, condition);
      var input = line.element.querySelector('[data-doris-search]');
      input.value = ''; line.element.querySelector('[data-doris-search-results]').replaceChildren(); input.focus();
      invalidate('Certificate changed. Process it again.');
    }
    function clearFinal() {
      var input = finalInput(editor); if (input) input.value = '';
      query(editor, '[data-doris-final-choice]').textContent = '';
      query(editor, '[data-doris-final-results]').replaceChildren();
      editor.querySelectorAll('[data-doris-related-window]').forEach(function (windowNode) { windowNode.remove(); });
      picker.closePostcoordination(query(editor, '[data-doris-final-panel]'));
    }
    function invalidate(message) {
      state.revision += 1; state.processing = null;
      query(editor, '[data-doris-results]').hidden = true;
      query(editor, '[data-doris-final-panel]').hidden = true;
      hidden(editor, '[data-doris-certificate]', ''); hidden(editor, '[data-doris-result]', ''); hidden(editor, '[data-codedit-result]', ''); hidden(editor, '[data-doris-token]', ''); hidden(editor, '[data-doris-digest]', '');
      clearFinal();
      var form = document.getElementById(editor.dataset.formId);
      var save = form && form.querySelector('[type="submit"]'); if (save) save.disabled = true;
      if (message) status(message);
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
      var value = text(input.value); resultList.replaceChildren();
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
        message.textContent = items.length ? 'Choose a result.' : 'No matching conditions.';
        var mandatory = [];
        items.forEach(function (item) {
          var row = document.createElement('div'); row.className = 'list-group-item doris-search-result';
          var main = document.createElement('div'); main.className = 'doris-search-result-main';
          var header = document.createElement('div'); header.className = 'doris-search-result-header';
          var title = document.createElement('button'); title.type = 'button'; title.className = 'doris-search-title doris-search-title-button';
      var codeNode = document.createElement('span'); codeNode.className = 'doris-search-code'; codeNode.textContent = item.code || '';
      var titleNode = document.createElement('span'); titleNode.className = 'doris-search-name fw-semibold'; titleNode.textContent = item.title || '';
      title.append(codeNode, ' — ', titleNode);
          title.addEventListener('click', function () {
            if (item.postcoordination_availability === 2 && !picker.isCompleteExpression(item.code)) {
              if (!finalMode) picker.showDetails(container, item);
              picker.openPostcoordination(container, item, title);
            } else picker.stage(container, item, message);
          });
          header.appendChild(title);
          var meta = document.createElement('div'); meta.className = 'doris-search-meta';
          if (item.matching_text && item.matching_text !== item.title) { var match = document.createElement('span'); match.className = 'doris-search-match'; match.textContent = 'Matched: ' + item.matching_text; meta.appendChild(match); }
          var complete = picker.isCompleteExpression(item.code);
          var buildIcon = picker.addContextIcons(meta, item, function (chapter, selected) {
            picker.openRelated(container, chapter, selected, function (term) {
              if (term.requires_postcoordination || !term.uri || finalMode) { input.value = term.code; search(line, finalMode); }
              else picker.stage(container, term, message);
            });
          }, item.postcoordination && !complete ? function (button) {
            if (!finalMode) picker.showDetails(container, item);
            picker.openPostcoordination(container, item, button);
          } : null, function () { picker.showDetails(container, item); });
          var actions = document.createElement('div'); actions.className = 'doris-search-actions';
          if (complete || item.postcoordination_availability !== 2) {
            var use = document.createElement('button'); use.type = 'button'; use.className = 'btn btn-sm btn-outline-primary'; use.textContent = 'Use';
            use.title = 'Select this code';
            use.addEventListener('click', function () { picker.stage(container, item, message); });
            actions.appendChild(use);
          }
          var details = document.createElement('button'); details.type = 'button'; details.className = 'btn btn-sm btn-outline-secondary'; details.textContent = 'Details';
          details.addEventListener('click', function () { picker.showDetails(container, item); });
          actions.appendChild(details);
          if (item.postcoordination_availability === 2 && !complete && buildIcon) mandatory.push({item: item, trigger: buildIcon});
          var controls = document.createElement('div'); controls.className = 'doris-search-controls'; controls.append(meta, actions);
          header.appendChild(controls); main.appendChild(header); row.appendChild(main); resultList.appendChild(row);
        });
        var automatic = items.length && mandatory.length && mandatory[0].item === items[0] ? mandatory[0] : null;
        if (automatic) {
          if (!finalMode) picker.showDetails(container, automatic.item);
          picker.openPostcoordination(container, automatic.item, automatic.trigger, true);
        }
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
      var searchTimer = null;
      function openSearch() {
        picker.open(element, searchInput, function () {
          clearTimeout(searchTimer); state.searchRequest += 1;
          element.querySelector('[data-doris-search-results]').replaceChildren();
        }, function () {
          clearTimeout(searchTimer); state.searchRequest += 1;
          element.querySelector('[data-doris-search-results]').replaceChildren();
          element.querySelector('[data-doris-search-status]').textContent = '';
          picker.closePostcoordination(element);
        });
      }
      element.querySelector('[data-doris-search-button]').addEventListener('click', function () { openSearch(); search(line, false); });
      element.querySelector('[data-doris-add-uncoded]').addEventListener('click', function () { var value = text(searchInput.value); if (!value) { element.querySelector('[data-doris-search-status]').textContent = 'Enter the condition text first.'; return; } var condition = {Text:value,Code:'',LinearizationURI:''}; line.conditions.push(condition); chip(line, condition); searchInput.value=''; element.querySelector('[data-doris-search-status]').textContent='Uncoded text added. DORIS may reject it.'; invalidate(); picker.close(); });
      searchInput.addEventListener('input', function () { openSearch(); picker.clearSelection(element); picker.clearDetails(element); clearTimeout(searchTimer); if (text(searchInput.value).length >= 2) searchTimer = setTimeout(function () { search(line, false); }, 250); else { state.searchRequest += 1; element.querySelector('[data-doris-search-results]').replaceChildren(); picker.closePostcoordination(element); } });
      searchInput.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); clearTimeout(searchTimer); openSearch(); search(line, false); } });
      if (isPart2) { element.querySelector('[data-doris-line-title]').textContent = 'Contributing conditions'; element.querySelector('[data-doris-up]').remove(); element.querySelector('[data-doris-down]').remove(); element.querySelector('[data-doris-remove]').remove(); }
      else {
        element.querySelector('[data-doris-up]').addEventListener('click', function () { var index = state.lines.indexOf(line); if (index > 0) { state.lines.splice(index, 1); state.lines.splice(index - 1, 0, line); renderOrder(); invalidate('Line moved. Process again.'); } });
        element.querySelector('[data-doris-down]').addEventListener('click', function () { var index = state.lines.indexOf(line); if (index < state.lines.length - 1) { state.lines.splice(index, 1); state.lines.splice(index + 1, 0, line); renderOrder(); invalidate('Line moved. Process again.'); } });
        element.querySelector('[data-doris-remove]').addEventListener('click', function () { if (state.lines.length === 1) return; picker.close(); state.lines.splice(state.lines.indexOf(line), 1); renderOrder(); invalidate('Line removed. Process again.'); });
      }
      return line;
    }
    function renderOrder() {
      var container = query(editor, '[data-doris-part1]'); container.replaceChildren();
      state.lines.forEach(function (line, index) { line.element.querySelector('[data-doris-line-title]').textContent = 'Line ' + String.fromCharCode(65 + index) + (index === 0 ? ' — IMMEDIATE CAUSE' : ''); line.element.querySelector('[data-doris-up]').disabled = index === 0; line.element.querySelector('[data-doris-down]').disabled = index === state.lines.length - 1; line.element.querySelector('[data-doris-remove]').disabled = state.lines.length === 1; container.appendChild(line.element); });
      query(editor, '[data-doris-add-line]').disabled = state.lines.length >= MAX_LINES;
    }
    function serializeLine(line) {
      var interval = line.interval ? line.interval.read().value : '';
      return {Conditions: line.conditions.map(function (condition) { var item={Text:condition.Text,Interval:interval}; if(condition.Code)item.Code=condition.Code;if(condition.LinearizationURI)item.LinearizationURI=condition.LinearizationURI;return item; })};
    }
    function certificate() {
      var result = {ICDVersion: 'ICD11', ICDMinorVersion: '2026-01', Part1: state.lines.filter(function (line) { return line.conditions.length; }).map(serializeLine)};
      var sex = query(editor, '[data-doris-sex]').value; var age = text(query(editor, '[data-doris-age]').value);
      if (sex || age) { result.AdministrativeData = {}; if (sex) result.AdministrativeData.Sex = Number(sex); if (age) result.AdministrativeData.EstimatedAge = age; }
      var other = serializeLine(state.part2); if (other.Conditions.length) result.Part2 = other;
      if (query(editor, '[data-doris-life-stage]').value === 'fetal-infant') {
        var fetal = {};
        [['Stillborn','[data-doris-stillborn]'],['MultiplePregnancy','[data-doris-multiple]'],['DeathWithin24h','[data-doris-within24]'],['BirthWeight','[data-doris-birth-weight]'],['PregnancyWeeks','[data-doris-pregnancy-weeks]'],['AgeMother','[data-doris-mother-age]']].forEach(function(entry){var value=numberOrNull(query(editor,entry[1]));if(value!==null)fetal[entry[0]]=value;});
        var perinatal=text(query(editor,'[data-doris-perinatal]').value);if(perinatal)fetal.PerinatalDescription=perinatal;if(Object.keys(fetal).length)result.FetalOrInfantDeath=fetal;
      }
      if (sex === '2') { var pregnant=numberOrNull(query(editor,'[data-doris-pregnant]'));if(pregnant!==null){result.MaternalDeath={WasPregnant:pregnant};if(pregnant!==9){var timing=numberOrNull(query(editor,'[data-doris-pregnancy-time]'));var contribute=numberOrNull(query(editor,'[data-doris-pregnancy-contribute]'));if(timing!==null)result.MaternalDeath.TimeFromPregnancy=timing;if(contribute!==null)result.MaternalDeath.PregnancyContribute=contribute;}} }
      return result;
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
      var doris = processing.doris || {}; var codedit = processing.codedit || {}; var dr = doris.result || {}; var cr = codedit.result || {};
      query(editor, '[data-doris-engine-status]').textContent = 'Status: ' + (doris.status || 'unavailable');
      query(editor, '[data-codedit-engine-status]').textContent = 'Status: ' + (codedit.status || 'unavailable');
      var dl = query(editor, '[data-doris-computed]'); dl.replaceChildren();
      [['Computed stem', dr.stemCode], ['Complete code', dr.code], ['Complete URI', dr.uri]].forEach(function (entry) { var dt = document.createElement('dt'); var dd = document.createElement('dd'); dt.className = 'col-4'; dd.className = 'col-8 text-break'; dt.textContent = entry[0]; dd.textContent = entry[1] || 'None'; dl.append(dt, dd); });
      var messages = query(editor, '[data-doris-messages]'); messages.replaceChildren();
      [['Rejected', dr.reject ? 'Yes — no reliable computed UCOD' : ''], ['Warning', dr.warning], ['Error', dr.error]].forEach(function (entry) { if (!entry[1]) return; var p = document.createElement('p'); p.className = 'alert alert-warning py-2'; p.textContent = entry[0] + ': ' + entry[1]; messages.appendChild(p); });
      query(editor, '[data-doris-report]').textContent = dr.report || 'No report returned.'; query(editor, '[data-codedit-report]').textContent = cr.report || 'No report returned.';
      query(editor, '[data-codedit-issues]').textContent = cr.issueIds ? 'WHO issue IDs: ' + JSON.stringify(cr.issueIds) : 'No issues reported.';
      query(editor, '[data-doris-results]').hidden = false; query(editor, '[data-doris-final-panel]').hidden = false;
      hidden(editor, '[data-doris-certificate]', JSON.stringify(processing.certificate || certificate())); hidden(editor, '[data-doris-result]', JSON.stringify(doris)); hidden(editor, '[data-codedit-result]', JSON.stringify(codedit)); hidden(editor, '[data-doris-token]', processing.process_token); hidden(editor, '[data-doris-digest]', processing.result_digest);
      clearFinal(); status(requireReconfirm ? 'The certificate changed during submission. Fresh results are shown; review them and reconfirm your final UCOD.' : 'Processing complete. Review the results and confirm your final UCOD.');
    }
    function process() {
      var gap = part1Gap();
      if (gap !== -1) { status('Fill or remove Part I line ' + String.fromCharCode(65 + gap) + ' before processing; blank lines cannot separate causes.'); return; }
      var invalidInterval = intervalError();
      if (invalidInterval) { invalidInterval.line.interval.value.focus(); status(invalidInterval.message); return; }
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
    var admin = initial.AdministrativeData || {}; query(editor, '[data-doris-sex]').value = admin.Sex == null ? '' : String(admin.Sex); query(editor, '[data-doris-age]').value = admin.EstimatedAge || '';
    var fetal=initial.FetalOrInfantDeath||{};query(editor,'[data-doris-life-stage]').value=initial.FetalOrInfantDeath?'fetal-infant':'none';[['[data-doris-stillborn]',fetal.Stillborn],['[data-doris-multiple]',fetal.MultiplePregnancy],['[data-doris-within24]',fetal.DeathWithin24h],['[data-doris-birth-weight]',fetal.BirthWeight],['[data-doris-pregnancy-weeks]',fetal.PregnancyWeeks],['[data-doris-mother-age]',fetal.AgeMother],['[data-doris-perinatal]',fetal.PerinatalDescription]].forEach(function(entry){query(editor,entry[0]).value=entry[1]==null?'':String(entry[1]);});
    var maternal=initial.MaternalDeath||{};[['[data-doris-pregnant]',maternal.WasPregnant],['[data-doris-pregnancy-time]',maternal.TimeFromPregnancy],['[data-doris-pregnancy-contribute]',maternal.PregnancyContribute]].forEach(function(entry){query(editor,entry[0]).value=entry[1]==null?'':String(entry[1]);});
    function conditionals(){var sexValue=query(editor,'[data-doris-sex]').value;query(editor,'[data-doris-fetal]').hidden=query(editor,'[data-doris-life-stage]').value!=='fetal-infant';query(editor,'[data-doris-maternal]').hidden=sexValue!=='2';var pregnant=query(editor,'[data-doris-pregnant]').value;editor.querySelectorAll('[data-doris-maternal-followup]').forEach(function(node){node.hidden=pregnant===''||pregnant==='9';});}conditionals();
    editor.querySelectorAll('[data-doris-fetal] input,[data-doris-fetal] select,[data-doris-fetal] textarea,[data-doris-maternal] select').forEach(function(field){field.addEventListener('input',function(){conditionals();invalidate();});});
    query(editor,'[data-doris-life-stage]').addEventListener('change',function(){conditionals();invalidate();});
    query(editor, '[data-doris-sex]').addEventListener('change', function () { conditionals(); invalidate(); }); query(editor, '[data-doris-age]').addEventListener('input', function () { invalidate(); });
    query(editor, '[data-doris-add-line]').addEventListener('click', function () { if (state.lines.length < MAX_LINES) { state.lines.push(makeLine({Conditions: []}, false)); renderOrder(); invalidate('Line added. Process again.'); } });
    query(editor, '[data-doris-process]').addEventListener('click', process);
    query(editor, '[data-doris-final-search-button]').addEventListener('click', function () { search(null, true); });
    query(editor, '[data-doris-final-search]').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); search(null, true); } });
    var form = document.getElementById(editor.dataset.formId); var save = form && form.querySelector('[type="submit"]'); if (save) save.disabled = true;
    editor._installFreshDorisResults = function (processing) { renderProcessing(processing, true); };
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
