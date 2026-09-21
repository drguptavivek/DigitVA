/*
 * Shared rich-text editor (Quill 2, vendored in app/static/vendor/quill/).
 *
 *   DigitVARichText.attach(containerEl, { initialHtml, onChange })
 *     -> Promise<{ getHtml(), setHtml(html), quill }>
 *
 * One toolbar for every rich-text field: bold, italic, bullet list, numbered
 * list, outdent, indent. getHtml() returns Quill's semantic HTML, where indent
 * is nested <ul>/<ol>, so it fits the server allowlist in
 * app/utils/rich_text.py (p, br, ul, ol, li, strong, b, em, i; no
 * attributes). The server sanitizes every save and returns the stored HTML;
 * callers setHtml() it back so the admin sees exactly what was kept.
 * Quill's assets load once per page, however many panels attach editors.
 */
(function () {
  if (window.DigitVARichText) return;

  var script = document.currentScript;
  var suffix = script && script.src.indexOf('?') !== -1 ? script.src.slice(script.src.indexOf('?')) : '';
  var base = script ? script.src.replace(/js\/rich_text_editor\.js.*$/, 'vendor/quill/') : '/static/vendor/quill/';
  var ASSETS = { css: base + 'quill.snow.css' + suffix, js: base + 'quill.js' + suffix };

  var TOOLBAR = [
    ['bold', 'italic'],
    [{ list: 'bullet' }, { list: 'ordered' }],
    [{ indent: '-1' }, { indent: '+1' }]
  ];
  var FORMATS = ['bold', 'italic', 'list', 'indent'];

  var _quillLoad = null;
  function loadQuill() {
    if (!document.querySelector('link[href="' + ASSETS.css + '"]')) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = ASSETS.css;
      document.head.appendChild(link);
    }
    if (window.Quill) return Promise.resolve(window.Quill);
    if (!_quillLoad) {
      _quillLoad = new Promise(function (resolve, reject) {
        var el = document.createElement('script');
        el.src = ASSETS.js;
        el.onload = function () { resolve(window.Quill); };
        el.onerror = function () { _quillLoad = null; el.remove(); reject(new Error('Quill failed to load')); };
        document.head.appendChild(el);
      });
    }
    return _quillLoad;
  }

  function attach(container, options) {
    options = options || {};
    return loadQuill().then(function (Quill) {
      container.textContent = '';
      var quill = new Quill(container, {
        theme: 'snow',
        modules: { toolbar: TOOLBAR },
        formats: FORMATS
      });
      var handle = {
        quill: quill,
        getHtml: function () {
          return quill.getText().trim() ? quill.getSemanticHTML() : '';
        },
        setHtml: function (html) {
          quill.setContents(quill.clipboard.convert({ html: html || '' }), 'silent');
          quill.history.clear();
        }
      };
      handle.setHtml(options.initialHtml);
      if (options.onChange) {
        quill.on('text-change', function () { options.onChange(handle.getHtml()); });
      }
      return handle;
    });
  }

  window.DigitVARichText = { attach: attach, TOOLBAR: TOOLBAR };
})();
