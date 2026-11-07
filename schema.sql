-- ============================================================
-- MSPMS - Motorcycle Spare Parts Management System
-- SQLite schema (open mspms.db in DB Browser for SQLite)
-- Developed by Venkatesh K, iPEC Solutions, Bangalore
-- ============================================================
PRAGMA foreign_keys = ON;

-- ---------- Users ----------
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(username) >= 3),
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    email         TEXT,
    role          TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('admin','manager','staff')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- Masters ----------
CREATE TABLE categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE brands (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE locations (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    type    TEXT NOT NULL DEFAULT 'Store' CHECK (type IN ('Store','Warehouse','Rack')),
    address TEXT
);

-- ---------- Parts ----------
CREATE TABLE parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    part_no       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    category_id   INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    brand_id      INTEGER REFERENCES brands(id) ON DELETE SET NULL,
    description   TEXT,
    cost_price    REAL NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    selling_price REAL NOT NULL DEFAULT 0 CHECK (selling_price >= 0),
    gst_percent   REAL NOT NULL DEFAULT 18 CHECK (gst_percent BETWEEN 0 AND 100),
    reorder_level INTEGER NOT NULL DEFAULT 5 CHECK (reorder_level >= 0),
    rack          TEXT,
    barcode       TEXT NOT NULL UNIQUE,
    image         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_parts_category ON parts(category_id);
CREATE INDEX idx_parts_brand    ON parts(brand_id);
CREATE INDEX idx_parts_name     ON parts(name);

-- ---------- Bike models and compatibility ----------
CREATE TABLE bike_models (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id  INTEGER NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
    model     TEXT NOT NULL,
    variant   TEXT NOT NULL DEFAULT 'Standard',
    year_from INTEGER NOT NULL CHECK (year_from BETWEEN 1950 AND 2100),
    year_to   INTEGER NOT NULL CHECK (year_to BETWEEN 1950 AND 2100),
    engine_cc INTEGER NOT NULL CHECK (engine_cc BETWEEN 25 AND 2500),
    CHECK (year_to >= year_from),
    UNIQUE (brand_id, model, variant)
);
CREATE INDEX idx_bikes_brand ON bike_models(brand_id);

CREATE TABLE part_compatibility (
    part_id       INTEGER NOT NULL REFERENCES parts(id)       ON DELETE CASCADE,
    bike_model_id INTEGER NOT NULL REFERENCES bike_models(id) ON DELETE CASCADE,
    PRIMARY KEY (part_id, bike_model_id)
);
CREATE INDEX idx_compat_bike ON part_compatibility(bike_model_id);

-- ---------- Stock per location ----------
-- NOTE: rows here are maintained automatically by the trigger
-- trg_movement_apply below. Never insert into stock directly;
-- insert a row into stock_movements instead.
CREATE TABLE stock (
    part_id     INTEGER NOT NULL REFERENCES parts(id)     ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    qty         INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
    PRIMARY KEY (part_id, location_id)
);
CREATE INDEX idx_stock_location ON stock(location_id);

CREATE TABLE stock_movements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id       INTEGER NOT NULL REFERENCES parts(id)     ON DELETE CASCADE,
    location_id   INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    qty_change    INTEGER NOT NULL CHECK (qty_change <> 0),
    movement_type TEXT NOT NULL CHECK (movement_type IN
                  ('purchase','sale','return_in','transfer_in','transfer_out','adjustment')),
    reference     TEXT,
    reason        TEXT,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_mov_part ON stock_movements(part_id, created_at);
CREATE INDEX idx_mov_type ON stock_movements(movement_type, created_at);
CREATE INDEX idx_mov_ref  ON stock_movements(reference);

-- Keeps stock consistent for purchases, sales, transfers, returns and
-- adjustments. If a movement would make stock negative, the CHECK on
-- stock.qty fails and the whole statement is rolled back.
CREATE TRIGGER trg_movement_apply AFTER INSERT ON stock_movements
BEGIN
    INSERT OR IGNORE INTO stock(part_id, location_id, qty) VALUES (NEW.part_id, NEW.location_id, 0);
    UPDATE stock SET qty = qty + NEW.qty_change
     WHERE part_id = NEW.part_id AND location_id = NEW.location_id;
END;

CREATE TRIGGER trg_parts_touch AFTER UPDATE ON parts
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE parts SET updated_at = datetime('now','localtime') WHERE id = NEW.id;
END;

-- ---------- Suppliers and purchases ----------
CREATE TABLE suppliers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    contact_person TEXT,
    phone          TEXT,
    email          TEXT,
    address        TEXT,
    gstin          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE purchases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    po_no          TEXT NOT NULL UNIQUE,
    supplier_id    INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    location_id    INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    order_date     TEXT NOT NULL,
    received_date  TEXT,
    status         TEXT NOT NULL DEFAULT 'ordered' CHECK (status IN ('ordered','received','cancelled')),
    payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid','partial','paid')),
    total          REAL NOT NULL DEFAULT 0 CHECK (total >= 0),
    paid_amount    REAL NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    notes          TEXT,
    user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_purchases_supplier ON purchases(supplier_id);
CREATE INDEX idx_purchases_date     ON purchases(order_date);

CREATE TABLE purchase_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    part_id     INTEGER NOT NULL REFERENCES parts(id)     ON DELETE RESTRICT,
    qty         INTEGER NOT NULL CHECK (qty > 0),
    unit_cost   REAL NOT NULL CHECK (unit_cost >= 0),
    gst_percent REAL NOT NULL DEFAULT 18 CHECK (gst_percent BETWEEN 0 AND 100)
);
CREATE INDEX idx_pitems_purchase ON purchase_items(purchase_id);
CREATE INDEX idx_pitems_part     ON purchase_items(part_id);

-- ---------- Customers and sales ----------
CREATE TABLE customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    address    TEXT,
    bike_owned TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_customers_name ON customers(name);

CREATE TABLE sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no      TEXT NOT NULL UNIQUE,
    customer_id     INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    location_id     INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    sale_date       TEXT NOT NULL,
    subtotal        REAL NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    discount        REAL NOT NULL DEFAULT 0 CHECK (discount >= 0),
    gst_amount      REAL NOT NULL DEFAULT 0 CHECK (gst_amount >= 0),
    total           REAL NOT NULL DEFAULT 0 CHECK (total >= 0),
    returned_amount REAL NOT NULL DEFAULT 0 CHECK (returned_amount >= 0),
    paid_amount     REAL NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    payment_mode    TEXT NOT NULL DEFAULT 'Cash' CHECK (payment_mode IN ('Cash','UPI','Card','Credit')),
    status          TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','partial_return','returned')),
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX idx_sales_date     ON sales(sale_date);
CREATE INDEX idx_sales_customer ON sales(customer_id);

CREATE TABLE sale_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    part_id      INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    qty          INTEGER NOT NULL CHECK (qty > 0),
    unit_price   REAL NOT NULL CHECK (unit_price >= 0),
    cost_price   REAL NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    gst_percent  REAL NOT NULL DEFAULT 18 CHECK (gst_percent BETWEEN 0 AND 100),
    returned_qty INTEGER NOT NULL DEFAULT 0,
    CHECK (returned_qty >= 0 AND returned_qty <= qty)
);
CREATE INDEX idx_sitems_sale ON sale_items(sale_id);
CREATE INDEX idx_sitems_part ON sale_items(part_id);

-- ---------- Activity log and settings ----------
CREATE TABLE activity_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id    INTEGER REFERENCES parts(id) ON DELETE SET NULL,
    action     TEXT NOT NULL CHECK (action IN
               ('Added','Updated','Sold','Purchased','Received','Transferred','Adjusted','Returned','Deleted')),
    details    TEXT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_activity_date ON activity_log(created_at);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
