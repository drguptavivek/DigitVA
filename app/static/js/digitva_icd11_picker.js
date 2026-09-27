/**
 * Reusable ICD-11 condition picker (search modal + WHO postcoordination
 * builder), framework-free and host-agnostic so a Cordova/React-Native
 * WebView shell can load it alongside the web hosts.
 *
 * createIcd11Picker(options) -> picker
 *   options.mount     Element the modal backdrop is appended to. Body
 *                      scroll lock still toggles a class on document.body
 *                      (a host concern, not a picker one).
 *   options.transport {post(path, body) -> Promise<json>}. `path` is one
 *                      of 'terms' | 'codeinfo' | 'selection-check' |
 *                      'postcoordination' | 'postcoordination-options' |
 *                      'hierarchy' | 'related' | 'details'. The host maps
 *                      these to URLs and attaches auth (CSRF header + same
 *                      origin credentials on web, a bearer token on
 *                      mobile). On a non-2xx response transport.post must
 *                      reject with an Error whose `.response` is the
 *                      parsed JSON body, matching WHO/DigitVA API error
 *                      shapes (`error.code`, `error.message`) -- the
 *                      picker relies on this to tell "code not found" from
 *                      a real failure.
 *   options.onSelect(choice, container) Called with the server-verified
 *                      choice (code, title, uri, ...) once selection-check
 *                      has confirmed it. The host owns what happens next
 *                      (add a chip, fill an input) -- the picker never
 *                      touches the host's data model.
 *   options.onClose()  Optional. Fires when the search modal closes.
 *   options.revision() Optional. Returns the host's current edit-revision
 *                      counter so in-flight requests can detect a stale
 *                      certificate and drop their response.
 *
 * A `container` argument throughout (the certificate line, or a
 * standalone panel such as a "confirm final UCOD" section) is any element
 * that carries the picker's marker attributes: [data-line-title] or
 * [data-doris-line-title], [data-doris-details-panel],
 * [data-doris-guided-panel], and (for the modal) [data-doris-related-window]
 * is created on demand. The postcoordination builder keeps independent
 * state per container (a WeakMap), so it works the same whether or not
 * that container currently owns the search modal.
 */
export function createIcd11Picker(options) {
  'use strict';
  var mount = options.mount;
  var transport = options.transport;

  function text(value) { return typeof value === 'string' ? value.trim() : ''; }
  function list(value) { return Array.isArray(value) ? value : []; }
  function safeUrl(value) { return typeof value === 'string' && value ? value : ''; }
  function currentRevision() { return typeof options.revision === 'function' ? options.revision() : null; }
  function button(label, className) {
    var node = document.createElement('button');
    node.type = 'button';
    node.className = className || 'btn btn-sm btn-outline-secondary';
    node.textContent = label;
    return node;
  }

  // ---- search modal (one active line at a time) --------------------

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
    closePostcoordination(current.line);
    current.line.classList.remove('doris-search-modal-open');
    current.line.removeAttribute('role');
    current.line.removeAttribute('aria-modal');
    current.line.removeAttribute('aria-label');
    document.body.classList.remove('doris-modal-lock');
    if (current.onClose) current.onClose();
    if (options.onClose) options.onClose();
    if (current.input.isConnected) current.input.focus();
  }

  function reset() {
    if (!active) return;
    active.input.value = '';
    clearSelection(active.line);
    clearDetails(active.line);
    var related = active.line.querySelector('[data-doris-related-window]');
    if (related) related.remove();
    var onReset = active.onReset;
    if (onReset) onReset();
    active.input.focus();
  }

  function open(line, input, onClose, onReset) {
    if (active && active.line === line) return;
    close();
    var backdrop = document.createElement('div');
    backdrop.className = 'doris-search-backdrop';
    backdrop.addEventListener('click', close);
    mount.appendChild(backdrop);
    var closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn btn-sm btn-outline-secondary doris-search-close';
    closeButton.textContent = 'Close search';
    closeButton.addEventListener('click', close);
    var resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'btn btn-sm btn-outline-secondary doris-search-reset';
    resetButton.setAttribute('aria-label', 'Reset search and current selection');
    resetButton.textContent = 'Reset';
    resetButton.addEventListener('click', reset);
    var heading = line.querySelector('[data-line-title], [data-doris-line-title]');
    heading.parentElement.append(resetButton, closeButton);
    line.classList.add('doris-search-modal-open');
    line.setAttribute('role', 'dialog');
    line.setAttribute('aria-modal', 'true');
    line.setAttribute('aria-label', 'Find an ICD-11 condition');
    var footer = document.createElement('div'); footer.className = 'doris-selection-footer border-top';
    var choice = document.createElement('div'); choice.className = 'doris-selection-choice'; choice.textContent = 'No code selected';
    var confirm = document.createElement('button'); confirm.type = 'button'; confirm.className = 'btn btn-primary'; confirm.textContent = 'OK'; confirm.disabled = true;
    confirm.addEventListener('click', function () {
      if (!active || active.line !== line || !active.selection) return;
      verifyAndSelect(line, active.selection, null, confirm);
    });
    var builderActions = document.createElement('div'); builderActions.className = 'doris-footer-actions d-flex flex-wrap gap-2';
    footer.append(choice, builderActions, confirm); line.appendChild(footer);
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
    active = {line: line, input: input, onClose: onClose, onReset: onReset, onKeydown: onKeydown, backdrop: backdrop, closeButton: closeButton, resetButton: resetButton, footer: footer, choice: choice, builderActions: builderActions, confirm: confirm, selection: null};
    input.focus();
  }

  function clearSelection(line) {
    if (!active || active.line !== line) return;
    active.selection = null;
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

  // ---- selection verification (owned by the picker) -----------------

  // Stage a choice for confirmation. When `container` currently owns the
  // open search modal, the choice waits in the modal footer until the
  // user clicks OK (giving them a chance to check Details/Related first).
  // Otherwise (a standalone container, e.g. a "confirm final UCOD" panel
  // with no modal) the choice is verified immediately.
  function stage(container, item, statusEl) {
    if (active && active.line === container) {
      active.selection = item;
      codeTitle(active.choice, item.code, item.title, 'Selected: ');
      active.confirm.disabled = false;
      showDetails(container, item);
      return true;
    }
    verifyAndSelect(container, item, statusEl, null);
    return false;
  }

  function verifyAndSelect(container, item, statusEl, trigger) {
    var sentRevision = currentRevision();
    if (trigger) trigger.disabled = true;
    var verifying = 'Verifying ' + (item.code || 'selection') + '…';
    if (statusEl) statusEl.textContent = verifying;
    else if (active && active.line === container) active.choice.textContent = verifying;
    return transport.post('selection-check', {schema_version: 1, code: item.code, uri: item.uri}).then(function (data) {
      if (currentRevision() !== sentRevision || !container.isConnected) return;
      var verified = data.item || data.selection || data;
      var choice = Object.assign({}, item, verified);
      if (!choice.code || !choice.uri) throw new Error('The server did not return a verified code and URI.');
      if (statusEl) statusEl.textContent = choice.code + ' verified and added.';
      options.onSelect(choice, container);
      if (active && active.line === container) close();
    }).catch(function (error) {
      if (currentRevision() !== sentRevision || !container.isConnected) return;
      if (trigger) trigger.disabled = false;
      var message = error.message || 'Could not verify this code.';
      if (statusEl) statusEl.textContent = message;
      else if (active && active.line === container) active.choice.textContent = message;
    });
  }

  function showDetails(container, item) {
    var panel = container.querySelector('[data-doris-details-panel]');
    if (!panel) return;
    panel.hidden = false;
    panel.replaceChildren();
    var heading = document.createElement('h4'); heading.className = 'h6 mb-2';
    codeTitle(heading, item.code, item.title);
    var body = document.createElement('div'); body.className = 'small'; body.textContent = 'Loading WHO code details…';
    panel.append(heading, body);
    var current = Symbol(); panel._request = current;
    transport.post('details', {schema_version: 1, code: item.code}).then(function (data) {
      if (!panel.isConnected || panel._request !== current) return;
      body.replaceChildren();
      function section(title, values, formatter) {
        if (!values.length) return;
        var label = document.createElement('h5'); label.className = 'small fw-semibold mt-2 mb-1'; label.textContent = title;
        var listNode = document.createElement('ul'); listNode.className = 'doris-details-list mb-1';
        values.forEach(function (value) { var row = document.createElement('li'); row.textContent = formatter(value); listNode.appendChild(row); });
        body.append(label, listNode);
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
      section('Includes', data.inclusions || [], function (term) { return term; });
      section('Exclusions', data.exclusions || [], function (term) { return term.title + (term.code ? ' (' + term.code + ')' : ''); });
      if (!body.childNodes.length) body.textContent = 'No additional WHO details were returned.';
      if (data.truncated) { var truncated = document.createElement('p'); truncated.className = 'text-muted mb-0'; truncated.textContent = 'More WHO details exist than are shown here.'; body.appendChild(truncated); }
    }).catch(function (error) { if (panel.isConnected && panel._request === current) body.textContent = error.message || 'WHO code details are unavailable.'; });
  }

  function openRelated(container, chapter, item, onCode) {
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
    transport.post('related', {schema_version: 1, code: item.code, chapter: chapter}).then(function (data) {
      if (!windowNode.isConnected || windowNode._request !== current) return;
      content.replaceChildren();
      var terms = data && data.terms;
      var composite = data && data.composite;
      var hasComposite = Boolean(composite && composite.code);
      if ((!Array.isArray(terms) || !terms.length) && !hasComposite) {
        content.textContent = 'No related terms were returned for this code.'; return;
      }
      var stem = document.createElement('div'); stem.className = 'fw-semibold mb-2'; stem.textContent = (item.code || '') + (item.title ? ' — ' + item.title : '');
      content.appendChild(stem);
      var markers = document.createElement('div'); markers.className = 'mb-2';
      addContextIcons(markers, item, function (nextChapter) { openRelated(container, nextChapter, item, onCode); });
      content.appendChild(markers);
      if (hasComposite) {
        var compositeRow = document.createElement('div');
        compositeRow.className = 'alert alert-warning py-2 px-2 mb-2 doris-related-composite';
        var compositeButton = document.createElement('button'); compositeButton.type = 'button';
        compositeButton.className = 'btn btn-link btn-sm text-start p-0 fw-semibold';
        compositeButton.textContent = composite.code + (composite.title ? ' — ' + composite.title : '');
        compositeButton.addEventListener('click', function () { windowNode.remove(); onCode(composite); });
        compositeRow.appendChild(compositeButton);
        content.appendChild(compositeRow);
      }
      if (Array.isArray(terms) && terms.length) {
        var termsList = document.createElement('ul'); termsList.className = 'list-group list-group-flush doris-related-terms';
        terms.forEach(function (term) {
          var row = document.createElement('li'); row.className = 'list-group-item';
          var label = (term.code ? term.code + ' — ' : '') + (term.title || 'Unnamed WHO term');
          if (term.code) {
            var choose = document.createElement('button'); choose.type = 'button';
            choose.className = 'btn btn-link btn-sm text-start p-0'; choose.textContent = label;
            choose.addEventListener('click', function () { windowNode.remove(); onCode(term); });
            row.appendChild(choose);
          } else row.textContent = label;
          termsList.appendChild(row);
        });
        content.appendChild(termsList);
      }
      if (data.truncated) { var truncatedNote = document.createElement('p'); truncatedNote.className = 'small text-muted mt-2 mb-0'; truncatedNote.textContent = 'WHO returned a shortened list.'; content.appendChild(truncatedNote); }
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

  // ---- postcoordination builder (independent state per container) ---

  var postcoordControllers = new WeakMap();

  // Render "CODE — Title" with the code in plain weight and the title
  // emphasised, matching the search rows.
  function codeTitle(target, code, title, prefix, suffix) {
    target.replaceChildren();
    if (prefix) target.append(prefix);
    var codeNode = document.createElement('span'); codeNode.className = 'doris-search-code'; codeNode.textContent = code || '';
    target.appendChild(codeNode);
    if (title) { var titleNode = document.createElement('span'); titleNode.className = 'fw-semibold'; titleNode.textContent = title; target.append(' — ', titleNode); }
    if (suffix) target.append(suffix);
  }
  function optionValue(option) {
    return {
      code: text(option && option.code), title: text(option && option.title),
      uri: text(option && option.uri), block_uri: text(option && option.block_uri),
      has_children: Boolean(option && option.has_children)
    };
  }

  function postcoordController(container) {
    var existing = postcoordControllers.get(container);
    if (existing) return existing;
    var guidedHost = container.querySelector('[data-doris-guided-panel]');
    if (!guidedHost) return null;
    var panel = document.createElement('div');
    panel.className = 'doris-guided-panel border rounded p-3 mt-2';
    panel.hidden = true;
    panel.setAttribute('data-doris-guided-panel-content', '');
    guidedHost.replaceChildren(panel);
    var requestId = 0;
    var stateRevision = null;
    var restoreTrigger = null;
    var state = null;
    var preserveInputFocus = false;

    function stale(id) {
      if (id !== requestId) return true;
      return stateRevision !== currentRevision();
    }
    function closePanel() {
      requestId += 1;
      state = null;
      if (active && active.line === container) { active.builderActions.replaceChildren(); if (!active.selection) active.choice.textContent = 'No code selected'; }
      panel.hidden = true;
      panel.replaceChildren();
      if (!preserveInputFocus && restoreTrigger && typeof restoreTrigger.focus === 'function') restoreTrigger.focus();
      restoreTrigger = null;
      preserveInputFocus = false;
    }
    function header(title, description, skipFocus) {
      panel.replaceChildren();
      var row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-start gap-2';
      var heading = document.createElement('div');
      var h = null;
      if (title) {
        h = document.createElement('h4');
        h.className = 'h6 mb-1'; h.tabIndex = -1; h.textContent = title;
        heading.appendChild(h);
      }
      if (description) {
        var p = document.createElement('p');
        p.className = 'small text-muted mb-0'; p.textContent = description;
        heading.appendChild(p);
      }
      var closeButton = button('Cancel', 'btn btn-sm btn-outline-secondary');
      closeButton.addEventListener('click', closePanel);
      row.append(heading, closeButton);
      panel.appendChild(row);
      panel.hidden = false;
      if (!preserveInputFocus && !skipFocus) { if (h) h.focus(); else closeButton.focus(); }
    }
    function error(message) {
      var p = document.createElement('p');
      p.className = 'alert alert-warning py-2 mt-2 mb-0';
      p.setAttribute('role', 'alert'); p.textContent = message;
      panel.appendChild(p);
    }
    function selectedFor(axis) { return state.selected[axis.id] || []; }
    function isSelected(axis, option) { return selectedFor(axis).some(function (item) { return item.code === option.code; }); }
    function selectOption(axis, option) {
      var values = selectedFor(axis).slice();
      var policy = axis.allow_multiple_values;
      if (policy === 'AllowedExceptFromSameBlock') {
        var index = values.findIndex(function (item) { return item.code === option.code; });
        if (index !== -1) {
          values.splice(index, 1);
        } else {
          var sameBlock = values.findIndex(function (item) { return option.block_uri && item.block_uri === option.block_uri; });
          if (sameBlock === -1) values.push(option); else values.splice(sameBlock, 1, option);
        }
      } else if (policy === 'AllowAlways' || (!policy && axis.allow_multiple)) {
        var multipleIndex = values.findIndex(function (item) { return item.code === option.code; });
        if (multipleIndex === -1) values.push(option); else values.splice(multipleIndex, 1);
      } else {
        values = [option];
      }
      state.selected[axis.id] = values;
      renderPostcoordination({axis: axis.id, code: option.code});
    }
    function complete() {
      var axes = state.axes;
      var code = state.stem.code;
      var uri = state.stem.uri;
      var titles = [state.stem.title];
      function append(item) {
        // WHO uses slash for a causal/associated stem and ampersand for an
        // X extension. Preserve axis order while keeping both forms as one
        // complete expression.
        var separator = /^X/i.test(item.code) ? '&' : '/';
        if (item.code) code += separator + item.code;
        if (item.uri) uri += ' ' + separator + ' ' + item.uri;
        if (item.title) titles.push(item.title);
      }
      // WHO codeinfo canonicalises "stem & extensions / stem & extensions":
      // an "&" after a "/" belongs to that second stem. Every axis here
      // annotates the main stem, so emit X extensions first (axis order,
      // then "Other postcoordination"), then the "/" stems in axis order.
      var chosen = [];
      axes.forEach(function (axis) { selectedFor(axis).forEach(function (item) { chosen.push(item); }); });
      if (state.other_selected) chosen.push(state.other_selected);
      chosen.filter(function (item) { return /^X/i.test(item.code); }).forEach(append);
      chosen.filter(function (item) { return !/^X/i.test(item.code); }).forEach(append);
      return {code: code, uri: uri, title: titles.join('; '), selected_text: titles.join('; ')};
    }
    function requiredSatisfied() { return state.axes.every(function (axis) { return !axis.required || selectedFor(axis).length > 0; }); }
    function appendOptionList(axis, optionsList, parent) {
      list(optionsList).forEach(function (raw) {
        var option = optionValue(raw);
        if (!option.code && !option.title) return;
        var row = document.createElement('div');
        row.className = 'doris-axis-option d-flex flex-wrap gap-1 align-items-center mb-1';
        if (option.code && option.uri) {
          var choose = button(option.code + (option.title ? ' — ' + option.title : ''));
          choose.setAttribute('data-doris-option-axis', axis.id);
          choose.setAttribute('data-doris-option-code', option.code);
          choose.classList.toggle('active', isSelected(axis, option));
          choose.setAttribute('aria-pressed', isSelected(axis, option) ? 'true' : 'false');
          choose.addEventListener('click', function () { selectOption(axis, option); });
          row.appendChild(choose);
        } else {
          // Uncoded hierarchy node: expand-only, no select control, plain
          // "▷" marker to match WHO's own picker.
          var group = document.createElement('span');
          group.className = 'small text-muted';
          group.textContent = '▷ ' + option.title;
          row.appendChild(group);
        }
        var expansionKey = axis.id + '|' + option.uri;
        if (state.expanded[expansionKey]) {
          var loadedChildren = document.createElement('div');
          loadedChildren.className = 'doris-axis-children ms-3 mt-1';
          appendOptionList(axis, state.expanded[expansionKey], loadedChildren);
          row.appendChild(loadedChildren);
        } else if (option.has_children && option.uri) {
          var expand = button('More choices', 'btn btn-sm btn-link');
          expand.addEventListener('click', function () {
            expand.disabled = true;
            expand.textContent = 'Loading…';
            var id = requestId;
            transport.post('postcoordination-options', {schema_version: 1, stem_code: state.stem.code, axis_id: axis.id, parent_uri: option.uri}).then(function (data) {
              if (stale(id)) return;
              state.expanded[expansionKey] = list(data.items || data.options);
              if (data.truncated) markTruncated('More WHO options exist. Refine the search if the needed choice is not shown.');
              var previousScroll = panel.scrollTop;
              renderPostcoordination();
              panel.scrollTop = previousScroll;
            }).catch(function (err) {
              if (!stale(id)) { expand.disabled = false; expand.textContent = 'More choices'; error(err.message || 'More choices are unavailable.'); }
            });
          });
          row.appendChild(expand);
        }
        parent.appendChild(row);
      });
    }
    function markTruncated(message) {
      state.truncated = true;
      if (panel.querySelector('[data-doris-truncated]')) return;
      var warning = document.createElement('p');
      warning.className = 'alert alert-warning py-2 mt-2 mb-0';
      warning.setAttribute('role', 'alert'); warning.setAttribute('data-doris-truncated', ''); warning.textContent = message;
      panel.appendChild(warning);
    }
    // Scoped "search in axis" box shared by per-axis search and the
    // open-ended "Other postcoordination?" section. Debounces, guards
    // against stale panels via `stale()`, and renders matches as option
    // buttons via the supplied `onChoose`/`isActive` callbacks.
    function mountScopedSearch(subtreeUris, label, onChoose, isActive, onToggle) {
      var wrap = document.createElement('div');
      wrap.className = 'mt-1 mb-1';
      var input = document.createElement('input');
      input.type = 'search';
      input.className = 'form-control form-control-sm doris-axis-search';
      input.placeholder = 'search in axis: ' + label;
      input.setAttribute('aria-label', 'search in axis: ' + label);
      var results = document.createElement('div');
      results.className = 'doris-axis-search-results mt-1';
      var timer = null;
      input.addEventListener('input', function () {
        clearTimeout(timer);
        var query = text(input.value);
        if (query.length < 2) {
          results.replaceChildren();
          if (onToggle) onToggle(false);
          return;
        }
        timer = setTimeout(function () {
          var snapshot = requestId;
          transport.post('terms', {schema_version: 1, query: query, limit: 20, cursor: null, subtree_uris: subtreeUris}).then(function (data) {
            if (stale(snapshot)) return;
            if (onToggle) onToggle(true);
            results.replaceChildren();
            var items = list(data.items).filter(function (item) { return text(item.code) && text(item.uri); });
            if (!items.length) {
              var none = document.createElement('p');
              none.className = 'small text-muted mb-0'; none.textContent = 'No matches in this axis.';
              results.appendChild(none);
              return;
            }
            items.forEach(function (item) {
              var code = text(item.code), itemTitle = text(item.title), uri = text(item.uri);
              var choose = button(code + (itemTitle ? ' — ' + itemTitle : ''));
              choose.classList.toggle('active', isActive(code));
              choose.setAttribute('aria-pressed', isActive(code) ? 'true' : 'false');
              choose.addEventListener('click', function () { onChoose({code: code, title: itemTitle, uri: uri}, choose); });
              results.appendChild(choose);
            });
          }).catch(function (err) {
            if (!stale(snapshot)) { results.replaceChildren(); results.textContent = err.message || 'Search is unavailable.'; }
          });
        }, 250);
      });
      wrap.append(input, results);
      return wrap;
    }
    function renderPostcoordination(focusOption) {
      if (!state) return;
      // Re-rendering must not jump the scrolled panel back to the top:
      // keep the scroll offset and only move focus on the first render.
      var scroller = panel.closest('.doris-search-side') || panel.parentElement;
      var scrollTop = scroller ? scroller.scrollTop : 0;
      var rerender = Boolean(state.rendered);
      state.rendered = true;
      panel.replaceChildren();
      header('', '', rerender);
      var stem = document.createElement('p');
      stem.className = 'small mb-2';
      stem.textContent = 'Stem: ' + state.stem.code + ' — ' + state.stem.title;
      panel.appendChild(stem);
      state.axes.slice().sort(function (a, b) { return Number(b.required) - Number(a.required); }).forEach(function (axis) {
        var section = document.createElement('section');
        section.className = 'doris-axis border-top pt-2 mt-2';
        var heading = document.createElement('h5');
        heading.className = 'small fw-semibold';
        heading.textContent = axis.label + ' (' + (axis.instruction || (axis.required ? 'required' : 'optional')) + '.)';
        var multipleHint = document.createElement('span');
        multipleHint.className = 'text-muted fw-normal';
        multipleHint.textContent = ' ' + (axis.allow_multiple_values === 'AllowedExceptFromSameBlock'
          ? '(choose across different blocks)'
          : ((axis.allow_multiple_values === 'AllowAlways' || (!axis.allow_multiple_values && axis.allow_multiple)) ? '(choose one or more)' : '(choose one)'));
        heading.appendChild(multipleHint);
        section.appendChild(heading);
        var optionsHost = document.createElement('div');
        optionsHost.setAttribute('data-doris-axis-options', axis.id);
        appendOptionList(axis, axis.options, optionsHost);
        if (list(axis.subtree_uris).length) {
          section.appendChild(mountScopedSearch(axis.subtree_uris, axis.label, function (item) {
            selectOption(axis, {code: item.code, title: item.title, uri: item.uri, has_children: false, block_uri: item.uri});
          }, function (code) { return isSelected(axis, {code: code}); }, function (isActive) { optionsHost.hidden = isActive; }));
        }
        section.appendChild(optionsHost);
        if (axis.truncated) markTruncated('More WHO options exist. Refine the search if the needed choice is not shown.');
        panel.appendChild(section);
      });
      if (state.other_postcoordination) {
        var otherSection = document.createElement('section');
        otherSection.className = 'doris-axis border-top pt-2 mt-2';
        var otherHeading = document.createElement('h5');
        otherHeading.className = 'small fw-semibold';
        otherHeading.textContent = 'Other postcoordination? (use additional code, if desired.)';
        otherSection.appendChild(otherHeading);
        if (state.other_selected) {
          var chosenRow = document.createElement('div');
          chosenRow.className = 'doris-axis-option d-flex flex-wrap gap-1 align-items-center mb-1';
          var chosen = button(state.other_selected.code + (state.other_selected.title ? ' — ' + state.other_selected.title : ''));
          chosen.classList.add('active'); chosen.setAttribute('aria-pressed', 'true');
          chosen.addEventListener('click', function () { state.other_selected = null; renderPostcoordination(); });
          chosenRow.appendChild(chosen);
          otherSection.appendChild(chosenRow);
        }
        var otherAlert = document.createElement('p');
        otherAlert.className = 'alert alert-warning py-2 mt-2 mb-0';
        otherAlert.setAttribute('role', 'alert');
        otherAlert.hidden = true;
        otherSection.appendChild(mountScopedSearch(state.other_postcoordination.subtree_uris, 'Other postcoordination', function (item, chooseButton) {
          otherAlert.hidden = true;
          var snapshot = requestId;
          if (chooseButton) chooseButton.disabled = true;
          // WHO's own picker only accepts an open-ended extension pick once
          // codeinfo confirms "stem&code" resolves; not every WHO code is a
          // valid extension of every stem (verified against the live WHO API).
          transport.post('codeinfo', {schema_version: 1, code: state.stem.code + '&' + item.code}).then(function (data) {
            if (stale(snapshot)) return;
            state.other_selected = item;
            renderPostcoordination();
          }).catch(function (err) {
            if (stale(snapshot)) return;
            if (chooseButton) chooseButton.disabled = false;
            if (err.response && err.response.error && err.response.error.code === 'CODE_NOT_FOUND') {
              otherAlert.textContent = 'WHO does not accept ' + item.code + ' as an extension of ' + state.stem.code + '.';
            } else {
              otherAlert.textContent = err.message || 'The extension could not be verified.';
            }
            otherAlert.hidden = false;
          });
        }, function (code) { return Boolean(state.other_selected && state.other_selected.code === code); }, null));
        otherSection.appendChild(otherAlert);
        panel.appendChild(otherSection);
      }
      if (state.truncated) markTruncated('More WHO options exist. Refine the search if the needed choice is not shown.');
      var preview = complete();
      if (active && active.line === container && !active.selection) {
        // The modal footer is the stable area; show the live expression there.
        codeTitle(active.choice, preview.code, preview.title, 'Building: ', requiredSatisfied() ? '' : ' (required axis missing)');
      } else {
        var previewLabel = document.createElement('p');
        previewLabel.className = 'small mt-3 mb-1'; previewLabel.textContent = 'Complete code preview';
        var previewCode = document.createElement('code');
        previewCode.className = 'd-block text-break'; previewCode.textContent = preview.code;
        panel.append(previewLabel, previewCode);
      }
      var inFooter = Boolean(active && active.line === container && !active.selection);
      var actions = inFooter ? active.builderActions : document.createElement('div');
      actions.className = inFooter ? 'doris-footer-actions d-flex flex-wrap gap-2' : 'd-flex flex-wrap gap-2 mt-2';
      actions.replaceChildren();
      var use = button('Use complete expression', 'btn btn-sm btn-primary');
      use.setAttribute('data-doris-use-expression', '');
      use.disabled = !requiredSatisfied();
      use.addEventListener('click', function () {
        if (!requiredSatisfied()) return;
        stage(container, preview, statusElementFor(container));
        closePanel();
      });
      actions.appendChild(use);
      if (!state.axes.some(function (axis) { return axis.required; })) {
        var stemButton = button('Use stem without extensions', 'btn btn-sm btn-outline-primary');
        stemButton.setAttribute('data-doris-use-expression', '');
        stemButton.addEventListener('click', function () { stage(container, state.stem, statusElementFor(container)); closePanel(); });
        actions.appendChild(stemButton);
      }
      if (!inFooter) panel.appendChild(actions);
      if (focusOption) {
        var optionButtons = panel.querySelectorAll('[data-doris-option-axis]');
        for (var i = 0; i < optionButtons.length; i += 1) {
          if (optionButtons[i].getAttribute('data-doris-option-axis') === focusOption.axis &&
              optionButtons[i].getAttribute('data-doris-option-code') === focusOption.code) {
            optionButtons[i].focus({preventScroll: true});
            break;
          }
        }
      }
      if (rerender && scroller) scroller.scrollTop = scrollTop;
    }
    function renderHierarchy(data) {
      header('See in hierarchy', 'Explore the selected stem. Choosing a different node requires an explicit confirmation.');
      var selected = data.selected || {};
      var path = document.createElement('p'); path.className = 'small mb-2';
      path.textContent = 'Selected: ' + (selected.code || '') + (selected.title ? ' — ' + selected.title : '');
      panel.appendChild(path);
      if (data.selected_expression && data.selected_expression.code) {
        var fullExpression = document.createElement('p');
        fullExpression.className = 'small mb-2';
        fullExpression.textContent = 'Opened from complete expression: ' + data.selected_expression.code;
        panel.appendChild(fullExpression);
      }
      function choices(title, values) {
        var section = document.createElement('section');
        var heading = document.createElement('h5'); heading.className = 'small fw-semibold'; heading.textContent = title;
        section.appendChild(heading);
        var listNode = document.createElement('div'); listNode.className = 'list-group list-group-flush';
        list(values).forEach(function (item) {
          var value = optionValue(item);
          if (!value.code && !value.title) return;
          if (value.code) {
            var node = button(value.code + (value.title ? ' — ' + value.title : ''), 'list-group-item list-group-item-action text-start');
            node.addEventListener('click', function () { openHierarchy(value, node); });
            listNode.appendChild(node);
          } else {
            var label = document.createElement('div');
            label.className = 'list-group-item small text-muted'; label.textContent = '▷ ' + value.title;
            listNode.appendChild(label);
          }
        });
        section.appendChild(listNode); panel.appendChild(section);
      }
      choices('Ancestor path', data.ancestors);
      choices('Siblings', data.siblings);
      choices('Children', data.children);
      [['Maternal context', data.related_maternal], ['Perinatal context', data.related_perinatal]].forEach(function (entry) {
        if (!list(entry[1]).length) return;
        var p = document.createElement('p'); p.className = 'small mb-1'; p.textContent = entry[0] + ': ' + list(entry[1]).map(function (item) { return text(item.title || item); }).join('; '); panel.appendChild(p);
      });
      var use = button('Use this code', 'btn btn-sm btn-primary mt-2');
      use.disabled = !text(selected.code) || !text(selected.uri);
      use.addEventListener('click', function () { stage(container, {code: text(selected.code), uri: text(selected.uri), title: text(selected.title), selected_text: text(selected.title)}, statusElementFor(container)); closePanel(); });
      panel.appendChild(use);
      if (text(selected.code) && text(selected.uri)) {
        var build = button('Build expression for this stem', 'btn btn-sm btn-outline-primary mt-2 ms-2');
        build.addEventListener('click', function () { openStem(selected, build); });
        panel.appendChild(build);
      }
      if (data.truncated) { var p = document.createElement('p'); p.className = 'small text-muted mt-2 mb-0'; p.setAttribute('role', 'status'); p.textContent = 'Some hierarchy choices were omitted; refine the code if needed.'; panel.appendChild(p); }
    }
    function openHierarchy(item, trigger) {
      var id = ++requestId;
      stateRevision = currentRevision();
      if (!restoreTrigger) restoreTrigger = trigger || null;
      header('See in hierarchy', 'Loading the WHO hierarchy…');
      transport.post('hierarchy', {schema_version: 1, code: item.code}).then(function (data) {
        if (stale(id)) return;
        renderHierarchy(data);
      }).catch(function (err) { if (!stale(id)) error(err.message || 'The hierarchy is unavailable.'); });
    }
    function openStem(item, trigger, preserveFocus) {
      var id = ++requestId;
      stateRevision = currentRevision();
      restoreTrigger = trigger || null;
      preserveInputFocus = Boolean(preserveFocus);
      if (item && item.mode === 'hierarchy') { openHierarchy(item.item, trigger); return; }
      state = {stem: {code: text(item.code), title: text(item.title), uri: text(item.uri)}, axes: [], selected: {}, expanded: {}, truncated: false, other_postcoordination: null, other_selected: null};
      header('', '');
      transport.post('postcoordination', {schema_version: 1, code: item.code}).then(function (data) {
        if (stale(id)) return;
        state.stem = Object.assign(state.stem, data.stem || {});
        state.truncated = Boolean(data.truncated);
        state.axes = list(data.axes).map(function (axis) {
          return {id: text(axis.id || axis.name), label: text(axis.label || axis.name), instruction: text(axis.instruction), required: Boolean(axis.required), allow_multiple: Boolean(axis.allow_multiple), allow_multiple_values: text(axis.allow_multiple_values), options: list(axis.options), subtree_uris: list(axis.subtree_uris).map(text).filter(Boolean), truncated: Boolean(axis.truncated)};
        });
        var otherSubtrees = data.other_postcoordination ? list(data.other_postcoordination.subtree_uris).map(text).filter(Boolean) : [];
        state.other_postcoordination = otherSubtrees.length ? {subtree_uris: otherSubtrees} : null;
        // WHO's tool opens a composite result as its stem with the other
        // parts already chosen; preselect any part that is a root option.
        list(item.preselect).map(text).filter(Boolean).forEach(function (code) {
          state.axes.forEach(function (axis) {
            var match = list(axis.options).map(optionValue).find(function (option) { return option.code === code; });
            if (match && !isSelected(axis, match)) state.selected[axis.id] = selectedFor(axis).concat([match]);
          });
        });
        renderPostcoordination();
      }).catch(function (err) { if (!stale(id)) error(err.message || 'Postcoordination choices are unavailable.'); });
    }
    panel.addEventListener('keydown', function (event) { if (event.key === 'Escape') { event.preventDefault(); closePanel(); } });
    var controller = {open: openStem, close: closePanel, panel: panel};
    postcoordControllers.set(container, controller);
    return controller;
  }

  function openPostcoordination(container, item, trigger, preserveFocus) {
    var controller = postcoordController(container);
    if (controller) controller.open(item, trigger, preserveFocus);
  }
  function closePostcoordination(container) {
    var controller = postcoordControllers.get(container);
    if (controller) controller.close();
  }
  function isCompleteExpression(code) { return /[&/]/.test(text(code)); }
  // Every host's status/message element sits inside the container passed
  // to the picker, under one of these markers. Used only for the
  // postcoordination "Use" buttons below, where there is no host callback
  // in the loop to supply one explicitly (unlike the direct search-result
  // "Use"/heading paths, where the host already has it to hand).
  function statusElementFor(container) {
    return container.querySelector('[data-search-status], [data-doris-search-status], [data-doris-final-choice]');
  }

  window.addEventListener('pagehide', close);

  return {
    open: open, close: close, reset: reset,
    stage: stage, clearSelection: clearSelection,
    showDetails: showDetails, clearDetails: clearDetails,
    addContextIcons: addContextIcons, openRelated: openRelated,
    openPostcoordination: openPostcoordination, closePostcoordination: closePostcoordination,
    isCompleteExpression: isCompleteExpression
  };
}
