// Example loader for the public DORIS demo. The editor itself is doris_clinical.js; this only fills
// the "Synthetic example" list and asks the editor to reload from a chosen example (editor._dorisReload).
(function () {
  'use strict';
  var app = document.getElementById('doris-demo-page');
  var select = document.getElementById('doris-example');
  var purpose = document.getElementById('doris-example-purpose');
  var examples = [];

  function show(example) {
    var editor = app.querySelector('[data-doris-editor]');
    if (!editor || !editor._dorisReload) return;
    purpose.hidden = !example; purpose.textContent = example ? example.purpose : '';
    editor._dorisReload(example ? example.certificate : {});
  }

  fetch(app.dataset.configUrl, {credentials: 'same-origin'}).then(function (response) {
    if (!response.ok) throw new Error('unavailable');
    return response.json();
  }).then(function (data) {
    examples = Array.isArray(data.examples) ? data.examples : [];
    examples.forEach(function (example) {
      var option = document.createElement('option'); option.value = example.id; option.textContent = example.label; select.appendChild(option);
    });
  }).catch(function () { purpose.hidden = false; purpose.textContent = 'The synthetic examples are unavailable. You can still fill the certificate by hand.'; });

  document.getElementById('doris-load-example').addEventListener('click', function () {
    show(examples.find(function (item) { return item.id === select.value; }));
  });
  document.getElementById('doris-new').addEventListener('click', function () { select.value = ''; show(null); });
}());
