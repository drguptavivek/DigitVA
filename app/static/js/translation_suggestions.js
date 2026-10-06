// Questionnaire translations for grant holders (digitva-5op): read the served
// translations beside the English and suggest a wording for one string. Fills
// #ts-root from /api/v1/translations/<project>/...; the server decides what the
// viewer may see and rechecks every suggestion. Every server string goes in
// through textContent.
(function () {
  'use strict';

  var root = document.getElementById('ts-root');
  if (!root || root.dataset.initialized) return;
  root.dataset.initialized = '1';

  var PAGE_SIZE = 25;
  var BASE = root.dataset.baseUrl;
  var state = { project: '', locale: '', page: 1, pages: 1, timer: null, token: 0 };

  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function showError(message) {
    var box = $('ts-error');
    box.textContent = message || '';
    box.classList.toggle('d-none', !message);
  }
  function getJson(url) {
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) throw new Error('failed');
        return response.json();
      });
  }

  // Every translatable string of one question row: the keys the suggestion
  // endpoint takes (item_kind / item_key / field) and what the reader sees.
  function stringsOf(q) {
    var out = [];
    if (q.english_label) {
      out.push({ label: 'Question', kind: 'question', key: q.name, field: 'label',
                 english: q.english_label, text: q.translated_label });
    }
    [['hint', 'hint', 'Hint'], ['constraint_message', 'constraint_message', 'Message'],
     ['guidance', 'guidance_hint', 'Guidance']].forEach(function (spec) {
      var part = q[spec[0]];
      if (part) {
        out.push({ label: spec[2], kind: 'question', key: q.name, field: spec[1],
                   english: part.english, text: part.translated });
      }
    });
    (q.choices || []).forEach(function (choice) {
      if (!choice.english) return;
      out.push({ label: 'Option', kind: 'choice', key: q.list_name + '/' + choice.value, field: 'label',
                 english: choice.english, text: choice.translated });
    });
    return out;
  }

  function suggestForm(item, holder) {
    holder.textContent = '';
    var form = el('div', 'mt-2 p-2 border rounded bg-light');
    var proposed = el('textarea', 'form-control form-control-sm mb-2');
    proposed.rows = 2; proposed.maxLength = 16000;
    proposed.placeholder = 'Your suggested wording';
    var reason = el('input', 'form-control form-control-sm mb-2');
    reason.type = 'text'; reason.maxLength = 1000; reason.placeholder = 'Why (required)';
    var status = el('div', 'small mb-2');
    var send = el('button', 'btn btn-sm btn-primary me-2', 'Send suggestion');
    send.type = 'button';
    var cancel = el('button', 'btn btn-sm btn-outline-secondary', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', function () { holder.textContent = ''; });
    send.addEventListener('click', function () {
      send.disabled = true;
      fetch(BASE + '/' + encodeURIComponent(state.project) + '/' + encodeURIComponent(state.locale) + '/suggestions', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf, Accept: 'application/json' },
        body: JSON.stringify({ item_kind: item.kind, item_key: item.key, field: item.field,
                               proposed_text: proposed.value, reason: reason.value })
      }).then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      }).then(function (result) {
        if (!result.ok) {
          status.className = 'small mb-2 text-danger';
          status.textContent = result.data.error || 'Could not send the suggestion.';
          send.disabled = false;
          return;
        }
        holder.textContent = '';
        holder.appendChild(el('div', 'small text-success mt-1', 'Suggestion sent. It will be reviewed.'));
      }).catch(function () {
        status.className = 'small mb-2 text-danger';
        status.textContent = 'Could not send the suggestion. Try again.';
        send.disabled = false;
      });
    });
    [proposed, reason, status, send, cancel].forEach(function (node) { form.appendChild(node); });
    holder.appendChild(form);
    proposed.focus();
  }

  function drawQuestion(q) {
    var card = el('div', 'border rounded p-2 mb-2');
    card.appendChild(el('div', 'small text-muted mb-1', q.name));
    stringsOf(q).forEach(function (item) {
      var row = el('div', 'row g-2 align-items-start border-top pt-1 mt-1');
      var en = el('div', 'col-md-5 small');
      en.appendChild(el('span', 'text-muted me-1', item.label));
      en.appendChild(el('span', '', item.english));
      var tr = el('div', 'col-md-5 small');
      if (item.text === null || item.text === undefined) {
        tr.appendChild(el('span', 'text-muted fst-italic', 'not yet translated'));
      } else {
        tr.appendChild(el('span', '', item.text));
      }
      var act = el('div', 'col-md-2 text-md-end');
      var holder = el('div', 'col-12');
      var btn = el('button', 'btn btn-sm btn-outline-primary', 'Suggest');
      btn.type = 'button';
      btn.addEventListener('click', function () { suggestForm(item, holder); });
      act.appendChild(btn);
      [en, tr, act, holder].forEach(function (node) { row.appendChild(node); });
      card.appendChild(row);
    });
    return card;
  }

  function loadPage() {
    if (!state.project || !state.locale) return;
    var token = ++state.token;
    var url = BASE + '/' + encodeURIComponent(state.project) + '/' + encodeURIComponent(state.locale) +
      '/questions?page=' + state.page + '&page_size=' + PAGE_SIZE +
      '&q=' + encodeURIComponent($('ts-q').value.trim());
    getJson(url).then(function (data) {
      if (token !== state.token) return;
      showError('');
      var rows = $('ts-rows');
      rows.textContent = '';
      data.items.forEach(function (q) {
        if (q.english_label || (q.choices && q.choices.length)) rows.appendChild(drawQuestion(q));
      });
      state.pages = Math.max(1, Math.ceil(data.total / data.page_size));
      $('ts-page').textContent = 'Page ' + data.page + ' of ' + state.pages + ' (' + data.total + ' questions)';
      $('ts-prev').disabled = data.page <= 1;
      $('ts-next').disabled = data.page >= state.pages;
    }).catch(function () { showError('Could not load the questionnaire. Try again.'); });
  }

  function loadLocales() {
    getJson(BASE + '/' + encodeURIComponent(state.project)).then(function (data) {
      var select = $('ts-locale');
      select.textContent = '';
      data.locales.forEach(function (l) { select.appendChild(new Option(l.label + ' (' + l.code + ')', l.code)); });
      $('ts-tab-review-item').classList.toggle('d-none', !data.can_decide);
      $('ts-empty').classList.toggle('d-none', data.locales.length > 0);
      $('ts-read').classList.toggle('d-none', !data.locales.length);
      state.locale = select.value;
      state.page = 1;
      loadPage();
    }).catch(function () { showError('Could not load the languages. Try again.'); });
  }

  function showTab(review) {
    $('ts-read').classList.toggle('d-none', review);
    $('ts-review').classList.toggle('d-none', !review);
    $('ts-tab-read').classList.toggle('active', !review);
    $('ts-tab-review').classList.toggle('active', review);
    if (review) {
      var queue = root.querySelector('[data-review-queue]');
      if (queue) queue.dispatchEvent(new CustomEvent('tsr:refresh'));
    }
  }

  $('ts-tab-read').addEventListener('click', function () { showTab(false); });
  $('ts-tab-review').addEventListener('click', function () { showTab(true); });
  $('ts-project').addEventListener('change', function () { state.project = this.value; loadLocales(); });
  $('ts-locale').addEventListener('change', function () { state.locale = this.value; state.page = 1; loadPage(); });
  $('ts-prev').addEventListener('click', function () { if (state.page > 1) { state.page -= 1; loadPage(); } });
  $('ts-next').addEventListener('click', function () { if (state.page < state.pages) { state.page += 1; loadPage(); } });
  $('ts-q').addEventListener('input', function () {
    clearTimeout(state.timer);
    state.timer = setTimeout(function () { state.page = 1; loadPage(); }, 300);
  });

  getJson(root.dataset.projectsUrl).then(function (data) {
    var projects = data.projects || [];
    if (!projects.length) {
      $('ts-empty').classList.remove('d-none');
      $('ts-read').classList.add('d-none');
      return;
    }
    var select = $('ts-project');
    projects.forEach(function (p) { select.appendChild(new Option(p.project_name + ' (' + p.project_id + ')', p.project_id)); });
    state.project = select.value;
    loadLocales();
  }).catch(function () { showError('Could not load your projects. Try again.'); });
})();
