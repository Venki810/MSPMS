"""
seed.py - (Re)creates mspms.db from schema.sql and fills it with demo data.

    python seed.py

WARNING: an existing mspms.db is deleted and rebuilt.
Seeds: 45 parts (8 categories), 15 bike models, 3 locations, 6 suppliers,
15 customers, 30 sales (2 with returns), 10 purchases, stock transfers,
and 3 users (admin/admin123, manager/manager123, staff/staff123).
All stock quantities flow through stock_movements, so the trigger in
schema.sql keeps the stock table consistent.
"""
import os
import random
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("MSPMS_DB", os.path.join(BASE, "mspms.db"))
random.seed(42)

if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys = ON")
with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as fh:
    con.executescript(fh.read())

NOW = datetime.now().replace(microsecond=0)


def dt(days_ago, hour=11, minute=0):
    d = NOW - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=minute, second=0).strftime("%Y-%m-%d %H:%M:%S")


def ins(sql, args=()):
    return con.execute(sql, args).lastrowid


# ---------------------------------------------------------------- users
ADMIN = ins("INSERT INTO users(username,password_hash,full_name,email,role) VALUES(?,?,?,?,?)",
            ("admin", generate_password_hash("admin123"), "Venkatesh K", "venkatesh@ipec.example", "admin"))
ins("INSERT INTO users(username,password_hash,full_name,email,role) VALUES(?,?,?,?,?)",
    ("manager", generate_password_hash("manager123"), "Anitha Rao", "anitha@ipec.example", "manager"))
ins("INSERT INTO users(username,password_hash,full_name,email,role) VALUES(?,?,?,?,?)",
    ("staff", generate_password_hash("staff123"), "Ravi Kumar", "ravi@ipec.example", "staff"))

# ---------------------------------------------------------------- settings
SETTINGS = {
    "shop_name": "MSPMS Motor Spares",
    "shop_address": "No. 42, 100 Feet Road, Indiranagar, Bengaluru - 560038",
    "shop_phone": "+91 98450 12345",
    "shop_email": "sales@mspms-spares.example",
    "gst_number": "29ABCDE1234F1Z5",
    "gst_rates": "0,5,12,18,28",
    "low_stock_default": "5",
    "invoice_prefix": "INV",
    "po_prefix": "PO",
    "invoice_footer": "Goods once sold will not be taken back after 7 days. Thank you for your business!",
}
for k, v in SETTINGS.items():
    ins("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))

# ---------------------------------------------------------------- masters
CATS = ["Engine", "Brakes", "Electrical", "Body", "Suspension", "Transmission", "Tyres & Wheels", "Accessories"]
CAT = {n: ins("INSERT INTO categories(name) VALUES(?)", (n,)) for n in CATS}
BRANDS = ["Honda", "Hero", "Bajaj", "TVS", "Royal Enfield", "Yamaha", "Suzuki", "KTM"]
BR = {n: ins("INSERT INTO brands(name) VALUES(?)", (n,)) for n in BRANDS}

LOC_MAIN = ins("INSERT INTO locations(name,type,address) VALUES(?,?,?)",
               ("Main Store - Indiranagar", "Store", "100 Feet Road, Indiranagar, Bengaluru"))
LOC_WH = ins("INSERT INTO locations(name,type,address) VALUES(?,?,?)",
             ("Central Warehouse - Peenya", "Warehouse", "2nd Stage, Peenya Industrial Area, Bengaluru"))
LOC_RACK = ins("INSERT INTO locations(name,type,address) VALUES(?,?,?)",
               ("Service Bay Rack Unit", "Rack", "Behind Main Store, Indiranagar"))
LOCS = [LOC_MAIN, LOC_WH, LOC_RACK]

BIKES = [  # brand, model, variant, from, to, cc
    ("Honda", "Activa 6G", "Standard", 2020, 2024, 109),
    ("Honda", "CB Shine", "Drum", 2018, 2024, 124),
    ("Honda", "Unicorn", "BS6", 2019, 2024, 162),
    ("Hero", "Splendor Plus", "i3S", 2018, 2024, 97),
    ("Hero", "HF Deluxe", "Self Start", 2019, 2024, 97),
    ("Hero", "Xtreme 160R", "Standard", 2020, 2024, 160),
    ("Bajaj", "Pulsar 150", "Twin Disc", 2017, 2024, 149),
    ("Bajaj", "Platina 110", "ABS", 2019, 2024, 115),
    ("TVS", "Apache RTR 160 4V", "Disc", 2019, 2024, 159),
    ("TVS", "Jupiter", "Classic", 2018, 2024, 109),
    ("Royal Enfield", "Classic 350", "Dual Channel", 2021, 2024, 349),
    ("Royal Enfield", "Bullet 350", "Standard", 2019, 2024, 346),
    ("Yamaha", "FZ-S V3", "ABS", 2019, 2024, 149),
    ("Suzuki", "Access 125", "Disc", 2018, 2024, 124),
    ("KTM", "Duke 200", "BS6", 2019, 2024, 199),
]
BIKE_ID = []
for b in BIKES:
    BIKE_ID.append(ins("INSERT INTO bike_models(brand_id,model,variant,year_from,year_to,engine_cc) VALUES(?,?,?,?,?,?)",
                       (BR[b[0]], b[1], b[2], b[3], b[4], b[5])))

# ---------------------------------------------------------------- parts
# name | category | brand | cost price | reorder | compatible bike numbers (1-15)
ALL = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
PARTS = [
    ("Spark Plug CPR7EA-9", "Engine", "Honda", 140, 15, "1,2,3,10,14"),
    ("Piston Kit Std 97cc", "Engine", "Hero", 780, 6, "4,5"),
    ("Air Filter Element", "Engine", "Bajaj", 95, 12, "7,8"),
    ("Engine Oil 10W-30 MA2 (1L)", "Engine", "Honda", 380, 20, ALL),
    ("Cylinder Gasket Set", "Engine", "TVS", 210, 8, "9,10"),
    ("Oil Filter Element", "Engine", "Royal Enfield", 120, 10, "11,12"),
    ("Carburettor Assembly", "Engine", "Hero", 1450, 4, "4,5"),
    ("Front Brake Pad Set", "Brakes", "Bajaj", 210, 15, "7,9,13,15"),
    ("Rear Brake Shoe Set", "Brakes", "Hero", 180, 15, "2,4,5,8"),
    ("Front Disc Rotor 240mm", "Brakes", "Bajaj", 1250, 4, "7,9"),
    ("Brake Master Cylinder", "Brakes", "TVS", 640, 5, "9,13"),
    ("Brake Fluid DOT 3 (100ml)", "Brakes", "Yamaha", 55, 25, ALL),
    ("Brake Cable Front", "Brakes", "Hero", 70, 15, "4,5,8"),
    ("Headlight Bulb H4 35/35W", "Electrical", "Suzuki", 85, 20, "1,2,3,4,5,10,14"),
    ("Battery 12V 5Ah (MF)", "Electrical", "Honda", 1180, 6, "1,2,3,10,14"),
    ("Battery 12V 9Ah (MF)", "Electrical", "Royal Enfield", 1850, 4, "11,12"),
    ("Indicator Lamp Set (4 pc)", "Electrical", "Bajaj", 260, 8, "7,8,9"),
    ("CDI Unit", "Electrical", "Hero", 540, 5, "4,5"),
    ("Regulator Rectifier", "Electrical", "TVS", 520, 5, "9,10"),
    ("Horn 12V Disc Type", "Electrical", "Yamaha", 150, 10, ALL),
    ("Self Starter Motor", "Electrical", "Honda", 1650, 3, "1,2,3"),
    ("Rear View Mirror Pair", "Body", "Honda", 280, 10, "1,2,3,14"),
    ("Fuel Tank Cap", "Body", "Bajaj", 190, 6, "7,8"),
    ("Side Panel Left", "Body", "Hero", 420, 5, "4,5,6"),
    ("Front Mudguard", "Body", "TVS", 560, 4, "9,10"),
    ("Seat Cover Assembly", "Body", "Suzuki", 480, 5, "14"),
    ("Tail Lamp Assembly", "Body", "Yamaha", 690, 4, "13"),
    ("Front Fork Oil Seal Kit", "Suspension", "Royal Enfield", 240, 8, "11,12"),
    ("Rear Shock Absorber Pair", "Suspension", "Bajaj", 1480, 4, "7,8"),
    ("Swingarm Bush Kit", "Suspension", "KTM", 320, 6, "15,13"),
    ("Front Fork Spring", "Suspension", "Hero", 360, 5, "4,5,6"),
    ("Chain Sprocket Kit 428H", "Transmission", "Hero", 1150, 8, "4,5,6,2"),
    ("Clutch Plate Set", "Transmission", "Honda", 760, 8, "1,2,3"),
    ("Clutch Cable", "Transmission", "Bajaj", 90, 15, "7,8,9"),
    ("Drive Chain 428H-120L", "Transmission", "TVS", 640, 8, "9,13"),
    ("Gear Shifter Lever", "Transmission", "KTM", 410, 4, "15,7"),
    ("Front Tyre 2.75-18 (Tube)", "Tyres & Wheels", "TVS", 1250, 8, "4,5,2"),
    ("Rear Tyre 3.00-18 (Tube)", "Tyres & Wheels", "Bajaj", 1480, 8, "7,2,3"),
    ("Tubeless Tyre 90/90-12", "Tyres & Wheels", "Honda", 1320, 8, "1,10,14"),
    ("Inner Tube 18 inch", "Tyres & Wheels", "Hero", 260, 15, "2,3,4,5,7"),
    ("Crash Guard (Leg Guard)", "Accessories", "Royal Enfield", 1250, 5, "11,12"),
    ("Full Face Helmet ISI", "Accessories", "Suzuki", 1450, 6, ALL),
    ("Phone Holder with Charger", "Accessories", "KTM", 520, 8, ALL),
    ("Tank Grip Pad", "Accessories", "KTM", 260, 8, "15,9,7"),
    ("Waterproof Bike Cover", "Accessories", "Honda", 390, 10, ALL),
]
CODE = {"Engine": "ENG", "Brakes": "BRK", "Electrical": "ELC", "Body": "BDY", "Suspension": "SUS",
        "Transmission": "TRN", "Tyres & Wheels": "TYR", "Accessories": "ACC"}
PART = []   # dicts
counters = {}
for i, (name, cat, brand, cost, reorder, compat) in enumerate(PARTS, 1):
    counters[cat] = counters.get(cat, 0) + 1
    part_no = f"{CODE[cat]}-{counters[cat]:03d}"
    sell = round(cost * random.uniform(1.35, 1.65) / 5) * 5
    barcode = f"8901234{i:05d}"
    pid = ins("""INSERT INTO parts(part_no,name,category_id,brand_id,cost_price,selling_price,gst_percent,
                 reorder_level,rack,barcode,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (part_no, name, CAT[cat], BR[brand], cost, sell, 18, reorder,
               f"{random.choice('ABCDEF')}-{random.randint(1, 9)}-{random.randint(1, 4)}", barcode,
               f"{brand} compatible {name.lower()}.", dt(195), dt(195)))
    for n in compat.split(","):
        con.execute("INSERT OR IGNORE INTO part_compatibility VALUES(?,?)", (pid, BIKE_ID[int(n) - 1]))
    PART.append(dict(id=pid, name=name, cost=cost, sell=sell, gst=18, reorder=reorder))

# ---------------------------------------------------------------- helpers
STOCK = {}


def mv(pid, loc, qty, mtype, ref, reason, when):
    """Insert a stock movement (trigger updates stock) and track qty locally."""
    con.execute("""INSERT INTO stock_movements(part_id,location_id,qty_change,movement_type,reference,reason,user_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""", (pid, loc, qty, mtype, ref, reason, ADMIN, when))
    STOCK[(pid, loc)] = STOCK.get((pid, loc), 0) + qty


def activity(action, details, pid, when):
    ins("INSERT INTO activity_log(part_id,action,details,user_id,created_at) VALUES(?,?,?,?,?)",
        (pid, action, details, ADMIN, when))


def totals(items, discount):
    sub = sum(i["qty"] * i["price"] for i in items)
    discount = min(max(discount, 0), sub)
    ratio = discount / sub if sub else 0
    gst = sum(i["qty"] * i["price"] * (1 - ratio) * i["gst"] / 100 for i in items)
    return round(sub, 2), round(discount, 2), round(gst, 2), round(sub - discount + gst, 2)


# ---------------------------------------------------------------- opening stock
for p in PART:
    for loc, lo, hi in ((LOC_MAIN, 25, 60), (LOC_WH, 20, 80), (LOC_RACK, 4, 14)):
        mv(p["id"], loc, random.randint(lo, hi), "adjustment", "OPENING", "Opening stock", dt(195, 10))
    activity("Added", f"Part added: {p['name']}", p["id"], dt(195, 10))

# ---------------------------------------------------------------- suppliers
SUPPLIERS = [
    ("Rajesh Auto Spares", "Rajesh Gowda", "+91 98860 11223", "rajesh@rajeshspares.example", "SP Road, Bengaluru - 560002", "29AAKCR1234M1ZQ"),
    ("Sundaram Motor Parts", "K. Sundaram", "+91 94440 22334", "sales@sundarammp.example", "Mount Road, Chennai - 600002", "33AABCS5678K1Z2"),
    ("Bharat Two-Wheeler Components", "Prakash Joshi", "+91 98220 33445", "info@bharat2w.example", "Chakan MIDC, Pune - 410501", "27AAECB9012P1ZV"),
    ("Gujarat Auto Agencies", "Hiren Patel", "+91 98250 44556", "hiren@gujaratauto.example", "Naroda GIDC, Ahmedabad - 382330", "24AACFG3456L1Z8"),
    ("Delhi Moto Traders", "Sandeep Arora", "+91 98110 55667", "orders@delhimoto.example", "Karol Bagh, New Delhi - 110005", "07AADCD7890N1ZA"),
    ("Hyderabad Bearings & Spares", "Mohd. Irfan", "+91 99490 66778", "irfan@hydspares.example", "Moosarambagh, Hyderabad - 500036", "36AAGCH2345Q1ZD"),
]
SUP = [ins("INSERT INTO suppliers(name,contact_person,phone,email,address,gstin) VALUES(?,?,?,?,?,?)", s) for s in SUPPLIERS]

# ---------------------------------------------------------------- customers
CUSTOMERS = [
    ("Arjun Reddy", "98450 10001", "Honda Activa 6G"), ("Suresh Babu", "98450 10002", "Hero Splendor Plus"),
    ("Manjunath Gowda", "98450 10003", "Bajaj Pulsar 150"), ("Priya Nair", "98450 10004", "TVS Jupiter"),
    ("Imran Pasha", "98450 10005", "Royal Enfield Classic 350"), ("Kavitha Murthy", "98450 10006", "Suzuki Access 125"),
    ("Rahul Sharma", "98450 10007", "KTM Duke 200"), ("Deepak Shetty", "98450 10008", "Yamaha FZ-S V3"),
    ("Lakshmi Narayan", "98450 10009", "Honda CB Shine"), ("Mohan Das", "98450 10010", "Hero HF Deluxe"),
    ("Naveen Kumar", "98450 10011", "TVS Apache RTR 160 4V"), ("Sneha Patil", "98450 10012", "Honda Activa 6G"),
    ("Vikram Singh", "98450 10013", "Royal Enfield Bullet 350"), ("Farhan Sheikh", "98450 10014", "Bajaj Platina 110"),
    ("Ganesh Iyer", "98450 10015", "Honda Unicorn"),
]
CUST = [ins("INSERT INTO customers(name,phone,email,address,bike_owned,created_at) VALUES(?,?,?,?,?,?)",
            (n, "+91 " + ph, n.split()[0].lower() + "@mail.example", "Bengaluru, Karnataka", b, dt(random.randint(60, 190))))
        for n, ph, b in CUSTOMERS]

# ---------------------------------------------------------------- purchases (10)
purchase_days = [170, 150, 128, 105, 88, 66, 45, 28, 12, 4]
for n, days in enumerate(purchase_days, 1):
    status = "received"
    if n == 9:
        status = "cancelled"
    if n == 10:
        status = "ordered"
    loc = LOC_WH if n % 3 else LOC_MAIN
    po = f"PO-{NOW.year}-{n:04d}"
    chosen = random.sample(PART, random.randint(2, 5))
    items = [dict(p=p, qty=random.randint(10, 40), cost=round(p["cost"] * random.uniform(0.92, 1.0), 2)) for p in chosen]
    total = round(sum(i["qty"] * i["cost"] * 1.18 for i in items), 2)
    if status != "received":
        paid = 0
    elif n in (2, 3, 5, 7, 8):
        paid = total
    elif n in (4, 6):
        paid = round(total * 0.5, 2)
    else:
        paid = 0
    pay_status = "paid" if paid >= total and total else ("partial" if paid > 0 else "unpaid")
    pid_ = ins("""INSERT INTO purchases(po_no,supplier_id,location_id,order_date,received_date,status,payment_status,
                  total,paid_amount,notes,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (po, SUP[(n - 1) % 6], loc, dt(days)[:10], dt(days - 2)[:10] if status == "received" else None,
                status, pay_status, total, paid, "Seed purchase order", ADMIN))
    for i in items:
        ins("INSERT INTO purchase_items(purchase_id,part_id,qty,unit_cost,gst_percent) VALUES(?,?,?,?,?)",
            (pid_, i["p"]["id"], i["qty"], i["cost"], 18))
        if status == "received":
            mv(i["p"]["id"], loc, i["qty"], "purchase", po, "Purchase received", dt(days - 2, 15))
    if status == "received":
        activity("Received", f"Received {po} ({len(items)} items)", items[0]["p"]["id"], dt(days - 2, 15))

# ---------------------------------------------------------------- transfers
for k, (days, pidx, qty) in enumerate([(100, 0, 8), (80, 3, 12), (60, 7, 6), (30, 13, 10)], 1):
    p = PART[pidx]
    ref = f"TRF-{NOW.year}{k:04d}"
    mv(p["id"], LOC_WH, -qty, "transfer_out", ref, "Replenish main store", dt(days, 12))
    mv(p["id"], LOC_MAIN, qty, "transfer_in", ref, "Replenish main store", dt(days, 12))
    activity("Transferred", f"Moved {qty} x {p['name']} to Main Store", p["id"], dt(days, 12))

# ---------------------------------------------------------------- sales (30)
PAY_MODES = ["Cash", "UPI", "Card", "Credit"]
sale_days = sorted(random.sample(range(1, 121), 30), reverse=True)
sale_rows = []
for n, days in enumerate(sale_days, 1):
    inv = f"INV-{NOW.year}-{n:04d}"
    cust = None if n % 8 == 0 else random.choice(CUST)
    chosen = random.sample(PART, random.randint(1, 4))
    items = []
    for p in chosen:
        qty = random.randint(1, 3)
        if STOCK.get((p["id"], LOC_MAIN), 0) >= qty:
            items.append(dict(p=p, qty=qty, price=p["sell"], gst=p["gst"]))
    if not items:
        continue
    disc = random.choice([0, 0, 0, 50, 100, 150])
    sub, disc, gst, total = totals(items, disc)
    mode = random.choice(PAY_MODES) if cust else random.choice(["Cash", "UPI", "Card"])
    paid = total if mode != "Credit" else random.choice([0, round(total * 0.5, 2)])
    sid = ins("""INSERT INTO sales(invoice_no,customer_id,location_id,sale_date,subtotal,discount,gst_amount,total,
                 paid_amount,payment_mode,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (inv, cust, LOC_MAIN, dt(days, random.randint(10, 19), random.randint(0, 59)), sub, disc, gst, total, paid, mode, ADMIN))
    for it in items:
        ins("INSERT INTO sale_items(sale_id,part_id,qty,unit_price,cost_price,gst_percent) VALUES(?,?,?,?,?,?)",
            (sid, it["p"]["id"], it["qty"], it["price"], it["p"]["cost"], it["gst"]))
        mv(it["p"]["id"], LOC_MAIN, -it["qty"], "sale", inv, "Sale", dt(days, 14))
    activity("Sold", f"Invoice {inv} ({len(items)} items)", items[0]["p"]["id"], dt(days, 14))
    sale_rows.append((sid, inv, days, items, sub, disc, total, paid))

# two sales with returns
for sid, inv, days, items, sub, disc, total, paid in (sale_rows[6], sale_rows[18]):
    it = items[0]
    ratio = disc / sub if sub else 0
    refund = round(1 * it["price"] * (1 - ratio) * (1 + it["gst"] / 100), 2)
    row = con.execute("SELECT id FROM sale_items WHERE sale_id=? AND part_id=?", (sid, it["p"]["id"])).fetchone()
    con.execute("UPDATE sale_items SET returned_qty=1 WHERE id=?", (row[0],))
    all_returned = len(items) == 1 and it["qty"] == 1
    new_paid = min(paid, round(total - refund, 2))
    con.execute("UPDATE sales SET returned_amount=?, status=?, paid_amount=? WHERE id=?",
                (refund, "returned" if all_returned else "partial_return", max(new_paid, 0), sid))
    mv(it["p"]["id"], LOC_MAIN, 1, "return_in", inv, "Customer return", dt(max(days - 2, 0), 16))
    activity("Returned", f"Return against {inv}", it["p"]["id"], dt(max(days - 2, 0), 16))


# ---------------------------------------------------------------- low / out-of-stock demo
def set_total(pidx, target):
    p = PART[pidx]
    total = sum(v for (pid_, _), v in STOCK.items() if pid_ == p["id"])
    remove = total - target
    for loc in (LOC_MAIN, LOC_WH, LOC_RACK):
        if remove <= 0:
            break
        take = min(remove, STOCK.get((p["id"], loc), 0))
        if take:
            mv(p["id"], loc, -take, "adjustment", "COUNT", "Stock count correction - damaged / shrinkage", dt(1, 17))
            remove -= take
    activity("Updated", "Stock count correction", p["id"], dt(1, 17))


for pidx, target in [(3, 4), (8, 3), (14, 2), (20, 1), (26, 0), (31, 5), (35, 3), (11, 0), (40, 2)]:
    set_total(pidx, target)

con.commit()
con.close()
print("mspms.db created.")
print("Login: admin / admin123   (also manager / manager123, staff / staff123)")
