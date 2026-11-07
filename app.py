"""
MSPMS - Motorcycle Spare Parts Management System
Developed by Venkatesh K, iPEC Solutions, Bangalore

Flask + plain sqlite3 (no ORM). Every SQL statement is parameterised.
All stock changes are made by inserting rows into stock_movements; the
trigger `trg_movement_apply` in schema.sql updates the stock table and
rejects any movement that would make stock negative.
"""
import csv
import io
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MSPMS_DB", os.path.join(BASE_DIR, "mspms.db"))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}
CREDIT = "Developed by Venkatesh K, iPEC Solutions,As Data Analyst From Bangalore"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)


def _secret_key():
    """Persist a random secret key next to the app so sessions survive restarts."""
    path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    return key


app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or _secret_key(),
    MAX_CONTENT_LENGTH=64 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SAMESITE="Lax",
)

DEFAULT_SETTINGS = {
    "shop_name": "MSPMS Motor Spares", "shop_address": "Bengaluru, Karnataka", "shop_phone": "",
    "shop_email": "", "gst_number": "", "gst_rates": "0,5,12,18,28", "low_stock_default": "5",
    "invoice_prefix": "INV", "po_prefix": "PO",
    "invoice_footer": "Thank you for your business!",
}


# =====================================================================
# Database helpers
# =====================================================================
def ensure_db():
    """Create an empty database (schema + admin user) if mspms.db is missing."""
    if os.path.exists(DB_PATH):
        return
    con = sqlite3.connect(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as fh:
        con.executescript(fh.read())
    con.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
                ("admin", generate_password_hash("admin123"), "Administrator", "admin"))
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))
    for n in ["Engine", "Brakes", "Electrical", "Body", "Suspension", "Transmission", "Tyres & Wheels", "Accessories"]:
        con.execute("INSERT INTO categories(name) VALUES(?)", (n,))
    for n in ["Honda", "Hero", "Bajaj", "TVS", "Royal Enfield", "Yamaha", "Suzuki", "KTM"]:
        con.execute("INSERT INTO brands(name) VALUES(?)", (n,))
    con.execute("INSERT INTO locations(name,type) VALUES('Main Store','Store')")
    con.commit()
    con.close()
    print("Empty mspms.db created. Run `python seed.py` for demo data.")


ensure_db()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def qall(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def qone(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def run(sql, args=()):
    return get_db().execute(sql, args)


def commit():
    get_db().commit()


def S(key, default=""):
    """Read one value from the settings table."""
    row = qone("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


PARTS_SQL = """
SELECT p.*, c.name AS category, b.name AS brand, COALESCE(t.q,0) AS total_qty
  FROM parts p
  JOIN categories c ON c.id = p.category_id
  LEFT JOIN brands b ON b.id = p.brand_id
  LEFT JOIN (SELECT part_id, SUM(qty) q FROM stock GROUP BY part_id) t ON t.part_id = p.id
"""


def paginate(sql, args, page, per=10):
    total = qone(f"SELECT COUNT(*) c FROM ({sql})", args)["c"]
    pages = max(1, -(-total // per))
    page = min(max(page, 1), pages)
    rows = qall(f"{sql} LIMIT ? OFFSET ?", (*args, per, (page - 1) * per))
    return rows, dict(page=page, pages=pages, total=total, per=per)


def page_arg():
    try:
        return int(request.args.get("page", 1))
    except ValueError:
        return 1


# =====================================================================
# Small utilities
# =====================================================================
def inr(v, dec=2):
    """Format a number as Indian rupees with lakh/crore grouping."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return v
    neg, v = v < 0, abs(v)
    whole, _, frac = f"{v:.{dec}f}".partition(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + "₹" + whole + ("." + frac if dec else "")


@app.template_filter("inr")
def inr_filter(v, dec=2):
    return inr(v, dec)


@app.template_filter("dmy")
def dmy(v):
    try:
        return datetime.fromisoformat(str(v)[:19]).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return v or ""


@app.template_filter("dmyhm")
def dmyhm(v):
    try:
        return datetime.fromisoformat(str(v)[:19]).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return v or ""


@app.template_global()
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.template_global()
def csrf_input():
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


@app.template_global()
def page_url(p):
    """URL of the current page with ?page=p, keeping the other filters."""
    args = request.args.to_dict()
    args["page"] = p
    return url_for(request.endpoint, **(request.view_args or {}), **args)


@app.template_global()
def img_url(name):
    return url_for("static", filename="uploads/" + name) if name else None


def to_float(val, label, errs, lo=0.0, hi=None):
    try:
        v = float(str(val).strip() or 0)
    except ValueError:
        errs.append(f"{label} must be a number.")
        return 0.0
    if v < lo or (hi is not None and v > hi):
        errs.append(f"{label} must be between {lo:g} and {hi:g}." if hi is not None else f"{label} cannot be less than {lo:g}.")
    return v


def to_int(val, label, errs, lo=0, hi=None):
    try:
        v = int(str(val).strip() or 0)
    except ValueError:
        errs.append(f"{label} must be a whole number.")
        return 0
    if v < lo or (hi is not None and v > hi):
        errs.append(f"{label} must be between {lo} and {hi}." if hi is not None else f"{label} cannot be less than {lo}.")
    return v


def flash_all(errs):
    for e in errs:
        flash(e, "danger")


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.is_json


def safe_next(default):
    nxt = request.form.get("next") or request.args.get("next") or ""
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default


def next_no(table, col, prefix):
    n = qone(f"SELECT COALESCE(MAX(id),0)+1 n FROM {table}")["n"]
    while True:
        no = f"{prefix}-{date.today().year}-{n:04d}"
        if not qone(f"SELECT 1 FROM {table} WHERE {col}=?", (no,)):
            return no
        n += 1


def log(action, details, part_id=None):
    run("INSERT INTO activity_log(part_id,action,details,user_id) VALUES(?,?,?,?)",
        (part_id, action, details, g.user["id"] if g.get("user") else None))


def move(part_id, loc_id, qty, mtype, ref="", reason=""):
    """Record a stock movement; the DB trigger updates the stock table."""
    run("""INSERT INTO stock_movements(part_id,location_id,qty_change,movement_type,reference,reason,user_id)
           VALUES(?,?,?,?,?,?,?)""", (part_id, loc_id, qty, mtype, ref, reason, g.user["id"]))


def location_qty(part_id, loc_id):
    r = qone("SELECT qty FROM stock WHERE part_id=? AND location_id=?", (part_id, loc_id))
    return r["qty"] if r else 0


def calc_totals(items, discount):
    """items: dicts with qty, price, gst. Discount (Rs) is spread proportionally before GST."""
    sub = sum(i["qty"] * i["price"] for i in items)
    discount = min(max(discount, 0), sub)
    ratio = discount / sub if sub else 0
    gst = sum(i["qty"] * i["price"] * (1 - ratio) * i["gst"] / 100 for i in items)
    return round(sub, 2), round(discount, 2), round(gst, 2), round(sub - discount + gst, 2)


def part_json(r):
    stock = {str(s["location_id"]): s["qty"] for s in qall("SELECT location_id, qty FROM stock WHERE part_id=?", (r["id"],))}
    return dict(id=r["id"], part_no=r["part_no"], name=r["name"], barcode=r["barcode"], brand=r["brand"],
                category=r["category"], price=r["selling_price"], cost=r["cost_price"], gst=r["gst_percent"],
                total_qty=r["total_qty"], reorder_level=r["reorder_level"], rack=r["rack"],
                image=img_url(r["image"]), stock=stock, url=url_for("part_detail", pid=r["id"]))


def months_back(n):
    y, m = date.today().year, date.today().month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


# =====================================================================
# Security: login, CSRF, roles
# =====================================================================
@app.before_request
def before_request():
    g.user = None
    if session.get("uid"):
        g.user = qone("SELECT * FROM users WHERE id=? AND active=1", (session["uid"],))
        if g.user is None:
            session.pop("uid", None)
    if request.endpoint in (None, "static"):
        return None
    if request.method == "POST":  # CSRF protection for every POST
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not session.get("_csrf") or not secrets.compare_digest(token, session["_csrf"]):
            abort(400)
    if g.user is None and request.endpoint not in ("login", "signup"):
        if request.path.startswith("/api/"):
            return jsonify(error="Login required"), 401
        return redirect(url_for("login", next=request.path if request.method == "GET" else None))
    return None


def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


manager_up = roles_required("admin", "manager")
admin_only = roles_required("admin")


@app.context_processor
def inject_globals():
    ctx = dict(CREDIT=CREDIT, shop_name=S("shop_name", "MSPMS"))
    if g.get("user"):
        ctx["low_count"] = qone(f"SELECT COUNT(*) c FROM ({PARTS_SQL}) WHERE total_qty <= reorder_level")["c"]
        ctx["low_list"] = qall(f"{PARTS_SQL} WHERE COALESCE(t.q,0) <= p.reorder_level ORDER BY total_qty LIMIT 6")
    return ctx


def render_error(code, title, msg):
    """Error pages: full layout when logged in, plain page otherwise."""
    tpl = "error.html" if g.get("user") else "error_plain.html"
    return render_template(tpl, code=code, title=title, msg=msg), code


@app.errorhandler(400)
def err400(_e):
    return render_error(400, "Invalid request", "The form expired or was tampered with. Go back, refresh the page and try again.")


@app.errorhandler(403)
def err403(_e):
    return render_error(403, "Not allowed", "Your role does not have access to this action.")


@app.errorhandler(404)
def err404(_e):
    return render_error(404, "Page not found", "The page you are looking for does not exist.")


@app.errorhandler(500)
def err500(_e):
    return render_error(500, "Something went wrong", "An unexpected error occurred. Please try again.")


# =====================================================================
# 1. Login / Sign up / Logout
# =====================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    remembered = request.cookies.get("mspms_user", "")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = qone("SELECT * FROM users WHERE username=?", (username,)) if username else None
        if user and user["active"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["uid"] = user["id"]
            session.permanent = bool(request.form.get("remember"))
            resp = redirect(safe_next(url_for("dashboard")))
            if request.form.get("remember"):
                resp.set_cookie("mspms_user", user["username"], max_age=30 * 86400, samesite="Lax")
            else:
                resp.delete_cookie("mspms_user")
            flash(f"Welcome back, {user['full_name']}!", "success")
            return resp
        flash("Invalid user ID or password." if not user or user["active"] else "This account is disabled.", "danger")
        remembered = username
    return render_template("login.html", remembered=remembered)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("dashboard"))
    f = request.form
    if request.method == "POST":
        errs = []
        full_name, username = f.get("full_name", "").strip(), f.get("username", "").strip()
        email, pw, pw2 = f.get("email", "").strip(), f.get("password", ""), f.get("confirm", "")
        if len(full_name) < 2:
            errs.append("Please enter your full name.")
        if not re.fullmatch(r"[A-Za-z0-9_.]{3,30}", username):
            errs.append("User ID must be 3-30 letters, digits, dot or underscore.")
        elif qone("SELECT 1 FROM users WHERE username=?", (username,)):
            errs.append("That User ID is already taken.")
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errs.append("Enter a valid email address.")
        if len(pw) < 6:
            errs.append("Password must be at least 6 characters.")
        if pw != pw2:
            errs.append("Passwords do not match.")
        if not errs:
            run("INSERT INTO users(username,password_hash,full_name,email,role) VALUES(?,?,?,?,'staff')",
                (username, generate_password_hash(pw), full_name, email))
            commit()
            flash("Account created. Please log in with your new User ID.", "success")
            return redirect(url_for("login"))
        flash_all(errs)
    return render_template("signup.html", f=f)


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        f, errs = request.form, []
        full_name, email = f.get("full_name", "").strip(), f.get("email", "").strip()
        if len(full_name) < 2:
            errs.append("Name is required.")
        if f.get("new_password"):
            if not check_password_hash(g.user["password_hash"], f.get("current_password", "")):
                errs.append("Current password is wrong.")
            if len(f["new_password"]) < 6:
                errs.append("New password must be at least 6 characters.")
            if f["new_password"] != f.get("confirm"):
                errs.append("New passwords do not match.")
        if errs:
            flash_all(errs)
        else:
            run("UPDATE users SET full_name=?, email=? WHERE id=?", (full_name, email, g.user["id"]))
            if f.get("new_password"):
                run("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(f["new_password"]), g.user["id"]))
            commit()
            flash("Profile updated.", "success")
            return redirect(url_for("profile"))
    return render_template("profile.html")


# =====================================================================
# 2. Dashboard
# =====================================================================
@app.route("/")
def dashboard():
    kpi = dashboard_data()["kpi"]
    return render_template("dashboard.html", kpi=kpi)


def dashboard_data():
    kpi = dict(
        parts=qone("SELECT COUNT(*) c FROM parts")["c"],
        bikes=qone("SELECT COUNT(*) c FROM bike_models")["c"],
        sales=qone("SELECT COALESCE(SUM(total-returned_amount),0) v FROM sales")["v"],
        low=qone(f"SELECT COUNT(*) c FROM ({PARTS_SQL}) WHERE total_qty <= reorder_level")["c"],
        stock_value=qone("""SELECT COALESCE(SUM(s.qty*p.cost_price),0) v FROM stock s JOIN parts p ON p.id=s.part_id""")["v"],
    )
    cats = qall("""SELECT c.name, COUNT(p.id) n FROM categories c LEFT JOIN parts p ON p.category_id=c.id
                   GROUP BY c.id ORDER BY c.id""")
    months = months_back(6)
    sales_by = {r["m"]: r["v"] for r in qall(
        "SELECT strftime('%Y-%m',sale_date) m, SUM(total-returned_amount) v FROM sales GROUP BY m")}
    inv_by = {r["m"]: r["v"] for r in qall(
        """SELECT strftime('%Y-%m',m.created_at) m, SUM(m.qty_change*p.cost_price) v
           FROM stock_movements m JOIN parts p ON p.id=m.part_id GROUP BY m""")}
    inventory = [round(sum(v for mo, v in inv_by.items() if mo <= m), 2) for m in months]
    labels = [datetime.strptime(m, "%Y-%m").strftime("%b %y") for m in months]
    recent = qall("""SELECT a.action, a.details, a.created_at, p.name AS part, p.id AS part_id
                     FROM activity_log a LEFT JOIN parts p ON p.id=a.part_id ORDER BY a.id DESC LIMIT 10""")
    low = qall(f"{PARTS_SQL} WHERE COALESCE(t.q,0) <= p.reorder_level ORDER BY total_qty, p.name LIMIT 8")
    return dict(
        kpi=kpi,
        categories=dict(labels=[c["name"] for c in cats], data=[c["n"] for c in cats]),
        inventory=dict(labels=labels, data=inventory),
        sales=dict(labels=labels, data=[round(sales_by.get(m, 0), 2) for m in months]),
        recent=[dict(part=r["part"] or "-", part_id=r["part_id"], action=r["action"], details=r["details"],
                     date=dmyhm(r["created_at"])) for r in recent],
        low=[dict(id=r["id"], name=r["name"], part_no=r["part_no"], qty=r["total_qty"], reorder=r["reorder_level"]) for r in low],
    )


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(dashboard_data())


# =====================================================================
# 3. Parts
# =====================================================================
SORTS = {"name": "p.name", "part_no": "p.part_no", "price": "p.selling_price", "stock": "total_qty",
         "category": "c.name", "brand": "b.name", "new": "p.id"}


def filtered_parts_sql():
    a = request.args
    where, args = [], []
    q = a.get("q", "").strip()
    if q:
        where.append("(p.name LIKE ? OR p.part_no LIKE ? OR p.barcode LIKE ?)")
        args += [f"%{q}%"] * 3
    if a.get("category"):
        where.append("p.category_id = ?")
        args.append(a["category"])
    if a.get("brand"):
        where.append("p.brand_id = ?")
        args.append(a["brand"])
    if a.get("bike"):
        where.append("EXISTS (SELECT 1 FROM part_compatibility pc WHERE pc.part_id=p.id AND pc.bike_model_id=?)")
        args.append(a["bike"])
    if a.get("status") == "low":
        where.append("COALESCE(t.q,0) <= p.reorder_level AND COALESCE(t.q,0) > 0")
    elif a.get("status") == "out":
        where.append("COALESCE(t.q,0) = 0")
    elif a.get("status") == "ok":
        where.append("COALESCE(t.q,0) > p.reorder_level")
    sql = PARTS_SQL + (" WHERE " + " AND ".join(where) if where else "")
    direction = "DESC" if a.get("dir") == "desc" else "ASC"
    return sql + f" ORDER BY {SORTS.get(a.get('sort'), 'p.name')} {direction}", args


def bike_choices():
    return qall("""SELECT bm.id, b.name || ' ' || bm.model || ' (' || bm.variant || ')' AS label
                   FROM bike_models bm JOIN brands b ON b.id=bm.brand_id ORDER BY b.name, bm.model""")


@app.route("/parts")
def parts_list():
    sql, args = filtered_parts_sql()
    rows, pg = paginate(sql, args, page_arg(), 10)
    return render_template("parts.html", parts=rows, pg=pg, bikes=bike_choices(),
                           categories=qall("SELECT * FROM categories ORDER BY name"),
                           brands=qall("SELECT * FROM brands ORDER BY name"), a=request.args,
                           locations=qall("SELECT * FROM locations ORDER BY name"))


@app.route("/parts/export")
def parts_export():
    sql, args = filtered_parts_sql()
    rows = qall(sql, args)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Part No", "Name", "Category", "Brand", "Cost", "Selling Price", "GST %", "Stock", "Reorder Level", "Rack", "Barcode"])
    for r in rows:
        w.writerow([r["part_no"], r["name"], r["category"], r["brand"], r["cost_price"], r["selling_price"],
                    r["gst_percent"], r["total_qty"], r["reorder_level"], r["rack"], r["barcode"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=parts.csv"})


def gen_barcode():
    while True:
        code = "890" + "".join(secrets.choice("0123456789") for _ in range(9))
        if not qone("SELECT 1 FROM parts WHERE barcode=?", (code,)):
            return code


def save_image(fs):
    """Validate and store an uploaded part image; returns the stored filename or None."""
    if not fs or not fs.filename:
        return None
    ext = fs.filename.rsplit(".", 1)[-1].lower() if "." in fs.filename else ""
    if ext not in ALLOWED_IMG:
        raise ValueError("Image must be PNG, JPG, GIF or WEBP.")
    data = fs.read()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Image must be smaller than 2 MB.")
    name = uuid.uuid4().hex + "." + ext
    with open(os.path.join(UPLOAD_DIR, name), "wb") as fh:
        fh.write(data)
    return name


def remove_image(name):
    if name:
        try:
            os.remove(os.path.join(UPLOAD_DIR, name))
        except OSError:
            pass


def read_part_form(pid):
    f, errs = request.form, []
    d = dict(
        part_no=f.get("part_no", "").strip().upper(), name=f.get("name", "").strip(),
        category_id=f.get("category_id", ""), brand_id=f.get("brand_id", ""),
        description=f.get("description", "").strip(), rack=f.get("rack", "").strip(),
        barcode=f.get("barcode", "").strip(),
    )
    if not d["part_no"]:
        errs.append("Part number is required.")
    elif qone("SELECT 1 FROM parts WHERE part_no=? AND id<>?", (d["part_no"], pid or 0)):
        errs.append("Part number already exists.")
    if not d["name"]:
        errs.append("Part name is required.")
    if not qone("SELECT 1 FROM categories WHERE id=?", (d["category_id"],)):
        errs.append("Choose a category.")
    if d["brand_id"] and not qone("SELECT 1 FROM brands WHERE id=?", (d["brand_id"],)):
        errs.append("Choose a valid brand.")
    d["brand_id"] = d["brand_id"] or None
    if d["barcode"] and qone("SELECT 1 FROM parts WHERE barcode=? AND id<>?", (d["barcode"], pid or 0)):
        errs.append("Barcode already used by another part.")
    d["cost_price"] = to_float(f.get("cost_price"), "Cost price", errs)
    d["selling_price"] = to_float(f.get("selling_price"), "Selling price", errs)
    d["gst_percent"] = to_float(f.get("gst_percent", 18), "GST %", errs, 0, 100)
    d["reorder_level"] = to_int(f.get("reorder_level"), "Reorder level", errs)
    return d, errs


@app.route("/parts/new", methods=["GET", "POST"])
def part_new():
    return part_save(None)


@app.route("/parts/<int:pid>/edit", methods=["GET", "POST"])
def part_edit(pid):
    return part_save(pid)


def part_save(pid):
    part = qone("SELECT * FROM parts WHERE id=?", (pid,)) if pid else None
    if pid and not part:
        abort(404)
    selected = [r["bike_model_id"] for r in qall("SELECT bike_model_id FROM part_compatibility WHERE part_id=?", (pid,))] if pid else []
    form = dict(part) if part else dict(gst_percent=18, reorder_level=int(S("low_stock_default", "5") or 5))
    if request.method == "POST":
        d, errs = read_part_form(pid)
        selected = [int(x) for x in request.form.getlist("bikes") if x.isdigit()]
        init_qty = to_int(request.form.get("init_qty", 0), "Opening stock", errs) if not pid else 0
        new_img = None
        try:
            new_img = save_image(request.files.get("image"))
        except ValueError as e:
            errs.append(str(e))
        if errs:
            flash_all(errs)
            form = {**form, **d}
            remove_image(new_img)
        else:
            d["barcode"] = d["barcode"] or gen_barcode()
            if pid:
                run("""UPDATE parts SET part_no=?,name=?,category_id=?,brand_id=?,description=?,cost_price=?,selling_price=?,
                       gst_percent=?,reorder_level=?,rack=?,barcode=? WHERE id=?""",
                    (d["part_no"], d["name"], d["category_id"], d["brand_id"], d["description"], d["cost_price"],
                     d["selling_price"], d["gst_percent"], d["reorder_level"], d["rack"], d["barcode"], pid))
                if new_img:
                    remove_image(part["image"])
                    run("UPDATE parts SET image=? WHERE id=?", (new_img, pid))
                log("Updated", f"Part updated: {d['name']}", pid)
            else:
                pid = run("""INSERT INTO parts(part_no,name,category_id,brand_id,description,cost_price,selling_price,gst_percent,
                             reorder_level,rack,barcode,image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (d["part_no"], d["name"], d["category_id"], d["brand_id"], d["description"], d["cost_price"],
                           d["selling_price"], d["gst_percent"], d["reorder_level"], d["rack"], d["barcode"], new_img)).lastrowid
                log("Added", f"Part added: {d['name']}", pid)
                loc = request.form.get("init_loc")
                if init_qty > 0 and loc:
                    move(pid, int(loc), init_qty, "adjustment", "OPENING", "Opening stock")
            run("DELETE FROM part_compatibility WHERE part_id=?", (pid,))
            for b in selected:
                run("INSERT OR IGNORE INTO part_compatibility(part_id,bike_model_id) VALUES(?,?)", (pid, b))
            commit()
            flash("Part saved.", "success")
            return redirect(url_for("part_detail", pid=pid))
    return render_template("part_form.html", f=form, part=part, selected=selected,
                           categories=qall("SELECT * FROM categories ORDER BY name"),
                           brands=qall("SELECT * FROM brands ORDER BY name"),
                           bikes=qall("""SELECT bm.*, b.name brand FROM bike_models bm JOIN brands b ON b.id=bm.brand_id
                                         ORDER BY b.name, bm.model"""),
                           locations=qall("SELECT * FROM locations ORDER BY name"))


@app.route("/parts/<int:pid>")
def part_detail(pid):
    part = qone(PARTS_SQL + " WHERE p.id=?", (pid,))
    if not part:
        abort(404)
    return render_template(
        "part_detail.html", p=part,
        stock=qall("""SELECT l.id, l.name, l.type, COALESCE(s.qty,0) qty FROM locations l
                      LEFT JOIN stock s ON s.location_id=l.id AND s.part_id=? ORDER BY l.name""", (pid,)),
        bikes=qall("""SELECT bm.*, b.name brand FROM part_compatibility pc JOIN bike_models bm ON bm.id=pc.bike_model_id
                      JOIN brands b ON b.id=bm.brand_id WHERE pc.part_id=? ORDER BY b.name, bm.model""", (pid,)),
        moves=qall("""SELECT m.*, l.name loc FROM stock_movements m JOIN locations l ON l.id=m.location_id
                      WHERE m.part_id=? ORDER BY m.id DESC LIMIT 10""", (pid,)),
        locations=qall("SELECT * FROM locations ORDER BY name"))


@app.route("/parts/<int:pid>/delete", methods=["POST"])
@manager_up
def part_delete(pid):
    part = qone("SELECT * FROM parts WHERE id=?", (pid,))
    if not part:
        abort(404)
    try:
        run("DELETE FROM parts WHERE id=?", (pid,))
        log("Deleted", f"Part deleted: {part['name']}")
        commit()
        remove_image(part["image"])
        flash("Part deleted.", "success")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("This part is used in sales or purchases and cannot be deleted.", "danger")
        return redirect(url_for("part_detail", pid=pid))
    return redirect(url_for("parts_list"))


@app.route("/parts/labels")
def part_labels():
    ids = [i for i in request.args.getlist("ids") if i.isdigit()]
    if not ids:
        flash("Select at least one part to print labels.", "warning")
        return redirect(url_for("parts_list"))
    marks = ",".join("?" * len(ids))
    rows = qall(f"{PARTS_SQL} WHERE p.id IN ({marks}) ORDER BY p.name", ids)
    copies = min(max(int(request.args.get("copies", 1) or 1), 1), 50)
    return render_template("labels.html", parts=rows, copies=copies)


@app.route("/parts/<int:pid>/label")
def part_label(pid):
    return redirect(url_for("part_labels", ids=pid, copies=request.args.get("copies", 1)))


# ---- JSON APIs used by live search, POS and scanner
@app.route("/api/parts/search")
def api_parts_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    rows = qall(PARTS_SQL + " WHERE p.name LIKE ? OR p.part_no LIKE ? OR p.barcode LIKE ? ORDER BY p.name LIMIT 8", [f"%{q}%"] * 3)
    return jsonify([part_json(r) for r in rows])


@app.route("/api/part/barcode/<code>")
def api_part_barcode(code):
    row = qone(PARTS_SQL + " WHERE p.barcode=? OR p.part_no=?", (code.strip(), code.strip()))
    return (jsonify(part_json(row)) if row else (jsonify(error="No part found for this barcode"), 404))


@app.route("/api/part/<int:pid>")
def api_part(pid):
    row = qone(PARTS_SQL + " WHERE p.id=?", (pid,))
    return (jsonify(part_json(row)) if row else (jsonify(error="Not found"), 404))


# =====================================================================
# 4. Barcode scanning
# =====================================================================
@app.route("/scan")
def scan():
    return render_template("scan.html", locations=qall("SELECT * FROM locations ORDER BY name"))


# =====================================================================
# 5. Vehicles / Bike models
# =====================================================================
@app.route("/bikes")
def bikes():
    a = request.args
    where, args = [], []
    if a.get("q"):
        where.append("(bm.model LIKE ? OR bm.variant LIKE ?)")
        args += [f"%{a['q'].strip()}%"] * 2
    if a.get("brand"):
        where.append("bm.brand_id=?")
        args.append(a["brand"])
    sql = """SELECT bm.*, b.name brand, (SELECT COUNT(*) FROM part_compatibility pc WHERE pc.bike_model_id=bm.id) parts_count
             FROM bike_models bm JOIN brands b ON b.id=bm.brand_id"""
    sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY b.name, bm.model"
    rows, pg = paginate(sql, args, page_arg(), 10)
    return render_template("bikes.html", bikes=rows, pg=pg, brands=qall("SELECT * FROM brands ORDER BY name"), a=a)


@app.route("/bikes/save", methods=["POST"])
def bike_save():
    f, errs = request.form, []
    bid = f.get("id")
    model, variant = f.get("model", "").strip(), f.get("variant", "").strip() or "Standard"
    yf = to_int(f.get("year_from"), "Year from", errs, 1950, 2100)
    yt = to_int(f.get("year_to"), "Year to", errs, 1950, 2100)
    cc = to_int(f.get("engine_cc"), "Engine cc", errs, 25, 2500)
    if not model:
        errs.append("Model name is required.")
    if not qone("SELECT 1 FROM brands WHERE id=?", (f.get("brand_id"),)):
        errs.append("Choose a brand.")
    if yt < yf:
        errs.append("'Year to' cannot be earlier than 'Year from'.")
    if not errs:
        try:
            if bid:
                run("UPDATE bike_models SET brand_id=?,model=?,variant=?,year_from=?,year_to=?,engine_cc=? WHERE id=?",
                    (f["brand_id"], model, variant, yf, yt, cc, bid))
            else:
                run("INSERT INTO bike_models(brand_id,model,variant,year_from,year_to,engine_cc) VALUES(?,?,?,?,?,?)",
                    (f["brand_id"], model, variant, yf, yt, cc))
            commit()
            flash("Bike model saved.", "success")
        except sqlite3.IntegrityError:
            get_db().rollback()
            flash("This brand/model/variant already exists.", "danger")
    else:
        flash_all(errs)
    return redirect(request.referrer or url_for("bikes"))


@app.route("/bikes/<int:bid>/delete", methods=["POST"])
@manager_up
def bike_delete(bid):
    run("DELETE FROM bike_models WHERE id=?", (bid,))
    commit()
    flash("Bike model deleted.", "success")
    return redirect(url_for("bikes"))


@app.route("/bikes/<int:bid>")
def bike_detail(bid):
    bike = qone("SELECT bm.*, b.name brand FROM bike_models bm JOIN brands b ON b.id=bm.brand_id WHERE bm.id=?", (bid,))
    if not bike:
        abort(404)
    parts = qall(PARTS_SQL + " WHERE p.id IN (SELECT part_id FROM part_compatibility WHERE bike_model_id=?) ORDER BY c.name, p.name", (bid,))
    others = qall("""SELECT id, part_no, name FROM parts WHERE id NOT IN
                     (SELECT part_id FROM part_compatibility WHERE bike_model_id=?) ORDER BY name""", (bid,))
    return render_template("bike_detail.html", bike=bike, parts=parts, others=others, brands=qall("SELECT * FROM brands ORDER BY name"))


@app.route("/bikes/<int:bid>/compat", methods=["POST"])
def bike_compat(bid):
    action = request.form.get("action")
    ids = [int(i) for i in request.form.getlist("part_ids") if i.isdigit()]
    for pid in ids:
        if action == "add":
            run("INSERT OR IGNORE INTO part_compatibility(part_id,bike_model_id) VALUES(?,?)", (pid, bid))
        else:
            run("DELETE FROM part_compatibility WHERE part_id=? AND bike_model_id=?", (pid, bid))
    commit()
    flash(f"{len(ids)} part(s) {'added to' if action == 'add' else 'removed from'} this bike.", "success")
    return redirect(url_for("bike_detail", bid=bid))


@app.route("/bikes/find")
def bike_finder():
    return render_template("bike_finder.html", bikes=qall("""SELECT bm.id, b.name brand, bm.model, bm.variant, bm.year_from, bm.year_to
                           FROM bike_models bm JOIN brands b ON b.id=bm.brand_id ORDER BY b.name, bm.model"""))


@app.route("/api/bike/<int:bid>/parts")
def api_bike_parts(bid):
    rows = qall(PARTS_SQL + " WHERE p.id IN (SELECT part_id FROM part_compatibility WHERE bike_model_id=?) ORDER BY c.name, p.name", (bid,))
    return jsonify([part_json(r) for r in rows])


# =====================================================================
# 6 + 11. Inventory: stock overview, ledger, adjustments, low/out/dead
#          stock, locations and transfers
# =====================================================================
INV_VIEWS = ("stock", "ledger", "adjust", "low", "out", "dead", "locations", "transfers")


@app.route("/inventory", defaults={"view": "stock"})
@app.route("/inventory/<view>")
def inventory(view):
    if view not in INV_VIEWS:
        abort(404)
    a = request.args
    locs = qall("SELECT * FROM locations ORDER BY name")
    ctx = dict(view=view, locations=locs, a=a, rows=[], pg=None)
    q = a.get("q", "").strip()
    like = [f"%{q}%"] * 3
    if view == "stock":
        sql = PARTS_SQL + (" WHERE p.name LIKE ? OR p.part_no LIKE ? OR p.barcode LIKE ?" if q else "") + " ORDER BY p.name"
        rows, pg = paginate(sql, like if q else [], page_arg(), 12)
        matrix = {}
        if rows:
            marks = ",".join("?" * len(rows))
            for s in qall(f"SELECT part_id, location_id, qty FROM stock WHERE part_id IN ({marks})", [r["id"] for r in rows]):
                matrix[(s["part_id"], s["location_id"])] = s["qty"]
        ctx.update(rows=rows, pg=pg, matrix=matrix,
                   totals=qone("""SELECT COALESCE(SUM(s.qty),0) units, COALESCE(SUM(s.qty*p.cost_price),0) cost,
                                  COALESCE(SUM(s.qty*p.selling_price),0) retail FROM stock s JOIN parts p ON p.id=s.part_id"""))
    elif view == "ledger":
        where, args = [], []
        if q:
            where.append("(p.name LIKE ? OR p.part_no LIKE ? OR m.reference LIKE ?)")
            args += like
        if a.get("type"):
            where.append("m.movement_type=?")
            args.append(a["type"])
        if a.get("location"):
            where.append("m.location_id=?")
            args.append(a["location"])
        if a.get("from"):
            where.append("date(m.created_at) >= ?")
            args.append(a["from"])
        if a.get("to"):
            where.append("date(m.created_at) <= ?")
            args.append(a["to"])
        sql = """SELECT m.*, p.part_no, p.name pname, l.name loc, u.full_name uname FROM stock_movements m
                 JOIN parts p ON p.id=m.part_id JOIN locations l ON l.id=m.location_id LEFT JOIN users u ON u.id=m.user_id"""
        sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC"
        ctx["rows"], ctx["pg"] = paginate(sql, args, page_arg(), 15)
    elif view == "adjust":
        ctx["parts_all"] = qall("SELECT id, part_no, name FROM parts ORDER BY name")
        ctx["rows"] = qall("""SELECT m.*, p.part_no, p.name pname, l.name loc FROM stock_movements m JOIN parts p ON p.id=m.part_id
                              JOIN locations l ON l.id=m.location_id WHERE m.movement_type='adjustment' AND m.reference<>'OPENING'
                              ORDER BY m.id DESC LIMIT 12""")
    elif view in ("low", "out"):
        cond = ("total_qty <= reorder_level AND total_qty > 0" if view == "low" else "total_qty = 0")
        ctx["rows"], ctx["pg"] = paginate(f"SELECT * FROM ({PARTS_SQL}) WHERE {cond} ORDER BY total_qty, name", [], page_arg(), 12)
    elif view == "dead":
        days = min(max(int(a.get("days", 90) or 90), 7), 730) if str(a.get("days", "90")).isdigit() else 90
        sql = PARTS_SQL + """ WHERE COALESCE(t.q,0) > 0 AND NOT EXISTS (SELECT 1 FROM stock_movements m WHERE m.part_id=p.id
                AND m.movement_type='sale' AND m.created_at >= date('now','localtime',?)) ORDER BY total_qty*p.cost_price DESC"""
        rows = qall(sql, (f"-{days} days",))
        last = {r["part_id"]: r["d"] for r in qall("SELECT part_id, MAX(created_at) d FROM stock_movements WHERE movement_type='sale' GROUP BY part_id")}
        ctx.update(rows=rows, days=days, last_sold=last, dead_value=sum(r["total_qty"] * r["cost_price"] for r in rows))
    elif view == "locations":
        ctx["rows"] = qall("""SELECT l.*, COUNT(DISTINCT CASE WHEN s.qty>0 THEN s.part_id END) parts_count,
                              COALESCE(SUM(s.qty),0) units, COALESCE(SUM(s.qty*p.cost_price),0) value
                              FROM locations l LEFT JOIN stock s ON s.location_id=l.id LEFT JOIN parts p ON p.id=s.part_id
                              GROUP BY l.id ORDER BY l.name""")
    elif view == "transfers":
        sql = """SELECT o.reference ref, o.created_at, p.part_no, p.name pname, -o.qty_change qty, lf.name from_loc,
                        lt.name to_loc, o.reason, u.full_name uname
                 FROM stock_movements o
                 JOIN stock_movements i ON i.reference=o.reference AND i.part_id=o.part_id AND i.movement_type='transfer_in'
                 JOIN parts p ON p.id=o.part_id JOIN locations lf ON lf.id=o.location_id JOIN locations lt ON lt.id=i.location_id
                 LEFT JOIN users u ON u.id=o.user_id WHERE o.movement_type='transfer_out' ORDER BY o.id DESC"""
        ctx["rows"], ctx["pg"] = paginate(sql, [], page_arg(), 12)
        ctx["parts_all"] = qall("SELECT id, part_no, name FROM parts ORDER BY name")
    return render_template("inventory.html", **ctx)


@app.route("/inventory/adjust", methods=["POST"])
def stock_adjust():
    f, errs = request.form, []
    part = qone("SELECT * FROM parts WHERE id=?", (f.get("part_id"),))
    loc = qone("SELECT * FROM locations WHERE id=?", (f.get("location_id"),))
    mode, reason = f.get("mode"), f.get("reason", "").strip()
    qty = to_int(f.get("qty"), "Quantity", errs, 0)
    if not part or not loc:
        errs.append("Choose a valid part and location.")
    if mode not in ("add", "remove", "set"):
        errs.append("Choose an adjustment type.")
    if not reason:
        errs.append("Please give a reason for the adjustment.")
    msg = ""
    if not errs:
        cur = location_qty(part["id"], loc["id"])
        delta = qty if mode == "add" else (-qty if mode == "remove" else qty - cur)
        if mode != "set" and qty <= 0:
            errs.append("Quantity must be greater than zero.")
        elif delta == 0:
            errs.append("That would not change the stock.")
        else:
            try:
                move(part["id"], loc["id"], delta, "adjustment", "ADJ", reason)
                log("Adjusted", f"Stock {'+' if delta > 0 else ''}{delta} at {loc['name']}: {reason}", part["id"])
                commit()
                msg = f"Stock updated: {part['name']} {'+' if delta > 0 else ''}{delta} at {loc['name']}."
            except sqlite3.IntegrityError:
                get_db().rollback()
                errs.append(f"Not enough stock at {loc['name']} (available: {cur}).")
    if wants_json():
        if errs:
            return jsonify(ok=False, error=" ".join(errs)), 400
        total = qone("SELECT COALESCE(SUM(qty),0) t FROM stock WHERE part_id=?", (part["id"],))["t"]
        return jsonify(ok=True, message=msg, total=total)
    flash_all(errs) if errs else flash(msg, "success")
    return redirect(safe_next(url_for("inventory", view="adjust")))


@app.route("/locations/save", methods=["POST"])
@manager_up
def location_save():
    f, errs = request.form, []
    name, typ = f.get("name", "").strip(), f.get("type", "Store")
    if not name:
        errs.append("Location name is required.")
    if typ not in ("Store", "Warehouse", "Rack"):
        errs.append("Invalid location type.")
    if not errs:
        try:
            if f.get("id"):
                run("UPDATE locations SET name=?, type=?, address=? WHERE id=?", (name, typ, f.get("address", "").strip(), f["id"]))
            else:
                run("INSERT INTO locations(name,type,address) VALUES(?,?,?)", (name, typ, f.get("address", "").strip()))
            commit()
            flash("Location saved.", "success")
        except sqlite3.IntegrityError:
            get_db().rollback()
            flash("A location with this name already exists.", "danger")
    else:
        flash_all(errs)
    return redirect(url_for("inventory", view="locations"))


@app.route("/locations/<int:lid>/delete", methods=["POST"])
@manager_up
def location_delete(lid):
    try:
        run("DELETE FROM locations WHERE id=?", (lid,))
        commit()
        flash("Location deleted.", "success")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("This location has stock history and cannot be deleted.", "danger")
    return redirect(url_for("inventory", view="locations"))


@app.route("/inventory/transfer", methods=["POST"])
def stock_transfer():
    f, errs = request.form, []
    part = qone("SELECT * FROM parts WHERE id=?", (f.get("part_id"),))
    src = qone("SELECT * FROM locations WHERE id=?", (f.get("from_loc"),))
    dst = qone("SELECT * FROM locations WHERE id=?", (f.get("to_loc"),))
    qty = to_int(f.get("qty"), "Quantity", errs, 1)
    if not (part and src and dst):
        errs.append("Choose a part, a source and a destination.")
    elif src["id"] == dst["id"]:
        errs.append("Source and destination must be different.")
    if not errs:
        ref = f"TRF-{datetime.now():%y%m%d%H%M%S}{secrets.randbelow(90) + 10}"
        notes = f.get("notes", "").strip() or "Stock transfer"
        try:
            move(part["id"], src["id"], -qty, "transfer_out", ref, notes)
            move(part["id"], dst["id"], qty, "transfer_in", ref, notes)
            log("Transferred", f"Moved {qty} x {part['name']} from {src['name']} to {dst['name']}", part["id"])
            commit()
            flash(f"Transferred {qty} x {part['name']} to {dst['name']} ({ref}).", "success")
        except sqlite3.IntegrityError:
            get_db().rollback()
            flash(f"Not enough stock at {src['name']} (available: {location_qty(part['id'], src['id'])}).", "danger")
    else:
        flash_all(errs)
    return redirect(url_for("inventory", view="transfers"))


# =====================================================================
# 7. Purchases
# =====================================================================
def pay_status(total, paid):
    return "paid" if total > 0 and paid >= total - 0.005 else ("partial" if paid > 0 else "unpaid")


@app.route("/purchases")
def purchases():
    a = request.args
    where, args = [], []
    if a.get("q"):
        where.append("(pu.po_no LIKE ? OR s.name LIKE ?)")
        args += [f"%{a['q'].strip()}%"] * 2
    for key, col in (("status", "pu.status"), ("payment", "pu.payment_status"), ("supplier", "pu.supplier_id")):
        if a.get(key):
            where.append(f"{col}=?")
            args.append(a[key])
    sql = """SELECT pu.*, s.name supplier, l.name location,
             (SELECT COUNT(*) FROM purchase_items WHERE purchase_id=pu.id) n_items
             FROM purchases pu JOIN suppliers s ON s.id=pu.supplier_id JOIN locations l ON l.id=pu.location_id"""
    sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY pu.id DESC"
    rows, pg = paginate(sql, args, page_arg(), 10)
    return render_template("purchases.html", rows=rows, pg=pg, a=a, suppliers=qall("SELECT * FROM suppliers ORDER BY name"))


@app.route("/purchases/new", methods=["GET", "POST"])
def purchase_new():
    if request.method == "POST":
        f, errs = request.form, []
        sup = qone("SELECT * FROM suppliers WHERE id=?", (f.get("supplier_id"),))
        loc = qone("SELECT * FROM locations WHERE id=?", (f.get("location_id"),))
        if not sup:
            errs.append("Choose a supplier.")
        if not loc:
            errs.append("Choose the receiving location.")
        lines = {}
        for pid, qty, cost in zip(f.getlist("part_id"), f.getlist("qty"), f.getlist("unit_cost")):
            if not pid:
                continue
            part = qone("SELECT * FROM parts WHERE id=?", (pid,))
            if not part:
                errs.append("One of the selected parts no longer exists.")
                continue
            q = to_int(qty, f"Quantity for {part['name']}", errs, 1)
            c = to_float(cost, f"Unit cost for {part['name']}", errs)
            if part["id"] in lines:
                lines[part["id"]]["qty"] += q
            else:
                lines[part["id"]] = dict(part=part, qty=q, cost=c)
        if not lines:
            errs.append("Add at least one part to the purchase order.")
        order_date = f.get("order_date") or date.today().isoformat()
        try:
            date.fromisoformat(order_date)
        except ValueError:
            errs.append("Invalid order date.")
        if errs:
            flash_all(errs)
        else:
            total = round(sum(l["qty"] * l["cost"] * (1 + l["part"]["gst_percent"] / 100) for l in lines.values()), 2)
            po = next_no("purchases", "po_no", S("po_prefix", "PO") or "PO")
            pid_ = run("""INSERT INTO purchases(po_no,supplier_id,location_id,order_date,total,notes,user_id)
                          VALUES(?,?,?,?,?,?,?)""", (po, sup["id"], loc["id"], order_date, total, f.get("notes", "").strip(), g.user["id"])).lastrowid
            for l in lines.values():
                run("INSERT INTO purchase_items(purchase_id,part_id,qty,unit_cost,gst_percent) VALUES(?,?,?,?,?)",
                    (pid_, l["part"]["id"], l["qty"], l["cost"], l["part"]["gst_percent"]))
            log("Purchased", f"Purchase order {po} created for {sup['name']}", next(iter(lines)))
            commit()
            flash(f"Purchase order {po} created.", "success")
            return redirect(url_for("purchase_detail", pid=pid_))
    prefill = []
    for pid in request.args.getlist("part_id"):
        p = qone(PARTS_SQL + " WHERE p.id=?", (pid,)) if pid.isdigit() else None
        if p:
            prefill.append(dict(id=p["id"], qty=max(p["reorder_level"] * 2 - p["total_qty"], p["reorder_level"], 1), cost=p["cost_price"]))
    parts = qall("SELECT id, part_no, name, cost_price, gst_percent FROM parts ORDER BY name")
    return render_template("purchase_form.html", suppliers=qall("SELECT * FROM suppliers ORDER BY name"),
                           locations=qall("SELECT * FROM locations ORDER BY name"), today=date.today().isoformat(),
                           parts=[dict(id=p["id"], label=f"{p['part_no']} - {p['name']}", cost=p["cost_price"], gst=p["gst_percent"]) for p in parts],
                           prefill=prefill)


@app.route("/purchases/<int:pid>")
def purchase_detail(pid):
    pu = qone("""SELECT pu.*, s.name supplier, s.phone sphone, s.gstin sgstin, l.name location FROM purchases pu
                 JOIN suppliers s ON s.id=pu.supplier_id JOIN locations l ON l.id=pu.location_id WHERE pu.id=?""", (pid,))
    if not pu:
        abort(404)
    items = qall("""SELECT pi.*, p.part_no, p.name FROM purchase_items pi JOIN parts p ON p.id=pi.part_id
                    WHERE pi.purchase_id=?""", (pid,))
    return render_template("purchase_detail.html", pu=pu, items=items)


@app.route("/purchases/<int:pid>/receive", methods=["POST"])
def purchase_receive(pid):
    pu = qone("SELECT * FROM purchases WHERE id=?", (pid,))
    if not pu:
        abort(404)
    if pu["status"] != "ordered":
        flash("Only orders in 'ordered' status can be received.", "warning")
        return redirect(url_for("purchase_detail", pid=pid))
    items = qall("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,))
    for it in items:
        move(it["part_id"], pu["location_id"], it["qty"], "purchase", pu["po_no"], "Purchase received")
    run("UPDATE purchases SET status='received', received_date=? WHERE id=?", (date.today().isoformat(), pid))
    log("Received", f"Received {pu['po_no']} ({len(items)} items)", items[0]["part_id"] if items else None)
    commit()
    flash(f"{pu['po_no']} received - stock increased for {len(items)} part(s).", "success")
    return redirect(url_for("purchase_detail", pid=pid))


@app.route("/purchases/<int:pid>/pay", methods=["POST"])
def purchase_pay(pid):
    pu = qone("SELECT * FROM purchases WHERE id=?", (pid,))
    if not pu or pu["status"] == "cancelled":
        abort(404)
    errs = []
    amt = to_float(request.form.get("amount"), "Payment amount", errs, 0.01)
    due = round(pu["total"] - pu["paid_amount"], 2)
    if amt > due + 0.005:
        errs.append(f"Payment cannot exceed the balance due ({inr(due)}).")
    if errs:
        flash_all(errs)
    else:
        paid = round(pu["paid_amount"] + amt, 2)
        run("UPDATE purchases SET paid_amount=?, payment_status=? WHERE id=?", (paid, pay_status(pu["total"], paid), pid))
        commit()
        flash(f"Payment of {inr(amt)} recorded.", "success")
    return redirect(url_for("purchase_detail", pid=pid))


@app.route("/purchases/<int:pid>/cancel", methods=["POST"])
def purchase_cancel(pid):
    pu = qone("SELECT * FROM purchases WHERE id=?", (pid,))
    if not pu or pu["status"] != "ordered":
        flash("Only open orders can be cancelled.", "warning")
    else:
        run("UPDATE purchases SET status='cancelled' WHERE id=?", (pid,))
        commit()
        flash(f"{pu['po_no']} cancelled.", "success")
    return redirect(url_for("purchase_detail", pid=pid))


# =====================================================================
# 8. Sales / Billing
# =====================================================================
@app.route("/sales")
def sales():
    a = request.args
    where, args = [], []
    if a.get("q"):
        where.append("(s.invoice_no LIKE ? OR c.name LIKE ?)")
        args += [f"%{a['q'].strip()}%"] * 2
    if a.get("from"):
        where.append("date(s.sale_date) >= ?")
        args.append(a["from"])
    if a.get("to"):
        where.append("date(s.sale_date) <= ?")
        args.append(a["to"])
    if a.get("status"):
        where.append("s.status=?")
        args.append(a["status"])
    base = """FROM sales s LEFT JOIN customers c ON c.id=s.customer_id JOIN locations l ON l.id=s.location_id""" + \
           (" WHERE " + " AND ".join(where) if where else "")
    rows, pg = paginate(f"SELECT s.*, c.name customer, l.name location {base} ORDER BY s.id DESC", args, page_arg(), 10)
    summ = qone(f"SELECT COUNT(*) n, COALESCE(SUM(s.total-s.returned_amount),0) v FROM sales s LEFT JOIN customers c ON c.id=s.customer_id {'WHERE ' + ' AND '.join(where) if where else ''}", args)
    return render_template("sales.html", rows=rows, pg=pg, a=a, summ=summ)


@app.route("/sales/new", methods=["GET", "POST"])
def sale_new():
    if request.method == "POST":
        f, errs = request.form, []
        loc = qone("SELECT * FROM locations WHERE id=?", (f.get("location_id"),))
        cust = qone("SELECT * FROM customers WHERE id=?", (f.get("customer_id"),)) if f.get("customer_id") else None
        mode = f.get("payment_mode", "Cash")
        if not loc:
            errs.append("Choose the selling location.")
        if mode not in ("Cash", "UPI", "Card", "Credit"):
            errs.append("Choose a payment mode.")
        lines = {}
        for pid, qty in zip(f.getlist("part_id"), f.getlist("qty")):
            part = qone("SELECT * FROM parts WHERE id=?", (pid,))
            if not part:
                continue
            q = to_int(qty, f"Quantity for {part['name']}", errs, 1)
            if part["id"] in lines:
                lines[part["id"]]["qty"] += q
            else:
                lines[part["id"]] = dict(part=part, qty=q, price=part["selling_price"], gst=part["gst_percent"])
        if not lines:
            errs.append("Add at least one part to the bill.")
        sub = sum(l["qty"] * l["price"] for l in lines.values())
        dval = to_float(f.get("discount"), "Discount", errs)
        discount = sub * dval / 100 if f.get("discount_type") == "percent" else dval
        if f.get("discount_type") == "percent" and dval > 100:
            errs.append("Discount cannot exceed 100%.")
        if discount > sub + 0.005:
            errs.append("Discount cannot be more than the bill subtotal.")
        sub, discount, gst, total = calc_totals(list(lines.values()), discount)
        paid_raw = f.get("paid_amount", "").strip()
        paid = total if paid_raw == "" and mode != "Credit" else to_float(paid_raw, "Amount received", errs)
        if paid > total + 0.005:
            errs.append("Amount received cannot exceed the bill total.")
        if not cust and paid < total - 0.005:
            errs.append("Select a customer for credit / part-paid bills (walk-in bills must be paid in full).")
        if not errs and loc:
            inv = next_no("sales", "invoice_no", S("invoice_prefix", "INV") or "INV")
            try:
                sid = run("""INSERT INTO sales(invoice_no,customer_id,location_id,sale_date,subtotal,discount,gst_amount,total,
                             paid_amount,payment_mode,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                          (inv, cust["id"] if cust else None, loc["id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           sub, discount, gst, total, round(paid, 2), mode, g.user["id"])).lastrowid
                for l in lines.values():
                    run("""INSERT INTO sale_items(sale_id,part_id,qty,unit_price,cost_price,gst_percent) VALUES(?,?,?,?,?,?)""",
                        (sid, l["part"]["id"], l["qty"], l["price"], l["part"]["cost_price"], l["gst"]))
                    move(l["part"]["id"], loc["id"], -l["qty"], "sale", inv, "Sale")
                log("Sold", f"Invoice {inv} ({len(lines)} items)", next(iter(lines)))
                commit()
                flash(f"Invoice {inv} created.", "success")
                return redirect(url_for("sale_detail", sid=sid))
            except sqlite3.IntegrityError:
                get_db().rollback()
                errs.append(f"Not enough stock at {loc['name']} for one of the parts. Check availability and try again.")
        flash_all(errs)
    return render_template("sale_form.html", customers=qall("SELECT id, name, phone FROM customers ORDER BY name"),
                           locations=qall("SELECT * FROM locations ORDER BY name"),
                           preload=request.args.get("part_id", ""), cust_id=request.args.get("customer_id", ""))


def sale_or_404(sid):
    s = qone("""SELECT s.*, c.name customer, c.phone cphone, c.address caddress, c.bike_owned, l.name location,
                u.full_name cashier FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                JOIN locations l ON l.id=s.location_id LEFT JOIN users u ON u.id=s.user_id WHERE s.id=?""", (sid,))
    if not s:
        abort(404)
    items = qall("""SELECT si.*, p.part_no, p.name FROM sale_items si JOIN parts p ON p.id=si.part_id WHERE si.sale_id=?""", (sid,))
    return s, items


@app.route("/sales/<int:sid>")
def sale_detail(sid):
    s, items = sale_or_404(sid)
    return render_template("sale_detail.html", s=s, items=items, locations=qall("SELECT * FROM locations ORDER BY name"))


@app.route("/sales/<int:sid>/print")
def sale_print(sid):
    s, items = sale_or_404(sid)
    ratio = s["discount"] / s["subtotal"] if s["subtotal"] else 0
    lines = []
    for it in items:
        taxable = it["qty"] * it["unit_price"] * (1 - ratio)
        lines.append(dict(it=it, amount=it["qty"] * it["unit_price"], taxable=taxable, gst=taxable * it["gst_percent"] / 100))
    settings = {k: S(k) for k in ("shop_name", "shop_address", "shop_phone", "shop_email", "gst_number", "invoice_footer")}
    return render_template("invoice.html", s=s, lines=lines, st=settings)


@app.route("/sales/<int:sid>/return", methods=["POST"])
def sale_return(sid):
    s, items = sale_or_404(sid)
    loc = qone("SELECT * FROM locations WHERE id=?", (request.form.get("location_id"),))
    if not loc:
        flash("Choose where the returned stock goes.", "danger")
        return redirect(url_for("sale_detail", sid=sid))
    ratio = s["discount"] / s["subtotal"] if s["subtotal"] else 0
    refund, count, errs = 0.0, 0, []
    plan = []
    for it in items:
        r = to_int(request.form.get(f"ret_{it['id']}", 0), f"Return quantity for {it['name']}", errs, 0)
        if r > it["qty"] - it["returned_qty"]:
            errs.append(f"Cannot return more than {it['qty'] - it['returned_qty']} of {it['name']}.")
        elif r > 0:
            plan.append((it, r))
            refund += r * it["unit_price"] * (1 - ratio) * (1 + it["gst_percent"] / 100)
            count += r
    if not plan and not errs:
        errs.append("Enter a return quantity for at least one item.")
    if errs:
        flash_all(errs)
        return redirect(url_for("sale_detail", sid=sid))
    for it, r in plan:
        run("UPDATE sale_items SET returned_qty = returned_qty + ? WHERE id=?", (r, it["id"]))
        move(it["part_id"], loc["id"], r, "return_in", s["invoice_no"], "Customer return")
    refund = round(refund, 2)
    new_returned = round(s["returned_amount"] + refund, 2)
    fully = all(qone("SELECT qty=returned_qty ok FROM sale_items WHERE id=?", (it["id"],))["ok"] for it in items)
    new_paid = max(min(s["paid_amount"], round(s["total"] - new_returned, 2)), 0)
    run("UPDATE sales SET returned_amount=?, paid_amount=?, status=? WHERE id=?",
        (min(new_returned, s["total"]), new_paid, "returned" if fully else "partial_return", sid))
    log("Returned", f"{count} item(s) returned against {s['invoice_no']}", plan[0][0]["part_id"])
    commit()
    flash(f"Return processed. Refund value: {inr(refund)}.", "success")
    return redirect(url_for("sale_detail", sid=sid))


@app.route("/sales/<int:sid>/pay", methods=["POST"])
def sale_pay(sid):
    s, _ = sale_or_404(sid)
    errs = []
    amt = to_float(request.form.get("amount"), "Payment amount", errs, 0.01)
    due = round(s["total"] - s["returned_amount"] - s["paid_amount"], 2)
    if amt > due + 0.005:
        errs.append(f"Payment cannot exceed the balance due ({inr(due)}).")
    if errs:
        flash_all(errs)
    else:
        run("UPDATE sales SET paid_amount=? WHERE id=?", (round(s["paid_amount"] + amt, 2), sid))
        commit()
        flash(f"Payment of {inr(amt)} received.", "success")
    return redirect(url_for("sale_detail", sid=sid))


# =====================================================================
# 9. Customers
# =====================================================================
CUST_SQL = """SELECT c.*,
  (SELECT COUNT(*) FROM sales s WHERE s.customer_id=c.id) bills,
  (SELECT COALESCE(SUM(s.total-s.returned_amount),0) FROM sales s WHERE s.customer_id=c.id) spent,
  (SELECT COALESCE(SUM(MAX(s.total-s.returned_amount-s.paid_amount,0)),0) FROM sales s WHERE s.customer_id=c.id) outstanding
  FROM customers c"""


@app.route("/customers")
def customers():
    q = request.args.get("q", "").strip()
    sql = CUST_SQL + (" WHERE c.name LIKE ? OR c.phone LIKE ? OR c.bike_owned LIKE ?" if q else "") + " ORDER BY c.name"
    rows, pg = paginate(sql, [f"%{q}%"] * 3 if q else [], page_arg(), 10)
    return render_template("customers.html", rows=rows, pg=pg, a=request.args)


def contact_form(table, extra):
    """Shared validation for customer / supplier forms. Returns (values, errors)."""
    f, errs = request.form, []
    d = {k: f.get(k, "").strip() for k in ("name", "phone", "email", "address", *extra)}
    if len(d["name"]) < 2:
        errs.append("Name is required.")
    if d["phone"] and not re.fullmatch(r"[+0-9 \-()]{7,20}", d["phone"]):
        errs.append("Enter a valid phone number.")
    if d["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", d["email"]):
        errs.append("Enter a valid email address.")
    return d, errs


@app.route("/customers/save", methods=["POST"])
def customer_save():
    d, errs = contact_form("customers", ["bike_owned"])
    if errs:
        flash_all(errs)
    else:
        cid = request.form.get("id")
        if cid:
            run("UPDATE customers SET name=?,phone=?,email=?,address=?,bike_owned=? WHERE id=?",
                (d["name"], d["phone"], d["email"], d["address"], d["bike_owned"], cid))
        else:
            run("INSERT INTO customers(name,phone,email,address,bike_owned) VALUES(?,?,?,?,?)",
                (d["name"], d["phone"], d["email"], d["address"], d["bike_owned"]))
        commit()
        flash("Customer saved.", "success")
    return redirect(request.referrer or url_for("customers"))


@app.route("/customers/<int:cid>/delete", methods=["POST"])
@manager_up
def customer_delete(cid):
    run("DELETE FROM customers WHERE id=?", (cid,))  # sales keep history (customer_id set to NULL)
    commit()
    flash("Customer deleted. Their past bills are kept as walk-in sales.", "success")
    return redirect(url_for("customers"))


@app.route("/customers/<int:cid>")
def customer_detail(cid):
    c = qone(CUST_SQL + " WHERE c.id=?", (cid,))
    if not c:
        abort(404)
    sales_ = qall("""SELECT s.*, l.name location FROM sales s JOIN locations l ON l.id=s.location_id
                     WHERE s.customer_id=? ORDER BY s.id DESC""", (cid,))
    return render_template("customer_detail.html", c=c, sales=sales_)


@app.route("/customers/<int:cid>/collect", methods=["POST"])
def customer_collect(cid):
    c = qone(CUST_SQL + " WHERE c.id=?", (cid,))
    if not c:
        abort(404)
    errs = []
    amt = to_float(request.form.get("amount"), "Amount", errs, 0.01)
    if amt > c["outstanding"] + 0.005:
        errs.append(f"Amount cannot exceed the outstanding balance ({inr(c['outstanding'])}).")
    if errs:
        flash_all(errs)
    else:
        left = amt  # settle the oldest bills first
        for s in qall("SELECT * FROM sales WHERE customer_id=? ORDER BY id", (cid,)):
            due = round(s["total"] - s["returned_amount"] - s["paid_amount"], 2)
            if due > 0 and left > 0:
                pay = min(due, left)
                run("UPDATE sales SET paid_amount=? WHERE id=?", (round(s["paid_amount"] + pay, 2), s["id"]))
                left = round(left - pay, 2)
        commit()
        flash(f"Collected {inr(amt)} from {c['name']}.", "success")
    return redirect(url_for("customer_detail", cid=cid))


# =====================================================================
# 10. Suppliers
# =====================================================================
SUP_SQL = """SELECT s.*,
  (SELECT COUNT(*) FROM purchases p WHERE p.supplier_id=s.id AND p.status<>'cancelled') pos,
  (SELECT COALESCE(SUM(p.total),0) FROM purchases p WHERE p.supplier_id=s.id AND p.status<>'cancelled') purchased,
  (SELECT COALESCE(SUM(p.total-p.paid_amount),0) FROM purchases p WHERE p.supplier_id=s.id AND p.status<>'cancelled') dues
  FROM suppliers s"""


@app.route("/suppliers")
def suppliers():
    q = request.args.get("q", "").strip()
    sql = SUP_SQL + (" WHERE s.name LIKE ? OR s.contact_person LIKE ? OR s.phone LIKE ?" if q else "") + " ORDER BY s.name"
    rows, pg = paginate(sql, [f"%{q}%"] * 3 if q else [], page_arg(), 10)
    return render_template("suppliers.html", rows=rows, pg=pg, a=request.args)


@app.route("/suppliers/save", methods=["POST"])
def supplier_save():
    d, errs = contact_form("suppliers", ["contact_person", "gstin"])
    if d["gstin"] and not re.fullmatch(r"[0-9A-Za-z]{15}", d["gstin"]):
        errs.append("GSTIN must be 15 characters.")
    if errs:
        flash_all(errs)
    else:
        try:
            sid = request.form.get("id")
            if sid:
                run("UPDATE suppliers SET name=?,contact_person=?,phone=?,email=?,address=?,gstin=? WHERE id=?",
                    (d["name"], d["contact_person"], d["phone"], d["email"], d["address"], d["gstin"].upper(), sid))
            else:
                run("INSERT INTO suppliers(name,contact_person,phone,email,address,gstin) VALUES(?,?,?,?,?,?)",
                    (d["name"], d["contact_person"], d["phone"], d["email"], d["address"], d["gstin"].upper()))
            commit()
            flash("Supplier saved.", "success")
        except sqlite3.IntegrityError:
            get_db().rollback()
            flash("A supplier with this name already exists.", "danger")
    return redirect(request.referrer or url_for("suppliers"))


@app.route("/suppliers/<int:sid>/delete", methods=["POST"])
@manager_up
def supplier_delete(sid):
    try:
        run("DELETE FROM suppliers WHERE id=?", (sid,))
        commit()
        flash("Supplier deleted.", "success")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("This supplier has purchase orders and cannot be deleted.", "danger")
    return redirect(url_for("suppliers"))


@app.route("/suppliers/<int:sid>")
def supplier_detail(sid):
    s = qone(SUP_SQL + " WHERE s.id=?", (sid,))
    if not s:
        abort(404)
    pos = qall("""SELECT pu.*, l.name location FROM purchases pu JOIN locations l ON l.id=pu.location_id
                  WHERE pu.supplier_id=? ORDER BY pu.id DESC""", (sid,))
    parts_ = qall("""SELECT p.id, p.part_no, p.name, SUM(pi.qty) qty, MAX(pu.order_date) last_date,
                     (SELECT pi2.unit_cost FROM purchase_items pi2 JOIN purchases pu2 ON pu2.id=pi2.purchase_id
                      WHERE pu2.supplier_id=? AND pi2.part_id=p.id ORDER BY pu2.id DESC LIMIT 1) last_cost
                     FROM purchase_items pi JOIN purchases pu ON pu.id=pi.purchase_id JOIN parts p ON p.id=pi.part_id
                     WHERE pu.supplier_id=? AND pu.status<>'cancelled' GROUP BY p.id ORDER BY p.name""", (sid, sid))
    return render_template("supplier_detail.html", s=s, pos=pos, parts=parts_)


@app.route("/suppliers/<int:sid>/pay", methods=["POST"])
def supplier_pay(sid):
    s = qone(SUP_SQL + " WHERE s.id=?", (sid,))
    if not s:
        abort(404)
    errs = []
    amt = to_float(request.form.get("amount"), "Amount", errs, 0.01)
    if amt > s["dues"] + 0.005:
        errs.append(f"Amount cannot exceed the dues ({inr(s['dues'])}).")
    if errs:
        flash_all(errs)
    else:
        left = amt  # settle the oldest purchase orders first
        for pu in qall("SELECT * FROM purchases WHERE supplier_id=? AND status<>'cancelled' ORDER BY id", (sid,)):
            due = round(pu["total"] - pu["paid_amount"], 2)
            if due > 0 and left > 0:
                pay = min(due, left)
                paid = round(pu["paid_amount"] + pay, 2)
                run("UPDATE purchases SET paid_amount=?, payment_status=? WHERE id=?", (paid, pay_status(pu["total"], paid), pu["id"]))
                left = round(left - pay, 2)
        commit()
        flash(f"Paid {inr(amt)} to {s['name']}.", "success")
    return redirect(url_for("supplier_detail", sid=sid))


# =====================================================================
# 12. Reports  (screen + CSV / Excel export; PDF via the print view)
# =====================================================================
REPORTS = {
    "sales": "Sales report", "purchases": "Purchase report", "valuation": "Stock valuation",
    "profit": "Profit by category", "top": "Top-selling parts", "movers": "Fast / slow movers",
    "suppliers": "Supplier report",
}
NET_REV = "(si.qty-si.returned_qty)*si.unit_price*(1-CASE WHEN s.subtotal>0 THEN s.discount/s.subtotal ELSE 0 END)"


def report_range():
    today = date.today()
    out = []
    for key, default in (("from", today - timedelta(days=180)), ("to", today)):
        try:
            out.append(date.fromisoformat(request.args.get(key, "")).isoformat())
        except ValueError:
            out.append(default.isoformat())
    return out[0], out[1]


def monthly_chart(rows, date_idx, val_idx, label):
    agg = {}
    for r in rows:
        agg[str(r[date_idx])[:7]] = agg.get(str(r[date_idx])[:7], 0) + (r[val_idx] or 0)
    keys = sorted(agg)
    return dict(type="bar", label=label, labels=[datetime.strptime(k, "%Y-%m").strftime("%b %y") for k in keys],
                data=[round(agg[k], 2) for k in keys])


def build_report(kind, d_from, d_to):
    """Return dict(cols=[(label, kind)], rows=[[...]], chart=..., totals=[(label, value, kind)])."""
    rng = (d_from, d_to)
    if kind == "sales":
        rows = [list(r) for r in qall("""
            SELECT s.invoice_no, date(s.sale_date), COALESCE(c.name,'Walk-in'),
                   (SELECT COALESCE(SUM(qty-returned_qty),0) FROM sale_items WHERE sale_id=s.id),
                   s.subtotal, s.discount, s.gst_amount, s.total-s.returned_amount, s.payment_mode
            FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
            WHERE date(s.sale_date) BETWEEN ? AND ? ORDER BY s.sale_date DESC""", rng)]
        return dict(cols=[("Invoice", "text"), ("Date", "text"), ("Customer", "text"), ("Units", "int"), ("Subtotal", "money"),
                          ("Discount", "money"), ("GST", "money"), ("Net total", "money"), ("Mode", "text")], rows=rows,
                    chart=monthly_chart(rows, 1, 7, "Net sales (Rs)"),
                    totals=[("Bills", len(rows), "int"), ("Net sales", sum(r[7] for r in rows), "money"),
                            ("GST collected", sum(r[6] for r in rows), "money")])
    if kind == "purchases":
        rows = [list(r) for r in qall("""
            SELECT pu.po_no, pu.order_date, s.name, pu.status, (SELECT COUNT(*) FROM purchase_items WHERE purchase_id=pu.id),
                   pu.total, pu.paid_amount, pu.total-pu.paid_amount
            FROM purchases pu JOIN suppliers s ON s.id=pu.supplier_id
            WHERE pu.status<>'cancelled' AND pu.order_date BETWEEN ? AND ? ORDER BY pu.order_date DESC""", rng)]
        return dict(cols=[("PO", "text"), ("Date", "text"), ("Supplier", "text"), ("Status", "text"), ("Lines", "int"),
                          ("Total", "money"), ("Paid", "money"), ("Due", "money")], rows=rows,
                    chart=monthly_chart(rows, 1, 5, "Purchases (Rs)"),
                    totals=[("Orders", len(rows), "int"), ("Purchased", sum(r[5] for r in rows), "money"),
                            ("Dues", sum(r[7] for r in rows), "money")])
    if kind == "valuation":
        rows = [list(r) for r in qall(f"""
            SELECT part_no, name, category, total_qty, cost_price, total_qty*cost_price, total_qty*selling_price
            FROM ({PARTS_SQL}) ORDER BY total_qty*cost_price DESC""")]
        by_cat = {}
        for r in qall(f"SELECT category, SUM(total_qty*cost_price) v FROM ({PARTS_SQL}) GROUP BY category ORDER BY v DESC"):
            by_cat[r["category"]] = round(r["v"], 2)
        return dict(cols=[("Part No", "text"), ("Part", "text"), ("Category", "text"), ("Qty", "int"), ("Cost", "money"),
                          ("Stock value (cost)", "money"), ("Stock value (retail)", "money")], rows=rows,
                    chart=dict(type="doughnut", label="Stock value by category", labels=list(by_cat), data=list(by_cat.values())),
                    totals=[("Units in stock", sum(r[3] for r in rows), "int"), ("Value at cost", sum(r[5] for r in rows), "money"),
                            ("Value at retail", sum(r[6] for r in rows), "money")], no_dates=True)
    if kind == "profit":
        rows = []
        for r in qall(f"""SELECT c.name, SUM({NET_REV}) rev, SUM((si.qty-si.returned_qty)*si.cost_price) cogs
                          FROM sale_items si JOIN sales s ON s.id=si.sale_id JOIN parts p ON p.id=si.part_id
                          JOIN categories c ON c.id=p.category_id WHERE date(s.sale_date) BETWEEN ? AND ?
                          GROUP BY c.id ORDER BY rev DESC""", rng):
            profit = (r["rev"] or 0) - (r["cogs"] or 0)
            rows.append([r["name"], r["rev"] or 0, r["cogs"] or 0, profit, (profit / r["rev"] * 100) if r["rev"] else 0])
        return dict(cols=[("Category", "text"), ("Revenue (ex-GST)", "money"), ("Cost of goods", "money"), ("Profit", "money"),
                          ("Margin", "pct")], rows=rows,
                    chart=dict(type="bar", label="Profit (Rs)", labels=[r[0] for r in rows], data=[round(r[3], 2) for r in rows]),
                    totals=[("Revenue", sum(r[1] for r in rows), "money"), ("Profit", sum(r[3] for r in rows), "money")])
    if kind == "top":
        rows = [list(r) for r in qall(f"""
            SELECT p.part_no, p.name, SUM(si.qty-si.returned_qty) units, SUM({NET_REV}) rev
            FROM sale_items si JOIN sales s ON s.id=si.sale_id JOIN parts p ON p.id=si.part_id
            WHERE date(s.sale_date) BETWEEN ? AND ? GROUP BY p.id HAVING units>0 ORDER BY units DESC, rev DESC LIMIT 15""", rng)]
        return dict(cols=[("Part No", "text"), ("Part", "text"), ("Units sold", "int"), ("Revenue (ex-GST)", "money")], rows=rows,
                    chart=dict(type="bar", horizontal=True, label="Units sold", labels=[r[1] for r in rows], data=[r[2] for r in rows]),
                    totals=[("Units (top 15)", sum(r[2] for r in rows), "int")])
    if kind == "movers":
        sold = {r["id"]: r["u"] for r in qall("""SELECT si.part_id id, SUM(si.qty-si.returned_qty) u FROM sale_items si
                                               JOIN sales s ON s.id=si.sale_id WHERE date(s.sale_date) BETWEEN ? AND ?
                                               GROUP BY si.part_id""", rng)}
        nz = sorted(v for v in sold.values() if v > 0)
        cut = nz[int(len(nz) * 0.67)] if nz else 1
        days = max((date.fromisoformat(d_to) - date.fromisoformat(d_from)).days + 1, 1)
        rows, counts = [], {"Fast": 0, "Slow": 0, "Non-moving": 0}
        for p in qall(PARTS_SQL + " ORDER BY p.name"):
            u = sold.get(p["id"], 0) or 0
            cls = "Non-moving" if u <= 0 else ("Fast" if u >= cut else "Slow")
            counts[cls] += 1
            cover = round(p["total_qty"] / (u / days), 0) if u > 0 else None
            rows.append([p["part_no"], p["name"], u, p["total_qty"], cover if cover is not None else "-", cls])
        order = {"Fast": 0, "Slow": 1, "Non-moving": 2}
        rows.sort(key=lambda r: (order[r[5]], -r[2]))
        return dict(cols=[("Part No", "text"), ("Part", "text"), ("Units sold", "int"), ("In stock", "int"),
                          ("Days of cover", "text"), ("Class", "text")], rows=rows,
                    chart=dict(type="doughnut", label="Movers", labels=list(counts), data=list(counts.values())),
                    totals=[(k + " movers", v, "int") for k, v in counts.items()])
    # suppliers
    rows = [list(r) for r in qall("""
        SELECT s.name, COUNT(pu.id), COALESCE(SUM(pu.total),0), COALESCE(SUM(pu.paid_amount),0),
               COALESCE(SUM(pu.total-pu.paid_amount),0), MAX(pu.order_date)
        FROM suppliers s LEFT JOIN purchases pu ON pu.supplier_id=s.id AND pu.status<>'cancelled'
             AND pu.order_date BETWEEN ? AND ? GROUP BY s.id ORDER BY 3 DESC""", rng)]
    return dict(cols=[("Supplier", "text"), ("Orders", "int"), ("Purchased", "money"), ("Paid", "money"), ("Dues", "money"),
                      ("Last order", "text")], rows=rows,
                chart=dict(type="bar", label="Purchased (Rs)", labels=[r[0] for r in rows], data=[round(r[2], 2) for r in rows]),
                totals=[("Purchased", sum(r[2] for r in rows), "money"), ("Dues", sum(r[4] for r in rows), "money")])


@app.route("/reports")
def reports():
    kind = request.args.get("type", "sales")
    if kind not in REPORTS:
        kind = "sales"
    d_from, d_to = report_range()
    return render_template("reports.html", kind=kind, titles=REPORTS, d_from=d_from, d_to=d_to,
                           rep=build_report(kind, d_from, d_to), today=date.today().strftime("%d %b %Y"))


@app.route("/reports/export")
def reports_export():
    kind = request.args.get("type", "sales")
    if kind not in REPORTS:
        abort(404)
    d_from, d_to = report_range()
    rep = build_report(kind, d_from, d_to)
    header = [c[0] for c in rep["cols"]]
    fname = f"{kind}_report_{d_from}_to_{d_to}"
    if request.args.get("fmt") == "xlsx":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            flash("Excel export needs openpyxl (pip install openpyxl).", "danger")
            return redirect(url_for("reports", type=kind))
        wb = Workbook()
        ws = wb.active
        ws.title = re.sub(r"[\\/*?:\[\]]", "-", REPORTS[kind])[:30]
        ws.append([REPORTS[kind], f"{d_from} to {d_to}" if not rep.get("no_dates") else "As on today"])
        ws.append(header)
        for c in ws[2]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0B3D91")
        for r in rep["rows"]:
            ws.append(r)
        for i, col in enumerate(ws.columns, 1):
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 3, 45)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=fname + ".xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(rep["rows"])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}.csv"})


# =====================================================================
# 13. Settings
# =====================================================================
LIST_TABLES = {"categories": "categories", "brands": "brands"}  # whitelist for dynamic table names


@app.route("/settings")
def settings():
    return render_template(
        "settings.html", st={k: S(k) for k in DEFAULT_SETTINGS},
        categories=qall("SELECT c.*, (SELECT COUNT(*) FROM parts p WHERE p.category_id=c.id) n FROM categories c ORDER BY name"),
        brands=qall("SELECT b.*, (SELECT COUNT(*) FROM parts p WHERE p.brand_id=b.id) n FROM brands b ORDER BY name"),
        users=qall("SELECT * FROM users ORDER BY id"))


@app.route("/settings/shop", methods=["POST"])
@admin_only
def settings_shop():
    f = request.form
    if not f.get("shop_name", "").strip():
        flash("Shop name is required.", "danger")
        return redirect(url_for("settings"))
    gst = f.get("gst_number", "").strip().upper()
    if gst and not re.fullmatch(r"[0-9A-Z]{15}", gst):
        flash("GST number must be 15 letters/digits.", "danger")
        return redirect(url_for("settings"))
    for k in ("shop_name", "shop_address", "shop_phone", "shop_email", "invoice_prefix", "po_prefix", "invoice_footer"):
        set_setting(k, f.get(k, "").strip())
    set_setting("gst_number", gst)
    commit()
    flash("Shop profile saved.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/tax", methods=["POST"])
@admin_only
def settings_tax():
    errs = []
    rates = []
    for part in request.form.get("gst_rates", "").split(","):
        if part.strip():
            rates.append(f"{to_float(part, 'GST rate', errs, 0, 100):g}")
    thr = to_int(request.form.get("low_stock_default"), "Default low-stock level", errs, 0)
    if errs or not rates:
        flash_all(errs or ["Enter at least one GST rate."])
    else:
        set_setting("gst_rates", ",".join(rates))
        set_setting("low_stock_default", str(thr))
        if request.form.get("apply_all"):
            run("UPDATE parts SET reorder_level=?", (thr,))
        commit()
        flash("Tax rates and thresholds saved." + (" Reorder level applied to all parts." if request.form.get("apply_all") else ""), "success")
    return redirect(url_for("settings"))


@app.route("/settings/list/<kind>/save", methods=["POST"])
@manager_up
def list_save(kind):
    table = LIST_TABLES.get(kind) or abort(404)
    name, lid = request.form.get("name", "").strip(), request.form.get("id")
    if not name:
        flash("Name is required.", "danger")
    else:
        try:
            if lid:
                run(f"UPDATE {table} SET name=? WHERE id=?", (name, lid))
            else:
                run(f"INSERT INTO {table}(name) VALUES(?)", (name,))
            commit()
            flash("Saved.", "success")
        except sqlite3.IntegrityError:
            get_db().rollback()
            flash("That name already exists.", "danger")
    return redirect(url_for("settings") + "#" + kind)


@app.route("/settings/list/<kind>/<int:lid>/delete", methods=["POST"])
@manager_up
def list_delete(kind, lid):
    table = LIST_TABLES.get(kind) or abort(404)
    try:
        run(f"DELETE FROM {table} WHERE id=?", (lid,))
        commit()
        flash("Deleted.", "success")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("It is still used by parts or bike models and cannot be deleted.", "danger")
    return redirect(url_for("settings") + "#" + kind)


@app.route("/settings/users/add", methods=["POST"])
@admin_only
def user_add():
    f, errs = request.form, []
    username, role = f.get("username", "").strip(), f.get("role", "staff")
    if not re.fullmatch(r"[A-Za-z0-9_.]{3,30}", username):
        errs.append("User ID must be 3-30 letters, digits, dot or underscore.")
    elif qone("SELECT 1 FROM users WHERE username=?", (username,)):
        errs.append("User ID already exists.")
    if len(f.get("full_name", "").strip()) < 2:
        errs.append("Full name is required.")
    if len(f.get("password", "")) < 6:
        errs.append("Password must be at least 6 characters.")
    if role not in ("admin", "manager", "staff"):
        errs.append("Invalid role.")
    if errs:
        flash_all(errs)
    else:
        run("INSERT INTO users(username,password_hash,full_name,email,role) VALUES(?,?,?,?,?)",
            (username, generate_password_hash(f["password"]), f["full_name"].strip(), f.get("email", "").strip(), role))
        commit()
        flash("User added.", "success")
    return redirect(url_for("settings") + "#users")


@app.route("/settings/users/<int:uid>/update", methods=["POST"])
@admin_only
def user_update(uid):
    f = request.form
    if uid == g.user["id"] and (f.get("role") != "admin" or not f.get("active")):
        flash("You cannot demote or disable your own account.", "danger")
    elif f.get("role") in ("admin", "manager", "staff"):
        run("UPDATE users SET role=?, active=? WHERE id=?", (f["role"], 1 if f.get("active") else 0, uid))
        if f.get("new_password"):
            if len(f["new_password"]) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return redirect(url_for("settings") + "#users")
            run("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(f["new_password"]), uid))
        commit()
        flash("User updated.", "success")
    return redirect(url_for("settings") + "#users")


@app.route("/settings/users/<int:uid>/delete", methods=["POST"])
@admin_only
def user_delete(uid):
    if uid == g.user["id"]:
        flash("You cannot delete your own account.", "danger")
    else:
        run("DELETE FROM users WHERE id=?", (uid,))
        commit()
        flash("User deleted.", "success")
    return redirect(url_for("settings") + "#users")


@app.route("/settings/backup")
@admin_only
def backup_db():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(tmp.name)
    src.backup(dst)  # consistent online copy
    dst.close()
    src.close()
    resp = send_file(tmp.name, as_attachment=True, download_name=f"mspms_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    resp.call_on_close(lambda: os.path.exists(tmp.name) and os.remove(tmp.name))
    return resp


@app.route("/settings/restore", methods=["POST"])
@admin_only
def restore_db():
    fs = request.files.get("backup")
    if not fs or not fs.filename.lower().endswith(".db"):
        flash("Choose a .db backup file made by MSPMS.", "danger")
        return redirect(url_for("settings") + "#backup")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    fs.save(tmp)
    try:
        con = sqlite3.connect(tmp)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()
        need = {"users", "parts", "stock", "stock_movements", "sales", "purchases", "settings"}
        if not need <= tables or not ok:
            raise ValueError
    except (sqlite3.DatabaseError, ValueError):
        os.remove(tmp)
        flash("That file is not a valid MSPMS database backup.", "danger")
        return redirect(url_for("settings") + "#backup")
    db = g.pop("db", None)
    if db is not None:
        db.close()
    shutil.copy(DB_PATH, DB_PATH + ".before_restore")  # safety copy of the current database
    os.replace(tmp, DB_PATH)
    session.clear()
    flash("Database restored. Please log in again.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    host = os.environ.get("MSPMS_HOST", "127.0.0.1")
    port = int(os.environ.get("MSPMS_PORT", "5000"))
    print(f"\n  MSPMS running at http://{host}:{port}  (login: admin / admin123)\n")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
