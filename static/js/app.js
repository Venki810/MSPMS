/* MSPMS shared behaviour: sidebar, validation, confirm dialogs, live search, stock modal.
   Developed by Venkatesh K, iPEC Solutions, Bangalore */
(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  window.MSPMS = {
    csrf: csrf,
    inr: function (v) { return '\u20B9' + Number(v || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); },
    esc: function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); },
    debounce: function (fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms || 250); }; },
    getJSON: function (url) { return fetch(url, { headers: { 'X-Requested-With': 'fetch' } }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw d; return d; }); }); }
  };

  // ---- sidebar toggle (mobile)
  var sb = document.getElementById('sidebar'), ov = document.getElementById('overlay'), mb = document.getElementById('menuBtn');
  function toggle(open) { if (!sb) return; sb.classList.toggle('open', open); ov.classList.toggle('show', open); }
  if (mb) mb.addEventListener('click', function () { toggle(!sb.classList.contains('open')); });
  if (ov) ov.addEventListener('click', function () { toggle(false); });

  // ---- client-side validation (Bootstrap) for every form marked needs-validation
  document.querySelectorAll('form.needs-validation').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!f.checkValidity()) { e.preventDefault(); e.stopPropagation(); }
      f.classList.add('was-validated');
    });
  });

  // ---- confirm dialog before destructive actions: <form data-confirm="Message">
  var modalEl = document.getElementById('confirmModal'), pending = null;
  if (modalEl) {
    var modal = new bootstrap.Modal(modalEl);
    document.addEventListener('submit', function (e) {
      var f = e.target;
      if (f.dataset && f.dataset.confirm && !f.dataset.ok) {
        e.preventDefault(); pending = f;
        document.getElementById('confirmText').textContent = f.dataset.confirm;
        modal.show();
      }
    });
    document.getElementById('confirmYes').addEventListener('click', function () {
      if (pending) { pending.dataset.ok = '1'; modal.hide(); pending.submit(); }
    });
  }

  // ---- global search with live results
  var gs = document.getElementById('globalSearch'), gr = document.getElementById('globalResults');
  if (gs && gr) {
    gs.addEventListener('input', MSPMS.debounce(function () {
      var q = gs.value.trim();
      if (q.length < 2) { gr.style.display = 'none'; return; }
      MSPMS.getJSON('/api/parts/search?q=' + encodeURIComponent(q)).then(function (rows) {
        gr.innerHTML = rows.length ? rows.map(function (p) {
          return '<a href="' + p.url + '"><span>' + MSPMS.esc(p.name) + '<br><small class="text-muted">' + MSPMS.esc(p.part_no) + '</small></span>' +
            '<span class="text-end"><b>' + MSPMS.inr(p.price) + '</b><br><small class="text-muted">' + p.total_qty + ' in stock</small></span></a>';
        }).join('') : '<div class="p-3 text-muted">No parts found</div>';
        gr.style.display = 'block';
      });
    }, 250));
    document.addEventListener('click', function (e) { if (!gs.contains(e.target) && !gr.contains(e.target)) gr.style.display = 'none'; });
  }

  // ---- "Update stock" modal (parts list, part details, scan page)
  window.openStockModal = function (partId, name, locId) {
    var m = document.getElementById('stockModal'); if (!m) return;
    document.getElementById('sm_part').value = partId;
    document.getElementById('sm_name').textContent = name;
    if (locId) document.getElementById('sm_loc').value = locId;
    var err = document.getElementById('sm_err'); err.classList.add('d-none');
    m.querySelector('form').reset(); if (locId) document.getElementById('sm_loc').value = locId;
    bootstrap.Modal.getOrCreateInstance(m).show();
  };
  document.querySelectorAll('form.js-ajax-stock').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var err = document.getElementById('sm_err');
      fetch(f.action, { method: 'POST', body: new FormData(f), headers: { 'X-Requested-With': 'fetch', 'X-CSRF-Token': csrf } })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) { err.textContent = res.d.error || 'Could not update stock.'; err.classList.remove('d-none'); return; }
          bootstrap.Modal.getInstance(document.getElementById('stockModal')).hide();
          if (window.onStockUpdated) window.onStockUpdated(res.d); else location.reload();
        });
    });
  });

  // ---- auto-dismiss success alerts
  setTimeout(function () { document.querySelectorAll('.alert-success').forEach(function (a) { bootstrap.Alert.getOrCreateInstance(a).close(); }); }, 6000);

  // ---- generic helper: fill a modal form from data-* attributes of the clicked button
  document.querySelectorAll('[data-edit-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var m = document.querySelector(btn.dataset.editTarget), data = btn.dataset;
      m.querySelectorAll('[name]').forEach(function (el) {
        if (el.name === 'csrf_token') return;
        el.value = data[el.name] !== undefined ? data[el.name] : '';
      });
      var t = m.querySelector('.modal-title'); if (t) t.textContent = data.title || t.textContent;
    });
  });
  document.querySelectorAll('[data-new-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var m = document.querySelector(btn.dataset.newTarget);
      m.querySelectorAll('[name]').forEach(function (el) { if (el.name !== 'csrf_token') el.value = el.dataset.default || ''; });
      var t = m.querySelector('.modal-title'); if (t) t.textContent = btn.dataset.title || t.textContent;
    });
  });
})();
