// Pending translation suggestions (digitva-5op): fills every [data-review-queue]
// from GET /api/v1/translations/suggestions and posts Accept / Reject. The
// server decides what the viewer may decide and rechecks everything; every
// server string goes in through textContent. `total` is the pending badge.
(function () {
  'use strict';

  var PAGE = 25;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function setBadges(total) {
    var badges = document.querySelectorAll('[data-pending-badge]');
    for (var i = 0; i < badges.length; i++) {
      badges[i].textContent = String(total);
      badges[i].classList.toggle('d-none', !total);
    }
  }

  function mount(root) {
    if (root.dataset.initialized) return;
    root.dataset.initialized = '1';
    var list = root.querySelector('[data-queue-list]');
    var empty = root.querySelector('[data-queue-empty]');
    var more = root.querySelector('[data-queue-more]');
    var errorBox = root.querySelector('[data-queue-error]');
    var offset = 0;

    function csrf() { return root.dataset.csrf || window._adminCsrf || ''; }
    function showError(message) {
      errorBox.textContent = message || '';
      errorBox.classList.toggle('d-none', !message);
    }
    function field(label, value, className) {
      var line = el('div', 'small mb-1');
      line.appendChild(el('span', 'text-muted me-1', label));
      line.appendChild(el('span', className || '', value === null || value === undefined ? 'not yet translated' : value));
      return line;
    }

    function decide(item, card, verb, noteInput) {
      var url = root.dataset[verb + 'Url'].replace('/0/', '/' + item.id + '/');
      if (verb === 'accept' && !window.confirm(
        'Accepting changes this language for all projects that use it. Continue?')) return;
      fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), Accept: 'application/json' },
        body: JSON.stringify({ note: noteInput.value })
      }).then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      }).then(function (result) {
        if (!result.ok) { showError(result.data.error || 'Could not save the decision.'); return; }
        showError('');
        card.remove();
        load(true);
      }).catch(function () { showError('Could not save the decision. Try again.'); });
    }

    function draw(item) {
      var card = el('div', 'border rounded p-2 mb-2');
      card.appendChild(el('div', 'fw-semibold small',
        item.language + ' (' + item.locale + ') - ' + item.item_key + ' / ' + item.field + ' - project ' + item.project_id));
      card.appendChild(field('English', item.english));
      card.appendChild(field('Current', item.current_text));
      card.appendChild(field('Suggested', item.proposed_text, 'fw-bold'));
      card.appendChild(field('Reason', item.reason));
      var when = item.suggested_at ? new Date(item.suggested_at).toLocaleString() : '';
      card.appendChild(el('div', 'small text-muted mb-2', 'Suggested by ' + item.suggested_by + (when ? ' on ' + when : '')));
      if (item.stale) {
        card.appendChild(el('div', 'small text-danger mb-2',
          'The translation changed since this was suggested. It cannot be accepted; reject it.'));
      }
      var note = el('input', 'form-control form-control-sm mb-2');
      note.type = 'text'; note.maxLength = 1000; note.placeholder = 'Note (optional)';
      card.appendChild(note);
      var accept = el('button', 'btn btn-sm btn-success me-2', 'Accept (changes this language for all projects)');
      accept.type = 'button'; accept.disabled = !!item.stale;
      accept.addEventListener('click', function () { decide(item, card, 'accept', note); });
      var reject = el('button', 'btn btn-sm btn-outline-danger', 'Reject');
      reject.type = 'button';
      reject.addEventListener('click', function () { decide(item, card, 'reject', note); });
      card.appendChild(accept);
      card.appendChild(reject);
      return card;
    }

    function load(reset) {
      if (reset) { offset = 0; list.textContent = ''; }
      fetch(root.dataset.queueUrl + '?limit=' + PAGE + '&offset=' + offset,
        { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (response) {
          if (response.status === 403) { root.classList.add('d-none'); return null; }
          if (!response.ok) throw new Error('failed');
          return response.json();
        })
        .then(function (data) {
          if (!data) return;
          showError('');
          data.items.forEach(function (item) { list.appendChild(draw(item)); });
          offset += data.items.length;
          setBadges(data.total);
          empty.classList.toggle('d-none', data.total > 0);
          more.classList.toggle('d-none', offset >= data.total);
        })
        .catch(function () { showError('Could not load the suggestions. Try again.'); });
    }

    more.addEventListener('click', function () { load(false); });
    root.addEventListener('tsr:refresh', function () { load(true); });
    load(true);
  }

  var roots = document.querySelectorAll('[data-review-queue]');
  for (var i = 0; i < roots.length; i++) mount(roots[i]);
})();
