(function (root) {
  'use strict';

  var UNITS = [
    {value: 'Y', label: 'Years', prefix: 'P'},
    {value: 'M', label: 'Months', prefix: 'P'},
    {value: 'W', label: 'Weeks', prefix: 'P'},
    {value: 'D', label: 'Days', prefix: 'P'},
    {value: 'H', label: 'Hours', prefix: 'PT'},
    {value: 'MI', label: 'Minutes', prefix: 'PT'},
    {value: 'S', label: 'Seconds', prefix: 'PT'}
  ];

  function trim(value) { return typeof value === 'string' ? value.trim() : ''; }

  function parse(rawValue) {
    var raw = typeof rawValue === 'string' ? rawValue : '';
    var value = trim(raw);
    var match = value.match(/^P(\d+(?:\.\d+)?)(Y|M|W|D)$/);
    if (!match) {
      match = value.match(/^PT(\d+(?:\.\d+)?)(H|M|S)$/);
      if (match && match[2] === 'M') match[2] = 'MI';
    }
    if (match) {
      return {raw: raw, value: match[1], unit: match[2], representable: true};
    }
    if (value === 'P' || value === 'PT') {
      return {raw: raw, value: '', unit: 'unknown', representable: true, unknown: true};
    }
    return {raw: raw, value: '', unit: '', representable: false};
  }

  function validNumber(value) {
    return /^\d+(?:\.\d+)?$/.test(value) && Number(value) >= 0;
  }

  function serialize(value, unit) {
    var number = trim(value);
    var selected = trim(unit);
    if (selected === '' && number === '') return {value: '', error: ''};
    if (selected === 'unknown' && number === '') return {value: '', error: ''};
    if (selected === '' && number !== '') return {value: '', error: 'Choose a time unit for the interval.'};
    if (selected !== 'unknown' && !validNumber(number)) {
      return {value: '', error: 'Enter a non-negative decimal interval without an exponent.'};
    }
    if (selected === 'unknown' && number !== '') {
      return {value: '', error: 'Remove the interval value or choose a time unit.'};
    }
    var unit = UNITS.find(function (item) { return item.value === selected; });
    if (!unit) return {value: '', error: 'Choose a valid time unit for the interval.'};
    return {value: unit.prefix + number + (selected === 'MI' ? 'M' : unit.value), error: ''};
  }

  function options(select) {
    if (!select || select.options.length) return;
    var blank = document.createElement('option');
    blank.value = ''; blank.textContent = 'Select unit';
    select.appendChild(blank);
    UNITS.forEach(function (unit) {
      var option = document.createElement('option');
      option.value = unit.value; option.textContent = unit.label;
      select.appendChild(option);
    });
    var unknown = document.createElement('option');
    unknown.value = 'unknown'; unknown.textContent = 'Unknown';
    select.appendChild(unknown);
  }

  function mount(container, rawValue) {
    var valueInput = container.querySelector('[data-interval-value], [data-doris-interval-value]');
    var unitSelect = container.querySelector('[data-interval-unit], [data-doris-interval-unit]');
    var rawDisplay = container.querySelector('[data-interval-raw], [data-doris-interval-raw]');
    var errorDisplay = container.querySelector('[data-interval-error], [data-doris-interval-error]');
    var parsed = parse(rawValue);
    var state = {raw: typeof rawValue === 'string' ? rawValue : '', dirty: false};
    options(unitSelect);
    valueInput.value = parsed.representable ? parsed.value : '';
    unitSelect.value = parsed.representable ? parsed.unit : '';
    if (rawDisplay) {
      rawDisplay.textContent = parsed.representable || !state.raw ? '' : 'Existing interval: ' + state.raw;
      rawDisplay.hidden = parsed.representable || !state.raw;
    }
    function edited() {
      state.dirty = true;
      if (rawDisplay) { rawDisplay.hidden = true; rawDisplay.textContent = ''; }
      if (errorDisplay) errorDisplay.textContent = '';
    }
    valueInput.addEventListener('input', edited);
    unitSelect.addEventListener('change', edited);
    return {
      read: function () {
        if (!state.dirty) return {value: state.raw, error: ''};
        var result = serialize(valueInput.value, unitSelect.value);
        if (errorDisplay) errorDisplay.textContent = result.error;
        return result;
      },
      validate: function () { return this.read(); },
      state: state,
      value: valueInput,
      unit: unitSelect
    };
  }

  root.DigitvaDorisInterval = {parse: parse, serialize: serialize, mount: mount, units: UNITS};
}(typeof window === 'undefined' ? globalThis : window));
