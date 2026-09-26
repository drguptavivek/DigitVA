(function (root) {
  'use strict';

  function text(value) { return typeof value === 'string' ? value.trim() : ''; }
  function expression(code) { return /[&/]/.test(text(code)); }
  function list(value) { return Array.isArray(value) ? value : []; }
  function button(label, className) {
    var node = document.createElement('button');
    node.type = 'button';
    node.className = className || 'btn btn-sm btn-outline-secondary';
    node.textContent = label;
    return node;
  }
  function safeUrl(value) { return typeof value === 'string' && value ? value : ''; }

  function mount(config) {
    var host = config.container;
    var panel = document.createElement('div');
    panel.className = 'doris-guided-panel border rounded p-3 mt-2';
    panel.hidden = true;
    panel.setAttribute('data-doris-guided-panel', '');
    host.replaceChildren(panel);
    var requestId = 0;
    var currentRevision = null;
    var restoreTrigger = null;
    var state = null;

    function stale(id) {
      if (id !== requestId) return true;
      if (typeof config.revision !== 'function') return false;
      return currentRevision !== config.revision();
    }
    function close() {
      requestId += 1;
      state = null;
      panel.hidden = true;
      panel.replaceChildren();
      if (restoreTrigger && typeof restoreTrigger.focus === 'function') restoreTrigger.focus();
      restoreTrigger = null;
    }
    function header(title, description) {
      panel.replaceChildren();
      var row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-start gap-2';
      var heading = document.createElement('div');
      var h = document.createElement('h4');
      h.className = 'h6 mb-1'; h.tabIndex = -1; h.textContent = title;
      heading.appendChild(h);
      if (description) {
        var p = document.createElement('p');
        p.className = 'small text-muted mb-0'; p.textContent = description;
        heading.appendChild(p);
      }
      var closeButton = button('Cancel', 'btn btn-sm btn-outline-secondary');
      closeButton.addEventListener('click', close);
      row.append(heading, closeButton);
      panel.appendChild(row);
      panel.hidden = false;
      h.focus();
    }
    function error(message) {
      var p = document.createElement('p');
      p.className = 'alert alert-warning py-2 mt-2 mb-0';
      p.setAttribute('role', 'alert'); p.textContent = message;
      panel.appendChild(p);
    }
    function loading(message) {
      var p = document.createElement('p');
      p.className = 'small text-muted mt-2 mb-0';
      p.setAttribute('role', 'status'); p.textContent = message;
      panel.appendChild(p);
    }
    function optionValue(option) {
      return {
        code: text(option && option.code), title: text(option && option.title),
        uri: text(option && option.uri), block_uri: text(option && option.block_uri),
        has_children: Boolean(option && option.has_children)
      };
    }
    function selectedFor(axis) {
      return state.selected[axis.id] || [];
    }
    function isSelected(axis, option) {
      return selectedFor(axis).some(function (item) { return item.code === option.code; });
    }
    function selectOption(axis, option) {
      var values = selectedFor(axis).slice();
      var policy = axis.allow_multiple_values;
      if (policy === 'AllowedExceptFromSameBlock') {
        var index = values.findIndex(function (item) { return item.code === option.code; });
        if (index !== -1) {
          values.splice(index, 1);
        } else {
          var sameBlock = values.findIndex(function (item) {
            return option.block_uri && item.block_uri === option.block_uri;
          });
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
      axes.forEach(function (axis) {
        selectedFor(axis).forEach(function (item) {
          // WHO uses slash for a causal/associated stem and ampersand for
          // an X extension. Preserve axis order while keeping both forms as
          // one complete expression.
          var separator = /^X/i.test(item.code) ? '&' : '/';
          if (item.code) code += separator + item.code;
          if (item.uri) uri += ' ' + separator + ' ' + item.uri;
          if (item.title) titles.push(item.title);
        });
      });
      return {
        code: code,
        uri: uri,
        title: titles.join('; '), selected_text: titles.join('; ')
      };
    }
    function requiredSatisfied() {
      return state.axes.every(function (axis) { return !axis.required || selectedFor(axis).length > 0; });
    }
    function appendOptionList(axis, options, parent) {
      list(options).forEach(function (raw) {
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
          var group = document.createElement('span');
          group.className = 'small text-muted';
          group.textContent = option.title + ' (choose a coded child)';
          row.appendChild(group);
        }
        var expansionKey = axis.id + '|' + option.uri;
        if (state.expanded[expansionKey]) {
          var loadedChildren = document.createElement('div');
          loadedChildren.className = 'ms-3 mt-1';
          appendOptionList(axis, state.expanded[expansionKey], loadedChildren);
          row.appendChild(loadedChildren);
        } else if (option.has_children && option.uri) {
          var expand = button('More choices', 'btn btn-sm btn-link');
          expand.addEventListener('click', function () {
            expand.disabled = true;
            var id = requestId;
            config.request(safeUrl(config.endpoints.options), {
              schema_version: 1, stem_code: state.stem.code,
              axis_id: axis.id, parent_uri: option.uri
            }).then(function (data) {
              if (stale(id)) return;
              state.expanded[expansionKey] = list(data.items || data.options);
              if (data.truncated) markTruncated('WHO returned more choices than this editor can display. Use a complete WHO expression or refine the code.');
              renderPostcoordination();
            }).catch(function (err) {
              if (!stale(id)) { expand.disabled = false; error(err.message || 'More choices are unavailable.'); }
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
      panel.querySelectorAll('[data-doris-use-expression]').forEach(function (node) { node.disabled = true; });
    }
    function renderPostcoordination(focusOption) {
      if (!state) return;
      panel.replaceChildren();
      header('Build complete ICD-11 expression', 'Choose WHO-allowed extensions. Required axes must be completed before selection.');
      var stem = document.createElement('p');
      stem.className = 'small mb-2';
      stem.textContent = 'Stem: ' + state.stem.code + ' — ' + state.stem.title;
      panel.appendChild(stem);
      state.axes.forEach(function (axis) {
        var section = document.createElement('section');
        section.className = 'doris-axis border-top pt-2 mt-2';
        var heading = document.createElement('h5');
        heading.className = 'small fw-semibold';
        var multipleLabel = axis.allow_multiple_values === 'AllowedExceptFromSameBlock'
          ? ' — choose across different blocks'
          : ((axis.allow_multiple_values === 'AllowAlways' || (!axis.allow_multiple_values && axis.allow_multiple)) ? ' — choose one or more' : ' — choose one');
        heading.textContent = axis.label + (axis.required ? ' (required)' : ' (optional)') + multipleLabel;
        section.appendChild(heading);
        var options = document.createElement('div');
        options.setAttribute('data-doris-axis-options', axis.id);
        appendOptionList(axis, axis.options, options);
        section.appendChild(options);
        if (axis.truncated) markTruncated('WHO returned more choices than this editor can display. Use a complete WHO expression or refine the code.');
        panel.appendChild(section);
      });
      if (state.truncated) markTruncated('WHO returned more choices than this editor can display. Use a complete WHO expression or refine the code.');
      var preview = complete();
      var previewLabel = document.createElement('p');
      previewLabel.className = 'small mt-3 mb-1'; previewLabel.textContent = 'Complete code preview';
      var previewCode = document.createElement('code');
      previewCode.className = 'd-block text-break'; previewCode.textContent = preview.code;
      panel.append(previewLabel, previewCode);
      var actions = document.createElement('div');
      actions.className = 'd-flex flex-wrap gap-2 mt-2';
      var use = button('Use complete expression', 'btn btn-sm btn-primary');
      use.setAttribute('data-doris-use-expression', '');
      use.disabled = !requiredSatisfied() || state.truncated;
      use.addEventListener('click', function () {
        if (!requiredSatisfied() || state.truncated) return;
        config.onSelect(preview);
        close();
      });
      actions.appendChild(use);
      if (!state.axes.some(function (axis) { return axis.required; })) {
        var stemButton = button('Use stem without extensions', 'btn btn-sm btn-outline-primary');
        stemButton.setAttribute('data-doris-use-expression', '');
        stemButton.disabled = state.truncated;
        stemButton.addEventListener('click', function () { if (state.truncated) return; config.onSelect(state.stem); close(); });
        actions.appendChild(stemButton);
      }
      panel.appendChild(actions);
      if (focusOption) {
        var options = panel.querySelectorAll('[data-doris-option-axis]');
        for (var i = 0; i < options.length; i += 1) {
          if (options[i].getAttribute('data-doris-option-axis') === focusOption.axis &&
              options[i].getAttribute('data-doris-option-code') === focusOption.code) {
            options[i].focus();
            break;
          }
        }
      }
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
            label.className = 'list-group-item small text-muted'; label.textContent = value.title + ' (uncoded hierarchy block)';
            listNode.appendChild(label);
          }
        });
        section.appendChild(listNode); panel.appendChild(section);
      }
      choices('Ancestor path', data.ancestors);
      choices('Siblings', data.siblings);
      choices('Children', data.children);
      [['Matching terms', data.matching_terms], ['Maternal context', data.related_maternal], ['Perinatal context', data.related_perinatal]].forEach(function (entry) {
        if (!list(entry[1]).length) return;
        var p = document.createElement('p'); p.className = 'small mb-1'; p.textContent = entry[0] + ': ' + list(entry[1]).map(function (item) { return text(item.title || item); }).join('; '); panel.appendChild(p);
      });
      var use = button('Use this code', 'btn btn-sm btn-primary mt-2');
      use.disabled = !text(selected.code) || !text(selected.uri);
      use.addEventListener('click', function () { config.onSelect({code: text(selected.code), uri: text(selected.uri), title: text(selected.title), selected_text: text(selected.title)}); close(); });
      panel.appendChild(use);
      if (text(selected.code) && text(selected.uri)) {
        var build = button('Build expression for this stem', 'btn btn-sm btn-outline-primary mt-2 ms-2');
        build.addEventListener('click', function () { open(selected, build); });
        panel.appendChild(build);
      }
      if (data.truncated) loading('Some hierarchy choices were omitted; refine the code if needed.');
    }
    function openHierarchy(item, trigger) {
      var id = ++requestId;
      currentRevision = typeof config.revision === 'function' ? config.revision() : null;
      if (!restoreTrigger) restoreTrigger = trigger || null;
      header('See in hierarchy', 'Loading the WHO hierarchy…');
      config.request(safeUrl(config.endpoints.hierarchy), {schema_version: 1, code: item.code}).then(function (data) {
        if (stale(id)) return;
        renderHierarchy(data);
      }).catch(function (err) { if (!stale(id)) error(err.message || 'The hierarchy is unavailable.'); });
    }
    function open(item, trigger) {
      var id = ++requestId;
      currentRevision = typeof config.revision === 'function' ? config.revision() : null;
      restoreTrigger = trigger || null;
      if (item && item.mode === 'hierarchy') { openHierarchy(item.item, trigger); return; }
      state = {stem: {code: text(item.code), title: text(item.title), uri: text(item.uri)}, axes: [], selected: {}, expanded: {}, truncated: false};
      header('Build complete ICD-11 expression', 'Loading WHO postcoordination axes…');
      config.request(safeUrl(config.endpoints.postcoordination), {schema_version: 1, code: item.code}).then(function (data) {
        if (stale(id)) return;
        state.stem = Object.assign(state.stem, data.stem || {});
        state.truncated = Boolean(data.truncated);
        state.axes = list(data.axes).map(function (axis) {
          return {id: text(axis.id || axis.name), label: text(axis.label || axis.name), required: Boolean(axis.required), allow_multiple: Boolean(axis.allow_multiple), allow_multiple_values: text(axis.allow_multiple_values), options: list(axis.options), truncated: Boolean(axis.truncated)};
        });
        renderPostcoordination();
      }).catch(function (err) { if (!stale(id)) error(err.message || 'Postcoordination choices are unavailable.'); });
    }
    panel.addEventListener('keydown', function (event) { if (event.key === 'Escape') { event.preventDefault(); close(); } });
    return {open: open, openHierarchy: openHierarchy, close: close, panel: panel};
  }

  root.DigitvaDorisPostcoordination = {mount: mount, isCompleteExpression: expression, version: 1};
}(window));
