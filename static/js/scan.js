/* Barcode scan page: camera (html5-qrcode) + manual entry -> /api/part/barcode/<code> */
(function () {
  'use strict';
  var box = document.getElementById('result'), input = document.getElementById('manualCode'), scanner = null, current = null;
  function show(p) {
    current = p;
    var st = p.total_qty <= 0 ? '<span class="badge-soft b-out">Out of stock</span>' : (p.total_qty <= p.reorder_level ? '<span class="badge-soft b-low">Low &middot; ' + p.total_qty + '</span>' : '<span class="badge-soft b-ok">' + p.total_qty + ' in stock</span>');
    box.innerHTML = '<div class="card detail-card"><div class="card-body"><div class="small text-muted">' + MSPMS.esc(p.part_no) + ' &middot; ' + MSPMS.esc(p.category) + '</div>' +
      '<h2 class="h5">' + MSPMS.esc(p.name) + '</h2><div class="mb-2">' + st + ' <span class="text-muted small ms-1">' + MSPMS.esc(p.brand || '') + ' &middot; Rack ' + MSPMS.esc(p.rack || '-') + '</span></div>' +
      '<div class="big mb-2">' + MSPMS.inr(p.price) + ' <small class="text-muted fw-normal">+ ' + p.gst + '% GST</small></div>' +
      '<div class="d-grid gap-2"><button class="btn btn-primary btn-lg" id="btnStock"><i class="bi bi-box-seam me-2"></i>Update Stock</button>' +
      '<a class="btn btn-success" href="/sales/new?part_id=' + p.id + '"><i class="bi bi-cart-plus me-1"></i>Add to Sale</a>' +
      '<a class="btn btn-outline-secondary" href="' + p.url + '">Full details</a></div></div></div>';
    document.getElementById('btnStock').onclick = function () { openStockModal(p.id, p.name); };
  }
  function lookup(code) {
    code = (code || '').trim(); if (!code) return;
    MSPMS.getJSON('/api/part/barcode/' + encodeURIComponent(code)).then(show).catch(function (e) {
      box.innerHTML = '<div class="alert alert-warning mb-0"><i class="bi bi-exclamation-triangle me-2"></i>' + MSPMS.esc(e.error || 'Lookup failed') + ' (' + MSPMS.esc(code) + ')</div>';
    });
  }
  window.onStockUpdated = function () { if (current) lookup(current.barcode); };
  document.getElementById('manualForm').addEventListener('submit', function (e) { e.preventDefault(); lookup(input.value); input.select(); });
  var startBtn = document.getElementById('startCam'), stopBtn = document.getElementById('stopCam'), msg = document.getElementById('camMsg');
  startBtn.addEventListener('click', function () {
    if (typeof Html5Qrcode === 'undefined') { msg.textContent = 'Camera library could not load (check internet). Use manual entry.'; return; }
    scanner = new Html5Qrcode('reader');
    scanner.start({ facingMode: 'environment' }, { fps: 10, qrbox: { width: 260, height: 140 } }, function (txt) { input.value = txt; lookup(txt); }, function () {})
      .then(function () { startBtn.classList.add('d-none'); stopBtn.classList.remove('d-none'); msg.textContent = ''; })
      .catch(function (err) { msg.textContent = 'Camera unavailable: ' + err + '. Camera needs HTTPS or localhost and permission.'; });
  });
  stopBtn.addEventListener('click', function () {
    if (scanner) scanner.stop().then(function () { scanner.clear(); startBtn.classList.remove('d-none'); stopBtn.classList.add('d-none'); });
  });
  var q = new URLSearchParams(location.search).get('code'); if (q) lookup(q);
  input.focus();
})();
