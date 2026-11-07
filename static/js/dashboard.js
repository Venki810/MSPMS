/* Dashboard: loads /api/dashboard and refreshes it every 30 seconds. */
(function () {
  'use strict';
  var charts = {}, PALETTE = ['#0B3D91', '#1E4FB5', '#4F86E0', '#7FAEF0', '#A9C8F7', '#12805c', '#e0a31a', '#c0392b'];
  function draw(id, type, labels, data, label, opts) {
    var ctx = document.getElementById(id); if (!ctx) return;
    if (charts[id]) { charts[id].data.labels = labels; charts[id].data.datasets[0].data = data; charts[id].update(); return; }
    var ds = { label: label, data: data };
    if (type === 'doughnut') { ds.backgroundColor = PALETTE; ds.borderWidth = 2; ds.borderColor = '#fff'; }
    else if (type === 'line') { ds.borderColor = '#1E4FB5'; ds.backgroundColor = 'rgba(30,79,181,.12)'; ds.fill = true; ds.tension = .35; ds.pointBackgroundColor = '#0B3D91'; }
    else { ds.backgroundColor = '#1E4FB5'; ds.borderRadius = 8; }
    charts[id] = new Chart(ctx, { type: type, data: { labels: labels, datasets: [ds] },
      options: Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === 'doughnut', position: 'right', labels: { boxWidth: 12 } } } },
        type === 'doughnut' ? { cutout: '62%' } : { scales: { y: { beginAtZero: true, ticks: { callback: function (v) { return v >= 100000 ? (v / 100000).toFixed(1) + 'L' : v >= 1000 ? (v / 1000) + 'k' : v; } } }, x: { grid: { display: false } } } }, opts || {}) });
  }
  var badge = { Added: 'b-ok', Updated: 'b-info', Sold: 'b-info', Received: 'b-ok', Purchased: 'b-info', Transferred: 'b-gray', Adjusted: 'b-low', Returned: 'b-low', Deleted: 'b-out' };
  function render(d) {
    var k = d.kpi;
    document.getElementById('k_parts').textContent = k.parts;
    document.getElementById('k_bikes').textContent = k.bikes;
    document.getElementById('k_sales').textContent = MSPMS.inr(k.sales).replace(/\.00$/, '');
    document.getElementById('k_low').textContent = k.low;
    document.getElementById('k_value').textContent = MSPMS.inr(k.stock_value).replace(/\.00$/, '');
    draw('catChart', 'doughnut', d.categories.labels, d.categories.data, 'Parts');
    draw('invChart', 'line', d.inventory.labels, d.inventory.data, 'Inventory value (Rs)');
    draw('salesChart', 'bar', d.sales.labels, d.sales.data, 'Sales (Rs)');
    document.getElementById('recentBody').innerHTML = d.recent.length ? d.recent.map(function (r) {
      return '<tr><td>' + (r.part_id ? '<a href="/parts/' + r.part_id + '">' + MSPMS.esc(r.part) + '</a>' : MSPMS.esc(r.details || '-')) + '</td>' +
        '<td><span class="badge-soft ' + (badge[r.action] || 'b-gray') + '">' + r.action + '</span></td><td class="text-muted small">' + r.date + '</td></tr>';
    }).join('') : '<tr><td colspan="3" class="text-center text-muted py-4">No activity yet</td></tr>';
    document.getElementById('lowList').innerHTML = d.low.length ? d.low.map(function (p) {
      return '<li class="list-group-item d-flex justify-content-between align-items-center gap-2"><div class="text-truncate"><a class="fw-semibold text-decoration-none" href="/parts/' + p.id + '">' +
        MSPMS.esc(p.name) + '</a><div class="small text-muted">' + MSPMS.esc(p.part_no) + ' &middot; ' + (p.qty === 0 ? '<span class="text-danger">Out of stock</span>' : p.qty + ' left (min ' + p.reorder + ')') + '</div></div>' +
        '<a class="btn btn-sm btn-outline-primary flex-none" href="/purchases/new?part_id=' + p.id + '"><i class="bi bi-cart-plus"></i> Reorder</a></li>';
    }).join('') : '<li class="list-group-item text-center text-muted py-4">All parts are above their reorder level.</li>';
    document.getElementById('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  }
  function load() { MSPMS.getJSON('/api/dashboard').then(render).catch(function () {}); }
  load(); setInterval(load, 30000);
  document.getElementById('refreshBtn').addEventListener('click', load);
})();
