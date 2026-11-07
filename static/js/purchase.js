/* Purchase order form: dynamic part rows with live totals. */
(function () {
  'use strict';
  var parts = JSON.parse(document.getElementById('partsData').textContent), prefill = JSON.parse(document.getElementById('prefillData').textContent);
  var body = document.getElementById('poBody');
  function row(sel) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><select name="part_id" class="form-select form-select-sm" required><option value="">Choose part...</option>' +
      parts.map(function (p) { return '<option value="' + p.id + '">' + MSPMS.esc(p.label) + '</option>'; }).join('') + '</select></td>' +
      '<td style="width:110px"><input type="number" name="qty" min="1" value="' + (sel ? sel.qty : 1) + '" class="form-control form-control-sm" required></td>' +
      '<td style="width:140px"><input type="number" name="unit_cost" min="0" step="0.01" value="' + (sel ? sel.cost : 0) + '" class="form-control form-control-sm" required></td>' +
      '<td class="text-end gst">-</td><td class="text-end amt fw-semibold">-</td><td><button type="button" class="btn btn-sm btn-outline-danger" aria-label="Remove"><i class="bi bi-x-lg"></i></button></td>';
    if (sel) tr.querySelector('select').value = sel.id;
    body.appendChild(tr); calc();
  }
  function calc() {
    var total = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var pid = tr.querySelector('select').value, p = parts.find(function (x) { return String(x.id) === pid; });
      var q = parseFloat(tr.querySelector('[name=qty]').value) || 0, c = parseFloat(tr.querySelector('[name=unit_cost]').value) || 0;
      var amt = p ? q * c * (1 + p.gst / 100) : q * c; total += amt;
      tr.querySelector('.gst').textContent = p ? p.gst + '%' : '-'; tr.querySelector('.amt').textContent = MSPMS.inr(amt);
    });
    document.getElementById('poTotal').textContent = MSPMS.inr(total);
  }
  body.addEventListener('input', calc);
  body.addEventListener('change', function (e) {
    if (e.target.tagName === 'SELECT') { var p = parts.find(function (x) { return String(x.id) === e.target.value; }); if (p) e.target.closest('tr').querySelector('[name=unit_cost]').value = p.cost; }
    calc();
  });
  body.addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { b.closest('tr').remove(); calc(); } });
  document.getElementById('addRow').addEventListener('click', function () { row(null); });
  (prefill.length ? prefill : [null]).forEach(row);
})();
