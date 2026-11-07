/* Sales / billing screen: search or scan parts, build cart, live totals. */
(function () {
  'use strict';
  var cart = {}, form = document.getElementById('saleForm'), body = document.getElementById('cartBody'), loc = document.getElementById('location_id');
  function stockAt(p) { return (p.stock && p.stock[loc.value]) || 0; }
  function add(p) {
    if (cart[p.id]) cart[p.id].qty += 1; else cart[p.id] = { p: p, qty: 1 };
    render();
  }
  function totals() {
    var sub = 0; Object.values(cart).forEach(function (l) { sub += l.qty * l.p.price; });
    var dv = parseFloat(document.getElementById('discount').value) || 0, pct = document.getElementById('discount_type').value === 'percent';
    var disc = Math.min(pct ? sub * dv / 100 : dv, sub), ratio = sub ? disc / sub : 0, gst = 0;
    Object.values(cart).forEach(function (l) { gst += l.qty * l.p.price * (1 - ratio) * l.p.gst / 100; });
    return { sub: sub, disc: disc, gst: gst, total: sub - disc + gst };
  }
  function render() {
    var ids = Object.keys(cart);
    body.innerHTML = ids.length ? ids.map(function (id) {
      var l = cart[id], av = stockAt(l.p), bad = l.qty > av;
      return '<tr><td><div class="fw-semibold">' + MSPMS.esc(l.p.name) + '</div><small class="text-muted">' + MSPMS.esc(l.p.part_no) + ' &middot; ' + (bad ? '<span class="text-danger">only ' + av + ' here</span>' : av + ' available') + '</small>' +
        '<input type="hidden" name="part_id" value="' + id + '"></td><td class="text-end">' + MSPMS.inr(l.p.price) + '</td>' +
        '<td style="width:100px"><input type="number" min="1" name="qty" class="form-control form-control-sm ' + (bad ? 'is-invalid' : '') + '" value="' + l.qty + '" data-id="' + id + '"></td>' +
        '<td class="text-end">' + l.p.gst + '%</td><td class="text-end fw-semibold">' + MSPMS.inr(l.qty * l.p.price) + '</td>' +
        '<td><button type="button" class="btn btn-sm btn-outline-danger" data-rm="' + id + '" aria-label="Remove"><i class="bi bi-x-lg"></i></button></td></tr>';
    }).join('') : '<tr><td colspan="6" class="text-center text-muted py-4">Search or scan a part to start the bill.</td></tr>';
    var t = totals();
    document.getElementById('t_sub').textContent = MSPMS.inr(t.sub); document.getElementById('t_disc').textContent = '- ' + MSPMS.inr(t.disc);
    document.getElementById('t_gst').textContent = MSPMS.inr(t.gst); document.getElementById('t_total').textContent = MSPMS.inr(t.total);
    var paid = document.getElementById('paid_amount'), mode = document.getElementById('payment_mode').value;
    if (!paid.dataset.touched) paid.value = mode === 'Credit' ? '0' : t.total.toFixed(2);
  }
  body.addEventListener('input', function (e) { var id = e.target.dataset.id; if (id) { cart[id].qty = Math.max(parseInt(e.target.value) || 1, 1); renderTotalsOnly(); } });
  body.addEventListener('change', render);
  function renderTotalsOnly() { var keep = document.activeElement; var id = keep && keep.dataset.id; render(); if (id) { var n = body.querySelector('[data-id="' + id + '"]'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } } }
  body.addEventListener('click', function (e) { var b = e.target.closest('[data-rm]'); if (b) { delete cart[b.dataset.rm]; render(); } });
  ['discount', 'discount_type', 'payment_mode', 'location_id'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', function () { if (id === 'payment_mode') delete document.getElementById('paid_amount').dataset.touched; render(); });
  });
  document.getElementById('paid_amount').addEventListener('input', function () { this.dataset.touched = '1'; });

  var q = document.getElementById('partSearch'), drop = document.getElementById('partDrop');
  q.addEventListener('input', MSPMS.debounce(function () {
    var v = q.value.trim(); if (v.length < 2) { drop.style.display = 'none'; return; }
    MSPMS.getJSON('/api/parts/search?q=' + encodeURIComponent(v)).then(function (rows) {
      drop.innerHTML = rows.length ? rows.map(function (p, i) {
        return '<button type="button" data-i="' + i + '"><span>' + MSPMS.esc(p.name) + '<br><small class="text-muted">' + MSPMS.esc(p.part_no) + '</small></span><span class="text-end">' + MSPMS.inr(p.price) + '<br><small class="text-muted">' + (p.stock[loc.value] || 0) + ' here</small></span></button>';
      }).join('') : '<div class="p-3 text-muted">No parts found</div>';
      drop._rows = rows; drop.style.display = 'block';
    });
  }, 250));
  drop.addEventListener('click', function (e) { var b = e.target.closest('button[data-i]'); if (b) { add(drop._rows[b.dataset.i]); q.value = ''; drop.style.display = 'none'; q.focus(); } });
  document.addEventListener('click', function (e) { if (!drop.contains(e.target) && e.target !== q) drop.style.display = 'none'; });

  var bc = document.getElementById('barcodeIn');
  bc.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return; e.preventDefault();
    var code = bc.value.trim(); if (!code) return;
    MSPMS.getJSON('/api/part/barcode/' + encodeURIComponent(code)).then(function (p) { add(p); bc.value = ''; }).catch(function (er) { alert(er.error || 'Not found'); bc.select(); });
  });
  form.addEventListener('submit', function (e) { if (!Object.keys(cart).length) { e.preventDefault(); alert('Add at least one part to the bill.'); } });
  var pre = form.dataset.preload; if (pre) MSPMS.getJSON('/api/part/' + pre).then(add);
  render();
})();
