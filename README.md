# Motorcycle Spare Parts Management System (MSPMS)

A complete Flask + SQLite web application for a motorcycle spare-parts shop: parts, barcode scanning and labels,
bike-compatibility lookup, multi-location stock and transfers, purchase orders, GST billing with printable invoices,
customers, suppliers, stock ledger, reports (CSV / Excel / PDF) and settings with backup/restore.

*Developed by Venkatesh K, iPEC Solutions, As Data Analyst From Bangalore*

## 1. Quick start

Requires **Python 3.9+** and an internet connection in the browser (Bootstrap, Chart.js, icons, barcode libraries load from CDNs).

```bash
cd mspms
python -m venv venv                  # optional but recommended
venv\Scripts\activate                # Windows      (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python seed.py                       # creates mspms.db with demo data (rebuilds it if it exists!)
python app.py                        # open http://127.0.0.1:5000
```

| User ID  | Password     | Role    |
|----------|--------------|---------|
| admin    | admin123     | admin   |
| manager  | manager123   | manager |
| staff    | staff123     | staff   |

New users can use **Sign up** on the login page (they get the `staff` role; an admin can change roles in Settings > Users).
If you skip `python seed.py`, `app.py` creates an empty database with only the admin user.

Optional environment variables: `MSPMS_HOST` (use `0.0.0.0` to open the app from your phone on the same Wi-Fi), `MSPMS_PORT`,
`MSPMS_DB` (database path), `FLASK_DEBUG=1`.
Note: browsers only allow the **camera** on `localhost` or HTTPS, so for phone camera scanning use a USB/Bluetooth scanner or HTTPS.

## 2. Project structure

```
mspms/
  app.py            all routes, validation, security (CSRF, roles), reports
  schema.sql        tables, constraints, indexes, triggers
  seed.py           demo data: 45 parts, 15 bikes, 3 locations, 6 suppliers, 15 customers, 30 sales, 10 purchases
  requirements.txt
  templates/        Jinja2 pages (base layout, macros, one template per screen)
  static/css/style.css
  static/js/        app.js (shared), dashboard.js, scan.js, pos.js, purchase.js
  static/img/       spareparts-banner.svg (login background)
  static/uploads/   uploaded part images
```

## 3. Features by page

1. **Login / Sign up / Logout** - hashed passwords, "Remind me" remembers the User ID and keeps you signed in for 30 days, muted elongated spare-parts banner.
2. **Dashboard** - KPI cards, category doughnut, inventory-value line chart, monthly sales bar chart, recent activity, low-stock list with *Reorder*; refreshes itself every 30 s.
3. **Parts** - CRUD, image upload, search, filters (category, brand, bike, stock status), sort, pagination, CSV export, bulk label printing.
4. **Scan** - camera (html5-qrcode) or manual / USB scanner entry; shows part details with *Update Stock* and *Add to Sale*. Printable CODE128 labels.
5. **Vehicles / Models** - CRUD, compatibility mapping, "Find parts for my bike".
6. **Multi-location inventory** - stores / warehouses / racks, per-location stock, transfers with history.
7. **Purchases** - purchase orders, receive stock (auto-increases inventory), payments, history.
8. **Sales / Billing** - search or scan, discount (Rs or %), GST, stock deduction, printable invoice (use *Print / Save as PDF*), returns.
9. **Customers** - CRUD, bike owned, history, outstanding balance, collect payment.
10. **Suppliers** - CRUD, parts supplied, history, dues, pay dues.
11. **Inventory** - overview, stock ledger, adjustments with reason, low / out-of-stock, dead-stock report.
12. **Reports** - sales, purchases, stock valuation, profit by category, top sellers, fast/slow movers, supplier report; date filters; CSV, Excel, PDF (print view with charts).
13. **Settings** - shop profile, GST number and rates, categories, brands, users, low-stock default, backup / restore.

Roles: `staff` can bill, receive stock and adjust stock; `manager` can also delete records and manage categories/brands;
`admin` can also change shop settings, users, backup and restore.

## 4. Database (ER description)

```
users ─┬─< stock_movements >─ parts >─ categories
       │                       │  └──── brands
       ├─< sales >─< sale_items >─ parts
       ├─< purchases >─< purchase_items >─ parts
       └─< activity_log                    suppliers ─< purchases >─ locations
customers ─< sales >─ locations
parts >─< bike_models   (via part_compatibility; bike_models >─ brands)
parts >─< locations     (via stock: part_id + location_id + qty)
settings (key / value)
```

* **parts** - unique `part_no` and `barcode`, CHECK constraints on prices, GST (0-100) and reorder level.
* **stock** - quantity per (part, location) with `CHECK (qty >= 0)`.
* **stock_movements** - the stock ledger. **Never edit `stock` directly.** The trigger `trg_movement_apply` adds each
  movement (purchase, sale, return_in, transfer_in/out, adjustment) to `stock`; a movement that would drive stock below zero is rejected,
  so purchase, sale, transfer and return can never leave stock inconsistent. Both rows of a transfer share a reference (`TRF-...`).
* **purchases / purchase_items**, **sales / sale_items** - headers and lines; item rows keep the price, cost and GST at the time of sale.
* ON DELETE rules: parts used in sales/purchases are protected (`RESTRICT`); deleting a customer keeps bills (`SET NULL`);
  deleting a part removes its mapping and stock rows (`CASCADE`).
* Outstanding balances (customers) and dues (suppliers) are computed from bills / purchase orders, so they can never drift.

Open `mspms.db` in **DB Browser for SQLite** at any time.

## 5. Security

Parameterised SQL everywhere, CSRF token on every POST, salted password hashing (Werkzeug), role checks, upload type/size checks,
Jinja auto-escaping, server-side and client-side validation, 400/403/404/500 pages.
Change the default passwords before real use.

## 6. Screenshots

Add your own screenshots here (suggested: `docs/login.png`, `docs/dashboard.png`, `docs/parts.png`, `docs/billing.png`, `docs/invoice.png`).

## 7. Troubleshooting

* *Charts / icons missing*: the browser needs internet for the CDN libraries.
* *Port 5000 busy*: `set MSPMS_PORT=5050` (Windows) / `MSPMS_PORT=5050 python app.py` (macOS/Linux).
* *Start fresh*: delete `mspms.db`, run `python seed.py` again.
