/**
 * Embedded ICD-11 picker host for the Expo app. Runs inside
 * /static/doris_picker_host.html, which the app shows in an iframe (browser
 * build) or a WebView (native). It reuses createIcd11Picker and its shared
 * result rows unchanged; this file is only the host glue.
 *
 * The page never sees credentials or a case id. Every WHO call is a message
 * to the app, which maps `path` + `body` onto its authenticated API client:
 *
 *   app -> page  {t:'init', title, accent, revision, allowUncoded, query?, finalMode?}
 *                {t:'search', query}   fill the search box and search now
 *                {t:'revision', value}
 *                {t:'res', id, ok:true, data} | {t:'res', id, ok:false, error:{code,message,status}}
 *                {t:'ping'}  (web) page re-sends ready if not yet initialised
 *   page -> app  {t:'ready'} (repeated every second until init) {t:'req', id, path, body} {t:'select', choice}
 *                {t:'uncoded', text} {t:'close'}
 *
 * URL params (host page): `theme` dark|light (colour scheme, handled in the
 * HTML) and `q` (term to search when the modal opens; an init `query` wins).
 *
 * Browser: window.postMessage with the parent frame (same origin only).
 * Native: React Native WebView postMessage out, and the app calls
 * window.__digitvaEmbedReceive(message) in.
 */
import { createIcd11Picker } from './digitva_icd11_picker.js?v=5';

var native = typeof window.ReactNativeWebView === 'object' && window.ReactNativeWebView;
var root = document.getElementById('doris-embed');
var revision = null;
var pending = new Map();
var nextId = 1;
var searchToken = 0;
var finalMode = false;
var timer = null;
var urlQuery = (new URLSearchParams(window.location.search).get('q') || '').slice(0, 80);
var opened = false;

function send(message) {
  if (native) native.postMessage(JSON.stringify(message));
  else window.parent.postMessage(message, window.location.origin);
}

var transport = {
  post: function (path, body) {
    return new Promise(function (resolve, reject) {
      var id = nextId++;
      pending.set(id, {resolve: resolve, reject: reject});
      send({t: 'req', id: id, path: path, body: body});
    });
  }
};

function settle(message) {
  var entry = pending.get(message.id);
  if (!entry) return;
  pending.delete(message.id);
  if (message.ok) { entry.resolve(message.data); return; }
  var failure = message.error || {};
  var error = new Error(failure.message || 'Request failed');
  // The picker tells "code not found" from a real failure by this shape.
  error.response = {error: {code: failure.code || 'REQUEST_FAILED', message: error.message}};
  error.status = failure.status;
  entry.reject(error);
}

var line = document.createElement('div');
line.className = 'border rounded p-3 doris-line-accented';
line.setAttribute('data-doris-line', '');
line.innerHTML =
  '<div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2 doris-search-head"><strong data-doris-line-title></strong></div>' +
  '<div class="input-group"><input class="form-control" maxlength="80" autocomplete="off" placeholder="Search a condition or ICD-11 code" data-doris-search>' +
  '<button type="button" class="btn btn-outline-secondary" data-doris-search-button>Search</button>' +
  '<button type="button" class="btn btn-outline-secondary" data-doris-add-uncoded hidden>Add uncoded text</button></div>' +
  '<div class="doris-search-workspace"><div class="doris-search-list-wrap"><p class="small text-muted mb-0 mt-1" role="status" data-doris-search-status></p><div class="list-group mt-1" data-doris-search-results></div></div>' +
  '<div class="doris-search-side"><div class="doris-code-details" data-doris-details-panel hidden></div><div data-doris-guided-panel></div></div></div>';
root.appendChild(line);
var input = line.querySelector('[data-doris-search]');
var resultList = line.querySelector('[data-doris-search-results]');
var statusEl = line.querySelector('[data-doris-search-status]');
var uncodedButton = line.querySelector('[data-doris-add-uncoded]');

var picker = createIcd11Picker({
  mount: root,
  transport: transport,
  revision: function () { return revision; },
  onSelect: function (choice) { send({t: 'select', choice: choice}); },
  onClose: function () { clearTimeout(timer); searchToken += 1; send({t: 'close'}); }
});

function search() {
  var value = input.value.trim();
  picker.clearPanels(line);
  resultList.replaceChildren();
  if (value.length < 2) { statusEl.textContent = 'Type at least 2 characters.'; return; }
  var token = ++searchToken;
  var sent = revision;
  statusEl.textContent = 'Searching…';
  var looksCode = /\d/.test(value) && !/\s/.test(value);
  var request = looksCode
    ? transport.post('codeinfo', {schema_version: 1, code: value}).then(function (data) { return data.item ? [data.item] : []; })
    : transport.post('terms', {schema_version: 1, query: value, limit: 20, cursor: null}).then(function (data) { return data.items || []; });
  request.then(function (items) {
    if (token !== searchToken || sent !== revision || value !== input.value.trim()) return;
    picker.renderResults(line, items, {input: input, statusEl: statusEl, resultList: resultList, finalMode: finalMode, onRequery: search});
  }).catch(function (error) {
    if (token === searchToken && sent === revision) statusEl.textContent = error.message;
  });
}

function reset() {
  clearTimeout(timer); searchToken += 1;
  resultList.replaceChildren();
  statusEl.textContent = '';
  picker.closePostcoordination(line);
}

input.addEventListener('input', function () {
  picker.clearSelection(line); picker.clearDetails(line); clearTimeout(timer);
  if (input.value.trim().length >= 2) timer = setTimeout(search, 250);
  else { searchToken += 1; resultList.replaceChildren(); picker.closePostcoordination(line); }
});
input.addEventListener('keydown', function (event) {
  if (event.key === 'Enter') { event.preventDefault(); clearTimeout(timer); search(); }
});
line.querySelector('[data-doris-search-button]').addEventListener('click', function () { clearTimeout(timer); search(); });
uncodedButton.addEventListener('click', function () {
  var value = input.value.trim();
  if (!value) { statusEl.textContent = 'Enter the condition text first.'; return; }
  send({t: 'uncoded', text: value});
  picker.close();
});

// Put a term in the search box and run the search now (no debounce).
function searchFor(term) {
  clearTimeout(timer);
  picker.clearSelection(line); picker.clearDetails(line);
  input.value = String(term || '').slice(0, 80);
  if (input.value.trim().length >= 2) search(); else reset();
}

function receive(message) {
  if (!message || typeof message !== 'object') return;
  if (message.t === 'res') settle(message);
  else if (message.t === 'revision') revision = message.value;
  else if (message.t === 'init') {
    // A repeated ready can draw a second init; it must not wipe the user's search.
    if (initialised) return;
    initialised = true;
    revision = message.revision;
    line.querySelector('[data-doris-line-title]').textContent = String(message.title || 'Find an ICD-11 condition');
    if (typeof message.accent === 'string' && /^#[0-9a-fA-F]{6}$/.test(message.accent)) line.style.setProperty('--doris-line-accent', message.accent);
    uncodedButton.hidden = !message.allowUncoded;
    reset();
    finalMode = Boolean(message.finalMode);
    input.value = typeof message.query === 'string' ? message.query.slice(0, 80) : urlQuery;
    picker.open(line, input, null, reset);
    opened = true;
    if (input.value.trim().length >= 2) search();
  } else if (message.t === 'search' && typeof message.query === 'string') {
    if (opened) searchFor(message.query); else urlQuery = message.query.slice(0, 80);
  }
}

// "ready" is one-shot, so a parent whose listener attached late would never answer.
// Repeat it until init arrives; the parent's {t:'ping'} (after iframe onLoad) asks for it now.
var initialised = false;
var readyTimer = null;
function announce() {
  if (initialised) { clearInterval(readyTimer); return; }
  send({t: 'ready'});
}

window.__digitvaEmbedReceive = receive;
window.addEventListener('message', function (event) {
  // Browser build only: accept the parent frame on our own origin.
  if (native || event.source !== window.parent || event.origin !== window.location.origin) return;
  if (event.data && event.data.t === 'ping') { announce(); return; }
  receive(event.data);
});
announce();
readyTimer = setInterval(announce, 1000);
