(function (root) {
  'use strict';

  var active = null;

  function close() {
    if (!active) return;
    var current = active;
    active = null;
    document.removeEventListener('keydown', current.onKeydown, true);
    current.backdrop.remove();
    current.closeButton.remove();
    current.resetButton.remove();
    current.footer.remove();
    clearDetails(current.line);
    var related = current.line.querySelector('[data-doris-related-window]');
    if (related) related.remove();
    current.line.classList.remove('doris-search-modal-open');
    current.line.removeAttribute('role');
    current.line.removeAttribute('aria-modal');
    current.line.removeAttribute('aria-label');
    document.body.classList.remove('doris-modal-lock');
    if (current.onClose) current.onClose();
    if (current.input.isConnected) current.input.focus();
  }

  function open(line, input, onClose, onReset) {
    if (active && active.line === line) return;
    close();
    var backdrop = document.createElement('div');
    backdrop.className = 'doris-search-backdrop';
    backdrop.addEventListener('click', close);
    document.body.appendChild(backdrop);
    var closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn btn-sm btn-outline-secondary doris-search-close';
    closeButton.textContent = 'Close search';
    closeButton.addEventListener('click', close);
    var resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'btn btn-sm btn-outline-secondary doris-search-reset';
    resetButton.textContent = 'Reset';
    resetButton.setAttribute('aria-label', 'Reset search and current selection');
    resetButton.addEventListener('click', function () {
      if (!active || active.line !== line) return;
      input.value = '';
      clearSelection(line);
      clearDetails(line);
      var related = line.querySelector('[data-doris-related-window]');
      if (related) related.remove();
      if (onReset) onReset();
      input.focus();
    });
    var heading = line.querySelector('[data-line-title], [data-doris-line-title]');
    heading.parentElement.append(resetButton, closeButton);
    line.classList.add('doris-search-modal-open');
    line.setAttribute('role', 'dialog');
    line.setAttribute('aria-modal', 'true');
    line.setAttribute('aria-label', 'Find an ICD-11 condition');
    var footer = document.createElement('div'); footer.className = 'doris-selection-footer border-top';
    var choice = document.createElement('div'); choice.className = 'doris-selection-choice'; choice.textContent = 'No code selected';
    var confirm = document.createElement('button'); confirm.type = 'button'; confirm.className = 'btn btn-primary'; confirm.textContent = 'OK'; confirm.disabled = true;
    confirm.addEventListener('click', function () { if (active && active.line === line && active.selection) active.onConfirm(confirm); });
    footer.append(choice, confirm); line.appendChild(footer);
    document.body.classList.add('doris-modal-lock');
    function onKeydown(event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      var controls = Array.from(line.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])')).filter(function (node) { return node.getClientRects().length; });
      if (!controls.length) return;
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1].focus(); }
      else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0].focus(); }
    }
    document.addEventListener('keydown', onKeydown, true);
    active = {line: line, input: input, onClose: onClose, onKeydown: onKeydown, backdrop: backdrop, closeButton: closeButton, resetButton: resetButton, footer: footer, choice: choice, confirm: confirm};
    input.focus();
  }

  function stage(line, item, onConfirm) {
    if (!active || active.line !== line) return false;
    active.selection = item;
    active.onConfirm = onConfirm;
    active.choice.textContent = 'Selected: ' + (item.code || '') + (item.title ? ' — ' + item.title : '');
    active.confirm.disabled = false;
    return true;
  }

  function clearSelection(line) {
    if (!active || active.line !== line) return;
    active.selection = null;
    active.onConfirm = null;
    active.choice.textContent = 'No code selected';
    active.confirm.disabled = true;
  }

  function clearDetails(line) {
    var panel = line.querySelector('[data-doris-details-panel]');
    if (!panel) return;
    panel._request = null;
    panel.hidden = true;
    panel.replaceChildren();
  }

  function showDetails(line, item, load) {
    var panel = line.querySelector('[data-doris-details-panel]');
    if (!panel) return;
    panel.hidden = false;
    panel.replaceChildren();
    var heading = document.createElement('h4'); heading.className = 'h6 mb-2';
    heading.textContent = (item.code || '') + (item.title ? ' — ' + item.title : '');
    var body = document.createElement('div'); body.className = 'small'; body.textContent = 'Loading WHO code details…';
    panel.append(heading, body);
    var current = Symbol(); panel._request = current;
    load().then(function (data) {
      if (!panel.isConnected || panel._request !== current) return;
      body.replaceChildren();
      function section(title, values, formatter) {
        if (!values.length) return;
        var label = document.createElement('h5'); label.className = 'small fw-semibold mt-2 mb-1'; label.textContent = title;
        var list = document.createElement('ul'); list.className = 'doris-details-list mb-1';
        values.forEach(function (value) { var row = document.createElement('li'); row.textContent = formatter(value); list.appendChild(row); });
        body.append(label, list);
      }
      if (data.coding_note) {
        var note = document.createElement('div'); note.className = 'doris-coding-note';
        var noteLabel = document.createElement('strong'); noteLabel.textContent = '☰ Coding note';
        var noteText = document.createElement('p'); noteText.className = 'mb-0'; noteText.textContent = data.coding_note;
        note.append(noteLabel, noteText); body.appendChild(note);
      }
      if (data.definition) {
        var definitionLabel = document.createElement('h5'); definitionLabel.className = 'small fw-semibold mt-2 mb-1'; definitionLabel.textContent = 'Definition';
        var definition = document.createElement('p'); definition.className = 'mb-1'; definition.textContent = data.definition;
        body.append(definitionLabel, definition);
      }
      if (data.fully_specified_name) {
        var label = document.createElement('h5'); label.className = 'small fw-semibold mt-2 mb-1'; label.textContent = 'Fully specified name';
        var value = document.createElement('p'); value.className = 'mb-1'; value.textContent = data.fully_specified_name;
        body.append(label, value);
      }
      section('Matching terms', data.matching_terms || [], function (term) { return term; });
      section('Includes', data.inclusions || [], function (term) { return term; });
      section('Exclusions', data.exclusions || [], function (term) { return term.title + (term.code ? ' (' + term.code + ')' : ''); });
      if (!body.childNodes.length) body.textContent = 'No additional WHO details were returned.';
      if (data.truncated) { var note = document.createElement('p'); note.className = 'text-muted mb-0'; note.textContent = 'More WHO details exist than are shown here.'; body.appendChild(note); }
    }).catch(function (error) { if (panel.isConnected && panel._request === current) body.textContent = error.message || 'WHO code details are unavailable.'; });
  }

  function openRelated(container, chapter, item, load, onCode) {
    var windowNode = container.querySelector('[data-doris-related-window]');
    if (!windowNode) {
      windowNode = document.createElement('section');
      windowNode.className = 'doris-related-window border rounded shadow';
      windowNode.setAttribute('data-doris-related-window', '');
      windowNode.setAttribute('role', 'dialog');
      windowNode.setAttribute('aria-modal', 'false');
      container.appendChild(windowNode);
    }
    windowNode.replaceChildren();
    var header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center gap-2 border-bottom p-2';
    var heading = document.createElement('h4');
    heading.className = 'h6 mb-0';
    heading.textContent = chapter === 'maternal' ? 'Pregnancy related terms' : 'Perinatal related terms';
    var closeButton = document.createElement('button');
    closeButton.type = 'button'; closeButton.className = 'btn btn-sm btn-outline-secondary'; closeButton.textContent = 'Close';
    closeButton.addEventListener('click', function () { windowNode.remove(); });
    header.append(heading, closeButton);
    var content = document.createElement('div'); content.className = 'doris-related-content p-2'; content.textContent = 'Loading WHO related terms…';
    windowNode.append(header, content);
    var current = Symbol(); windowNode._request = current;
    load().then(function (data) {
      if (!windowNode.isConnected || windowNode._request !== current) return;
      content.replaceChildren();
      var terms = data && data.terms;
      if (!Array.isArray(terms) || !terms.length) { content.textContent = 'No related terms were returned for this code.'; return; }
      var stem = document.createElement('div'); stem.className = 'fw-semibold mb-2'; stem.textContent = (item.code || '') + (item.title ? ' — ' + item.title : '');
      content.appendChild(stem);
      var markers = document.createElement('div'); markers.className = 'mb-2';
      addContextIcons(markers, item, function (nextChapter) { openRelated(container, nextChapter, item, load, onCode); });
      content.appendChild(markers);
      var list = document.createElement('ul'); list.className = 'list-group list-group-flush doris-related-terms';
      terms.forEach(function (term) {
        var row = document.createElement('li'); row.className = 'list-group-item';
        var label = (term.code ? term.code + ' — ' : '') + (term.title || 'Unnamed WHO term');
        if (term.code) {
          var choose = document.createElement('button'); choose.type = 'button';
          choose.className = 'btn btn-link btn-sm text-start p-0'; choose.textContent = label;
          choose.addEventListener('click', function () { windowNode.remove(); onCode(term); });
          row.appendChild(choose);
        } else row.textContent = label;
        list.appendChild(row);
      });
      content.appendChild(list);
      if (data.truncated) { var note = document.createElement('p'); note.className = 'small text-muted mt-2 mb-0'; note.textContent = 'WHO returned a shortened list.'; content.appendChild(note); }
    }).catch(function (error) { if (windowNode.isConnected && windowNode._request === current) content.textContent = error.message || 'Related terms are unavailable.'; });
    closeButton.focus();
  }

  function addContextIcons(parent, item, onRelated, onBuild, onDetails) {
    if (!item.postcoordination && !item.related_maternal && !item.related_perinatal && !item.has_coding_note) return null;
    var icons = document.createElement('span');
    icons.className = 'doris-context-icons';
    var buildButton = null;
    function icon(label, description, modifier, chapter) {
      var isBuild = label === '+' && Boolean(onBuild);
      var node = document.createElement(chapter || isBuild ? 'button' : 'span');
      if (chapter) { node.type = 'button'; node.addEventListener('click', function () { onRelated(chapter, item); }); }
      if (isBuild) { node.type = 'button'; node.addEventListener('click', function () { onBuild(node); }); buildButton = node; }
      node.className = 'doris-context-icon doris-context-icon--' + modifier;
      if (chapter) {
        var glyph = document.createElement('i');
        glyph.className = 'fa-solid ' + (chapter === 'maternal' ? 'fa-person-pregnant' : 'fa-baby');
        glyph.setAttribute('aria-hidden', 'true');
        var letter = document.createElement('span'); letter.textContent = label;
        node.append(glyph, letter);
      } else node.textContent = isBuild ? '+ Build' : label;
      node.title = description;
      node.setAttribute('aria-label', description);
      icons.appendChild(node);
    }
    if (item.postcoordination) icon('+', item.postcoordination_availability === 2 ? 'Mandatory postcoordination' : 'Postcoordination available', item.postcoordination_availability === 2 ? 'required' : 'post');
    if (item.related_maternal && onRelated) icon('J', 'Open pregnancy related terms', 'maternal', 'maternal');
    if (item.related_perinatal && onRelated) icon('K', 'Open perinatal related terms', 'perinatal', 'perinatal');
    if (item.has_coding_note) {
      var note = document.createElement(onDetails ? 'button' : 'span');
      if (onDetails) { note.type = 'button'; note.addEventListener('click', onDetails); }
      note.className = 'doris-context-icon doris-context-icon--note';
      note.textContent = '☰'; note.title = 'Coding note available'; note.setAttribute('aria-label', 'Open coding note');
      icons.appendChild(note);
    }
    parent.appendChild(icons);
    return buildButton;
  }

  root.DigitvaDorisSearchModal = {open: open, close: close, stage: stage, clearSelection: clearSelection, showDetails: showDetails, clearDetails: clearDetails, addContextIcons: addContextIcons, openRelated: openRelated};
  document.body.addEventListener('htmx:beforeSwap', close);
  root.addEventListener('pagehide', close);
}(typeof window === 'undefined' ? globalThis : window));
