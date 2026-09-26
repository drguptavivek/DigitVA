(function () {
  'use strict';

  var app = document.getElementById('doris-demo-app');
  if (!app) return;

  var MAX_LINES = 5;
  var MAX_RESULTS = 20;
  var revision = 0;
  var examples = [];
  var release = '2026-01';
  var requestNumber = 0;
  var activeEctLine = null;
  var ectConfigured = false;
  var form = document.getElementById('doris-certificate');
  var part1 = document.getElementById('doris-part1-lines');
  var part2 = document.getElementById('doris-part2-line');
  var results = document.getElementById('doris-results');
  var status = document.getElementById('doris-app-status');
  var processButton = document.getElementById('doris-process');

  function endpoint(name) { return app.dataset[name + 'Url']; }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': app.dataset.csrf},
      body: JSON.stringify(body)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var error = new Error((data.error && data.error.message) || 'Request failed (' + response.status + ')');
          error.response = data;
          throw error;
        }
        return data;
      });
    });
  }

  function announce(message) { status.textContent = message; }
  function clearResults() {
    results.hidden = true;
    results.removeAttribute('data-revision');
  }
  function changed(message) {
    revision += 1;
    clearResults();
    if (message) announce(message);
  }
  function intOrNull(element) {
    return element.value === '' ? null : Number(element.value);
  }
  function setValue(id, value) {
    document.getElementById(id).value = value === undefined || value === null ? '' : String(value);
  }
  function cleanText(value) { return typeof value === 'string' ? value.trim() : ''; }

  function conditionFromItem(item) {
    return {
      Text: cleanText(item.selected_text || item.matching_text || item.title),
      Code: cleanText(item.code),
      LinearizationURI: cleanText(item.uri || item.linearization_uri || item.LinearizationURI),
      FoundationURI: cleanText(item.foundation_uri || item.FoundationURI),
      title: cleanText(item.title), verified: true
    };
  }

  function addChip(line, condition) {
    var chip = document.createElement('span');
    chip.className = 'doris-chip';
    var label = document.createElement('span');
    label.textContent = (condition.Code ? condition.Code + ' — ' : '') + (condition.Text || condition.title || 'Untitled condition');
    var remove = document.createElement('button');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Remove ' + label.textContent);
    remove.textContent = '×';
    remove.addEventListener('click', function () {
      var index = line._conditions.indexOf(condition);
      if (index !== -1) line._conditions.splice(index, 1);
      chip.remove();
      changed('Condition removed. Process the certificate again to see current results.');
    });
    chip.append(label, remove);
    line.querySelector('[data-chips]').appendChild(chip);
  }

  function showSearchResults(line, items, truncated) {
    var container = line.querySelector('[data-search-results]');
    var searchStatus = line.querySelector('[data-search-status]');
    container.replaceChildren();
    if (!items.length) {
      searchStatus.textContent = 'No matching ICD-11 conditions.';
      return;
    }
    searchStatus.textContent = truncated ? 'Showing the first results; refine the search for more.' : items.length + ' result' + (items.length === 1 ? '' : 's') + '.';
    items.slice(0, MAX_RESULTS).forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'list-group-item list-group-item-action';
      var heading = document.createElement('span');
      heading.className = 'd-block fw-semibold';
      heading.textContent = (item.code || 'No code') + ' — ' + (item.title || 'Untitled');
      button.appendChild(heading);
      if (item.matching_text && item.matching_text !== item.title) {
        var match = document.createElement('span');
        match.className = 'd-block doris-search-match';
        match.textContent = 'Matched: ' + item.matching_text;
        button.appendChild(match);
      }
      if (item.postcoordination) {
        var detail = document.createElement('span');
        detail.className = 'badge text-bg-light';
        detail.textContent = 'Postcoordination available';
        button.appendChild(detail);
      }
      button.addEventListener('click', function () { verifyAndSelect(line, item, button); });
      container.appendChild(button);
    });
  }

  function verifyAndSelect(line, item, button) {
    var searchStatus = line.querySelector('[data-search-status]');
    if (button) button.disabled = true;
    searchStatus.textContent = 'Verifying ' + (item.code || 'selection') + '…';
    var body = {schema_version: 1, code: item.code, uri: item.uri};
    post(endpoint('selection'), body).then(function (data) {
      var verified = data.item || data.selection || data;
      var condition = conditionFromItem(Object.assign({}, item, verified));
      if (!condition.Code || !condition.LinearizationURI) throw new Error('The server did not return a verified code and URI.');
      line._conditions.push(condition);
      addChip(line, condition);
      line.querySelector('[data-search]').value = '';
      line.querySelector('[data-search-results]').replaceChildren();
      searchStatus.textContent = condition.Code + ' verified and added.';
      changed();
    }).catch(function (error) {
      if (button) button.disabled = false;
      searchStatus.textContent = error.message || 'Could not verify this code.';
    });
  }

  function searchLine(line) {
    var query = cleanText(line.querySelector('[data-search]').value);
    var searchStatus = line.querySelector('[data-search-status]');
    if (query.length < 2) {
      searchStatus.textContent = 'Type at least 2 characters.';
      return;
    }
    var current = ++requestNumber;
    searchStatus.textContent = 'Searching…';
    line.querySelector('[data-search-results]').replaceChildren();
    var looksLikeCode = /\d/.test(query) && !/\s/.test(query);
    var lookup = looksLikeCode
      ? post(endpoint('codeinfo'), {schema_version: 1, code: query})
          .then(function (data) { return {items: data.item ? [data.item] : [], truncated: false}; })
      : post(endpoint('terms'), {schema_version: 1, query: query, limit: MAX_RESULTS, cursor: null});
    lookup
      .then(function (data) {
        if (current !== requestNumber) return;
        showSearchResults(line, Array.isArray(data.items) ? data.items : [], Boolean(data.truncated));
      }).catch(function (error) {
        if (current === requestNumber) searchStatus.textContent = error.message || 'Search is unavailable.';
      });
  }

  function refreshLineLabels() {
    Array.from(part1.children).forEach(function (line, index) {
      line.querySelector('[data-line-title]').textContent = 'Line ' + String.fromCharCode(65 + index);
      line.querySelector('[data-move-up]').disabled = index === 0;
      line.querySelector('[data-move-down]').disabled = index === part1.children.length - 1;
      line.querySelector('[data-remove-line]').disabled = part1.children.length === 1;
    });
    document.getElementById('doris-add-line').disabled = part1.children.length >= MAX_LINES;
  }

  function makeLine(kind, source) {
    var line = document.getElementById('doris-line-template').content.firstElementChild.cloneNode(true);
    line._conditions = [];
    line.dataset.kind = kind;
    var conditions = (source && Array.isArray(source.Conditions)) ? source.Conditions : [];
    line.querySelector('[data-interval]').value = conditions.length ? (conditions[0].Interval || '') : '';
    conditions.forEach(function (raw) {
      var condition = {
        Text: raw.Text || '', Code: raw.Code || '', LinearizationURI: raw.LinearizationURI || '',
        FoundationURI: raw.FoundationURI || '', title: raw.Text || '', verified: Boolean(raw.Code && raw.LinearizationURI)
      };
      line._conditions.push(condition);
      addChip(line, condition);
    });
    line.querySelector('[data-interval]').addEventListener('input', function () { changed(); });
    line.querySelector('[data-search-button]').addEventListener('click', function () { searchLine(line); });
    line.querySelector('[data-open-ect]').addEventListener('click', function () { openEct(line); });
    line.querySelector('[data-add-uncoded]').addEventListener('click', function () {
      var text = cleanText(line.querySelector('[data-search]').value);
      if (!text) { line.querySelector('[data-search-status]').textContent = 'Enter the condition text first.'; return; }
      var condition = {Text: text, Code: '', LinearizationURI: '', FoundationURI: '', title: text, verified: false};
      line._conditions.push(condition); addChip(line, condition);
      line.querySelector('[data-search]').value = '';
      line.querySelector('[data-search-results]').replaceChildren();
      line.querySelector('[data-search-status]').textContent = 'Uncoded text added. DORIS may reject an uncoded condition.';
      changed();
    });
    line.querySelector('[data-search]').addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); searchLine(line); }
    });
    line.querySelector('[data-remove-line]').addEventListener('click', function () {
      if (part1.children.length <= 1) return;
      line.remove(); refreshLineLabels(); changed('Line removed.');
    });
    line.querySelector('[data-move-up]').addEventListener('click', function () {
      if (line.previousElementSibling) { part1.insertBefore(line, line.previousElementSibling); refreshLineLabels(); changed('Line moved up.'); }
    });
    line.querySelector('[data-move-down]').addEventListener('click', function () {
      if (line.nextElementSibling) { part1.insertBefore(line.nextElementSibling, line); refreshLineLabels(); changed('Line moved down.'); }
    });
    return line;
  }

  function openEct(line) {
    var panel = document.getElementById('doris-ect-panel');
    var ectStatus = document.getElementById('doris-ect-status');
    activeEctLine = line; panel.hidden = false;
    ectStatus.textContent = 'Loading the WHO Coding Tool for this certificate line…';
    if (!window.ECT || !window.ECT.Handler) { ectStatus.textContent = 'WHO Coding Tool assets are unavailable.'; return; }
    var ready = Promise.resolve();
    if (!ectConfigured) {
      window.ECT.Handler.configure({apiServerUrl: app.dataset.whoApiUrl, apiSecured: false, source: 'mms', minorVersion: release, language: 'en', simplifiedMode: false, autoBind: false}, {
        selectedEntityFunction: function (entity) {
          if (!activeEctLine) return;
          var item = {code: entity && entity.code, title: entity && entity.title, matching_text: entity && entity.selectedText, uri: entity && (entity.linearizationUri || entity.uri)};
          if (!item.code || !item.uri) { ectStatus.textContent = 'Choose a complete WHO code expression.'; return; }
          ectStatus.textContent = 'Verifying the WHO selection…';
          verifyAndSelect(activeEctLine, item, null);
        }
      });
      ectConfigured = true; ready = Promise.resolve(window.ECT.Handler.bind('doris-help'));
    }
    ready.then(function () { ectStatus.textContent = 'Type a diagnosis, inspect the result, then choose the complete expression.'; document.getElementById('doris-ect-query').focus(); }).catch(function () { ectStatus.textContent = 'WHO Coding Tool could not connect to the local ICD-11 service.'; });
  }

  function renderLines(certificate) {
    part1.replaceChildren();
    var sourceLines = Array.isArray(certificate.Part1) && certificate.Part1.length ? certificate.Part1.slice(0, MAX_LINES) : [{Conditions: []}];
    sourceLines.forEach(function (source) { part1.appendChild(makeLine('part1', source)); });
    part2.replaceChildren();
    var p2 = makeLine('part2', certificate.Part2 || {Conditions: []});
    p2.querySelector('[data-line-title]').textContent = 'Other significant conditions';
    p2.querySelector('[data-move-up]').remove(); p2.querySelector('[data-move-down]').remove(); p2.querySelector('[data-remove-line]').remove();
    part2.appendChild(p2);
    refreshLineLabels();
  }

  function updateConditionalSections(notify) {
    var sex = document.getElementById('doris-sex').value;
    var lifeStage = document.getElementById('doris-life-stage').value;
    var maternal = document.getElementById('doris-maternal-section');
    var fetal = document.getElementById('doris-fetal-section');
    fetal.hidden = lifeStage !== 'fetal-infant';
    maternal.hidden = sex !== '2';
    var pregnant = document.getElementById('doris-pregnant').value;
    var followups = document.getElementById('doris-maternal-followups');
    followups.hidden = pregnant === '' || pregnant === '9';
    if (notify) {
      if (sex !== '2') announce('Pregnancy fields are inapplicable and will be omitted.');
      if (lifeStage !== 'fetal-infant') announce('Fetal and infant fields are inapplicable and will be omitted.');
    }
  }

  function loadCertificate(certificate, message) {
    certificate = certificate || {};
    var admin = certificate.AdministrativeData || {};
    setValue('doris-sex', admin.Sex); setValue('doris-age', admin.EstimatedAge);
    var fetal = certificate.FetalOrInfantDeath || {};
    setValue('doris-life-stage', certificate.FetalOrInfantDeath ? 'fetal-infant' : 'none');
    setValue('doris-stillborn', fetal.Stillborn); setValue('doris-multiple', fetal.MultiplePregnancy);
    setValue('doris-within24', fetal.DeathWithin24h); setValue('doris-birth-weight', fetal.BirthWeight);
    setValue('doris-pregnancy-weeks', fetal.PregnancyWeeks); setValue('doris-mother-age', fetal.AgeMother);
    setValue('doris-perinatal-description', fetal.PerinatalDescription);
    var maternal = certificate.MaternalDeath || {};
    setValue('doris-pregnant', maternal.WasPregnant); setValue('doris-pregnancy-time', maternal.TimeFromPregnancy);
    setValue('doris-pregnancy-contribute', maternal.PregnancyContribute);
    renderLines(certificate); updateConditionalSections(false); changed(message);
  }

  function serializeLine(line) {
    var interval = cleanText(line.querySelector('[data-interval]').value);
    return {Conditions: line._conditions.map(function (condition) {
      var result = {Text: condition.Text, Interval: interval};
      if (condition.Code) result.Code = condition.Code;
      if (condition.LinearizationURI) result.LinearizationURI = condition.LinearizationURI;
      if (condition.FoundationURI) result.FoundationURI = condition.FoundationURI;
      return result;
    })};
  }
  function serializeCertificate() {
    var certificate = {ICDVersion: 'ICD11', ICDMinorVersion: release};
    var admin = {};
    var sex = intOrNull(document.getElementById('doris-sex'));
    var age = cleanText(document.getElementById('doris-age').value);
    if (sex !== null) admin.Sex = sex;
    if (age) admin.EstimatedAge = age;
    if (Object.keys(admin).length) certificate.AdministrativeData = admin;
    certificate.Part1 = Array.from(part1.children).map(serializeLine);
    var p2 = serializeLine(part2.firstElementChild);
    if (p2.Conditions.length) certificate.Part2 = p2;
    if (document.getElementById('doris-life-stage').value === 'fetal-infant') {
      var fetal = {};
      [['Stillborn','doris-stillborn'],['MultiplePregnancy','doris-multiple'],['DeathWithin24h','doris-within24'],['BirthWeight','doris-birth-weight'],['PregnancyWeeks','doris-pregnancy-weeks'],['AgeMother','doris-mother-age']].forEach(function (entry) {
        var value = intOrNull(document.getElementById(entry[1])); if (value !== null) fetal[entry[0]] = value;
      });
      var description = cleanText(document.getElementById('doris-perinatal-description').value);
      if (description) fetal.PerinatalDescription = description;
      if (Object.keys(fetal).length) certificate.FetalOrInfantDeath = fetal;
    }
    if (document.getElementById('doris-sex').value === '2') {
      var pregnant = intOrNull(document.getElementById('doris-pregnant'));
      if (pregnant !== null) {
        certificate.MaternalDeath = {WasPregnant: pregnant};
        if (pregnant !== 9) {
          var timing = intOrNull(document.getElementById('doris-pregnancy-time'));
          var contributed = intOrNull(document.getElementById('doris-pregnancy-contribute'));
          if (timing !== null) certificate.MaternalDeath.TimeFromPregnancy = timing;
          if (contributed !== null) certificate.MaternalDeath.PregnancyContribute = contributed;
        }
      }
    }
    return certificate;
  }

  function textValue(value) {
    if (value === null || value === undefined || value === '') return 'None reported';
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  }
  function addDefinition(list, term, value) {
    var dt = document.createElement('dt'); var dd = document.createElement('dd');
    dt.className = 'col-sm-4'; dd.className = 'col-sm-8 text-break';
    dt.textContent = term; dd.textContent = textValue(value); list.append(dt, dd);
  }
  function renderEngineStatus(id, engine) {
    var element = document.getElementById(id);
    var state = engine && engine.status ? engine.status : 'unavailable';
    element.dataset.status = state;
    element.textContent = state.replaceAll('_', ' ');
  }
  function messageBox(type, label, value) {
    if (value === null || value === undefined || value === '') return null;
    var box = document.createElement('div'); box.className = 'alert alert-' + type + ' py-2';
    var strong = document.createElement('strong'); strong.textContent = label + ': ';
    box.append(strong, document.createTextNode(textValue(value))); return box;
  }

  function parseTabular(raw) {
    if (Array.isArray(raw)) return raw.slice(0, 100).map(function (row) { return Array.isArray(row) ? row : Object.values(row); });
    if (raw && typeof raw === 'object') {
      var candidate = raw.rows || raw.data;
      if (Array.isArray(candidate)) return candidate.slice(0, 100).map(function (row) { return Array.isArray(row) ? row : Object.values(row); });
    }
    var value = cleanText(raw);
    if (!value) return [];
    try { return parseTabular(JSON.parse(value)); } catch (_error) { /* use delimited fallback */ }
    return value.split(/\r?\n/).filter(Boolean).slice(0, 100).map(function (line) {
      // The pinned WHO image emits semicolon-delimited rule rows with a
      // thirteenth trailing BER field. Keep every field in the raw table.
      var delimiter = line.includes(';') ? ';' : (line.includes('\t') ? '\t' : (line.includes('|') ? '|' : ','));
      return line.split(delimiter).map(function (cell) { return cleanText(cell); }).slice(0, 13);
    });
  }
  function safeDiagramLabel(value) {
    return textValue(value).replace(/[^A-Za-z0-9 .:_()/-]/g, ' ').replace(/\s+/g, ' ').slice(0, 70) || 'Rule';
  }
  function renderTrace(raw) {
    var rows = parseTabular(raw);
    var head = document.querySelector('#doris-rule-table thead');
    var body = document.querySelector('#doris-rule-table tbody');
    head.replaceChildren(); body.replaceChildren();
    if (!rows.length) {
      document.getElementById('doris-trace-status').textContent = 'No parseable rule rows were returned. The raw report remains available below.';
      document.getElementById('doris-rule-flow').textContent = 'No rule flow available.';
      document.getElementById('doris-rule-sequence').textContent = 'No rule sequence available.';
      return;
    }
    var width = Math.max.apply(null, rows.map(function (row) { return row.length; }));
    var header = document.createElement('tr');
    for (var column = 0; column < width; column += 1) { var th = document.createElement('th'); th.textContent = 'Field ' + (column + 1); header.appendChild(th); }
    head.appendChild(header);
    rows.forEach(function (row) { var tr = document.createElement('tr'); for (var index = 0; index < width; index += 1) { var td = document.createElement('td'); td.textContent = textValue(row[index] || ''); tr.appendChild(td); } body.appendChild(tr); });
    document.getElementById('doris-trace-status').textContent = 'Parsed ' + rows.length + ' row' + (rows.length === 1 ? '' : 's') + ' using the pinned report parser.';
    var labels = rows.slice(0, 25).map(function (row) {
      return safeDiagramLabel((row[0] || 'Rule') + ' ' + (row[1] === 'True' ? 'applied' : 'not applied') + ' — ' + (row[8] || ''));
    });
    var flow = 'flowchart TD\n' + labels.map(function (label, index) { return 'n' + index + '["' + label.replaceAll('"', '') + '"]' + (index ? '\nn' + (index - 1) + ' --> n' + index : ''); }).join('\n');
    var sequence = 'sequenceDiagram\nparticipant D as DORIS\nparticipant R as Rules\n' + labels.map(function (label) { return 'D->>R: ' + label.replaceAll(':', ' '); }).join('\n');
    renderMermaid('doris-rule-flow', flow); renderMermaid('doris-rule-sequence', sequence);
  }
  function renderMermaid(id, source) {
    var container = document.getElementById(id); container.textContent = 'Rendering…';
    if (!window.mermaid || !window.mermaid.render) { container.textContent = 'Diagram rendering is unavailable. Use the rule table or raw report.'; return; }
    Promise.resolve(window.mermaid.render(id + '-svg-' + revision, source)).then(function (rendered) {
      container.innerHTML = rendered.svg;
    }).catch(function () { container.textContent = 'This diagram could not be rendered. Use the rule table or raw report.'; });
  }

  function renderResults(data, expectedRevision) {
    if (revision !== expectedRevision || data.client_revision !== expectedRevision) {
      announce('A newer edit replaced this response. Process the current certificate again.'); return;
    }
    var doris = data.doris || {}; var codedit = data.codedit || {};
    var dorisResult = doris.result || {}; var codeditResult = codedit.result || {};
    renderEngineStatus('doris-engine-status', doris); renderEngineStatus('codedit-engine-status', codedit);
    var computed = document.getElementById('doris-computed'); computed.replaceChildren();
    addDefinition(computed, 'Computed stem', dorisResult.stemCode);
    addDefinition(computed, 'Complete code', dorisResult.code);
    addDefinition(computed, 'Complete URI', dorisResult.uri);
    var messages = document.getElementById('doris-messages'); messages.replaceChildren();
    [messageBox('danger','Rejected',dorisResult.reject ? 'Yes — no reliable computed UCOD' : ''), messageBox('warning','Warning',dorisResult.warning), messageBox('danger','Error',dorisResult.error)].forEach(function (box) { if (box) messages.appendChild(box); });
    document.getElementById('doris-report').textContent = textValue(dorisResult.report);
    document.getElementById('codedit-report').textContent = textValue(codeditResult.report);
    document.getElementById('codedit-issues').textContent = codeditResult.issueIds ? 'WHO issue IDs: ' + textValue(codeditResult.issueIds) : 'No issues reported.';
    document.getElementById('doris-raw-tabular').textContent = textValue(dorisResult.tabularReport);
    document.getElementById('codedit-raw-tabular').textContent = textValue(codeditResult.tabularReport);
    results.hidden = false; results.dataset.revision = String(revision); renderTrace(dorisResult.tabularReport);
    announce('Processing complete. Review the independent DORIS and CoDEdit results.');
    results.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function processCertificate() {
    var certificate = serializeCertificate();
    if (!certificate.Part1.some(function (line) { return line.Conditions.length; })) {
      announce('Add at least one verified condition to Part I before processing.'); return;
    }
    var sentRevision = revision;
    processButton.disabled = true; announce('DORIS and CoDEdit are processing independently…'); clearResults();
    post(endpoint('process'), {schema_version: 1, client_revision: sentRevision, certificate: certificate})
      .then(function (data) { renderResults(data, sentRevision); })
      .catch(function (error) {
        if (revision !== sentRevision) return;
        var fields = error.response && error.response.error && error.response.error.fields;
        announce(error.message + (Array.isArray(fields) && fields.length ? ' Check: ' + fields.map(function (field) { return field.path + ' — ' + field.message; }).join('; ') : ''));
      }).finally(function () { processButton.disabled = false; });
  }

  function loadConfig() {
    announce('Loading the synthetic examples…');
    fetch(endpoint('config'), {credentials: 'same-origin'}).then(function (response) {
      if (!response.ok) throw new Error('Configuration unavailable'); return response.json();
    }).then(function (data) {
      release = data.icd_release || release; examples = Array.isArray(data.examples) ? data.examples : [];
      var select = document.getElementById('doris-example');
      examples.forEach(function (example) { var option = document.createElement('option'); option.value = example.id; option.textContent = example.label; select.appendChild(option); });
      announce('Ready. Start blank or load one of ' + examples.length + ' synthetic examples.');
    }).catch(function () { announce('Examples could not be loaded. A blank certificate is still available.'); });
  }

  document.getElementById('doris-add-line').addEventListener('click', function () {
    if (part1.children.length >= MAX_LINES) return;
    part1.appendChild(makeLine('part1', {Conditions: []})); refreshLineLabels(); changed('Line added.');
  });
  document.getElementById('doris-load-example').addEventListener('click', function () {
    var id = document.getElementById('doris-example').value;
    var example = examples.find(function (item) { return item.id === id; });
    var purpose = document.getElementById('doris-example-purpose');
    purpose.hidden = !example; purpose.textContent = example ? example.purpose : '';
    loadCertificate(example ? example.certificate : {}, example ? example.label + ' loaded. You can edit every field.' : 'Blank certificate ready.');
  });
  document.getElementById('doris-new').addEventListener('click', function () {
    document.getElementById('doris-example').value = ''; document.getElementById('doris-example-purpose').hidden = true;
    loadCertificate({}, 'Blank certificate ready.');
  });
  processButton.addEventListener('click', processCertificate);
  document.getElementById('doris-ect-close').addEventListener('click', function () { document.getElementById('doris-ect-panel').hidden = true; activeEctLine = null; });
  form.addEventListener('input', function (event) {
    if (!event.target.matches('[data-certificate-input]')) return;
    updateConditionalSections(event.target.id === 'doris-sex' || event.target.id === 'doris-life-stage'); changed();
  });
  form.addEventListener('change', function (event) {
    if (event.target.id === 'doris-pregnant') updateConditionalSections(false);
  });

  if (window.mermaid && window.mermaid.initialize) window.mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'neutral'});
  loadCertificate({}, 'Blank certificate ready.'); loadConfig();
}());
