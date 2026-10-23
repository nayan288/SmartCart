import base64
import io
import os
from functools import wraps

import matplotlib
matplotlib.use("Agg")  # no GUI window, render to memory
import matplotlib.pyplot as plt
import mysql.connector
import numpy as np
import pandas as pd
from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import get_db
from recommender import recommend_for_product

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

COUPONS = {"SAVE10": 10, "WELCOME5": 5}  # code -> percent off


# ---------------------------------------------------------------- helpers
def query(sql, params=(), one=False, commit=False):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        if commit:
            conn.commit()
            return cur.lastrowid
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close()
        conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access only.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def save_image(file):
    if file and file.filename:
        name = secure_filename(file.filename)
        file.save(os.path.join(UPLOAD_FOLDER, name))
        return name
    return None


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


@app.context_processor
def inject_globals():
    count = 0
    if session.get("user_id"):
        r = query("SELECT COALESCE(SUM(quantity),0) AS c FROM cart WHERE user_id=%s",
                  (session["user_id"],), one=True)
        count = int(r["c"])
    return {"cart_count": count}


# ------------------------------------------------------------------- auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if not name or not email or len(password) < 6:
            flash("Fill all fields. Password needs at least 6 characters.", "error")
        elif query("SELECT id FROM users WHERE email=%s", (email,), one=True):
            flash("That email is already registered.", "error")
        else:
            query("INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s)",
                  (name, email, generate_password_hash(password)), commit=True)
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = query("SELECT * FROM users WHERE email=%s", (email,), one=True)
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session.update(user_id=user["id"], name=user["name"], role=user["role"])
            flash(f"Welcome back, {user['name']}.", "success")
            return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "index"))
        flash("Wrong email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ------------------------------------------------------------------- shop
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "")
    sort = request.args.get("sort", "new")
    min_p = request.args.get("min_price", "")
    max_p = request.args.get("max_price", "")

    sql = ("SELECT p.*, c.name AS category, COALESCE(AVG(r.rating),0) AS avg_rating "
           "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
           "LEFT JOIN reviews r ON r.product_id = p.id WHERE 1=1")
    params = []
    if q:
        sql += " AND (p.name LIKE %s OR p.description LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    if cat:
        sql += " AND p.category_id = %s"
        params.append(cat)
    if min_p:
        sql += " AND p.price >= %s"
        params.append(min_p)
    if max_p:
        sql += " AND p.price <= %s"
        params.append(max_p)
    order = {"new": "p.created_at DESC", "price_low": "p.price ASC",
             "price_high": "p.price DESC", "rating": "avg_rating DESC"}.get(sort, "p.created_at DESC")
    sql += f" GROUP BY p.id, c.name ORDER BY {order}"

    products = query(sql, tuple(params))
    categories = query("SELECT * FROM categories ORDER BY name")
    return render_template("index.html", products=products, categories=categories,
                           q=q, cat=cat, sort=sort, min_p=min_p, max_p=max_p)


@app.route("/product/<int:pid>", methods=["GET", "POST"])
def product(pid):
    p = query("SELECT p.*, c.name AS category FROM products p "
              "LEFT JOIN categories c ON c.id = p.category_id WHERE p.id=%s", (pid,), one=True)
    if not p:
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        if "user_id" not in session:
            flash("Log in to write a review.", "error")
            return redirect(url_for("login"))
        rating = int(request.form["rating"])
        if 1 <= rating <= 5:
            query("INSERT INTO reviews (user_id, product_id, rating, comment) VALUES (%s,%s,%s,%s)",
                  (session["user_id"], pid, rating, request.form.get("comment", "").strip()),
                  commit=True)
            flash("Thanks for your review.", "success")
        return redirect(url_for("product", pid=pid))

    reviews = query("SELECT r.*, u.name FROM reviews r JOIN users u ON u.id = r.user_id "
                    "WHERE r.product_id=%s ORDER BY r.created_at DESC", (pid,))
    avg = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else 0

    # ML recommendations, with a same-category fallback
    ids = recommend_for_product(pid)
    if ids:
        marks = ",".join(["%s"] * len(ids))
        recs = query(f"SELECT * FROM products WHERE id IN ({marks})", tuple(ids))
    else:
        recs = query("SELECT * FROM products WHERE category_id=%s AND id<>%s LIMIT 4",
                     (p["category_id"], pid))
    return render_template("product.html", p=p, reviews=reviews, avg=avg, recs=recs)


# ------------------------------------------------------------------- cart
@app.route("/cart")
@login_required
def cart():
    items = query("SELECT c.id, c.quantity, p.id AS product_id, p.name, p.price, p.stock, p.image "
                  "FROM cart c JOIN products p ON p.id = c.product_id WHERE c.user_id=%s",
                  (session["user_id"],))
    total = sum(float(i["price"]) * i["quantity"] for i in items)
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/add/<int:pid>", methods=["POST"])
@login_required
def add_to_cart(pid):
    qty = max(1, int(request.form.get("quantity", 1)))
    p = query("SELECT stock FROM products WHERE id=%s", (pid,), one=True)
    if not p or p["stock"] < 1:
        flash("This product is out of stock.", "error")
        return redirect(request.referrer or url_for("index"))
    query("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s,%s,%s) "
          "ON DUPLICATE KEY UPDATE quantity = LEAST(quantity + VALUES(quantity), %s)",
          (session["user_id"], pid, qty, p["stock"]), commit=True)
    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("cart"))


@app.route("/cart/update/<int:cid>", methods=["POST"])
@login_required
def update_cart(cid):
    qty = int(request.form.get("quantity", 1))
    if qty < 1:
        query("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session["user_id"]), commit=True)
    else:
        query("UPDATE cart c JOIN products p ON p.id = c.product_id "
              "SET c.quantity = LEAST(%s, p.stock) WHERE c.id=%s AND c.user_id=%s",
              (qty, cid, session["user_id"]), commit=True)
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:cid>", methods=["POST"])
@login_required
def remove_from_cart(cid):
    query("DELETE FROM cart WHERE id=%s AND user_id=%s", (cid, session["user_id"]), commit=True)
    return redirect(url_for("cart"))


# --------------------------------------------------------------- checkout
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    items = query("SELECT c.quantity, p.id AS product_id, p.name, p.price, p.stock "
                  "FROM cart c JOIN products p ON p.id = c.product_id WHERE c.user_id=%s",
                  (session["user_id"],))
    if not items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("index"))

    subtotal = sum(float(i["price"]) * i["quantity"] for i in items)

    if request.method == "GET":
        return render_template("checkout.html", items=items, subtotal=subtotal)

    address = request.form["address"].strip()
    payment = request.form["payment"]
    code = request.form.get("coupon", "").strip().upper()
    discount_pct = COUPONS.get(code, 0)
    if code and not discount_pct:
        flash("That coupon code is not valid.", "error")
        return render_template("checkout.html", items=items, subtotal=subtotal)
    if not address:
        flash("Please enter a delivery address.", "error")
        return render_template("checkout.html", items=items, subtotal=subtotal)

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        # lock rows so two customers cannot buy the last item at the same time
        cur.execute("SELECT c.quantity, p.id AS product_id, p.name, p.price, p.stock "
                    "FROM cart c JOIN products p ON p.id = c.product_id "
                    "WHERE c.user_id=%s FOR UPDATE", (session["user_id"],))
        rows = cur.fetchall()
        total = 0.0
        for r in rows:
            if r["quantity"] > r["stock"]:
                raise ValueError(f"Not enough stock for {r['name']} (only {r['stock']} left).")
            total += float(r["price"]) * r["quantity"]
        total = round(total * (100 - discount_pct) / 100, 2)

        cur.execute("INSERT INTO orders (user_id, total, address, payment_method) VALUES (%s,%s,%s,%s)",
                    (session["user_id"], total, address, payment))
        order_id = cur.lastrowid
        for r in rows:
            cur.execute("INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s,%s,%s,%s)",
                        (order_id, r["product_id"], r["quantity"], r["price"]))
            cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s",
                        (r["quantity"], r["product_id"]))
        cur.execute("DELETE FROM cart WHERE user_id=%s", (session["user_id"],))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
        return redirect(url_for("cart"))
    except Exception:
        conn.rollback()
        flash("Something went wrong while placing your order. Please try again.", "error")
        return redirect(url_for("cart"))
    finally:
        cur.close()
        conn.close()

    flash(f"Order #{order_id} placed successfully.", "success")
    return redirect(url_for("orders"))


@app.route("/orders")
@login_required
def orders():
    rows = query("SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC", (session["user_id"],))
    for o in rows:
        o["items"] = query("SELECT oi.*, p.name FROM order_items oi JOIN products p ON p.id = oi.product_id "
                           "WHERE oi.order_id=%s", (o["id"],))
    return render_template("orders.html", orders=rows)


@app.route("/orders/<int:oid>/cancel", methods=["POST"])
@login_required
def cancel_order(oid):
    o = query("SELECT * FROM orders WHERE id=%s AND user_id=%s", (oid, session["user_id"]), one=True)
    if o and o["status"] == "Placed":
        query("UPDATE orders SET status='Cancelled' WHERE id=%s", (oid,), commit=True)
        query("UPDATE products p JOIN order_items oi ON oi.product_id = p.id "
              "SET p.stock = p.stock + oi.quantity WHERE oi.order_id=%s", (oid,), commit=True)
        flash("Order cancelled and stock restored.", "success")
    else:
        flash("Only orders in 'Placed' status can be cancelled.", "error")
    return redirect(url_for("orders"))


# ------------------------------------------------------------------ admin
@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "revenue": float(query("SELECT COALESCE(SUM(total),0) AS v FROM orders WHERE status<>'Cancelled'", one=True)["v"]),
        "orders": query("SELECT COUNT(*) AS v FROM orders", one=True)["v"],
        "customers": query("SELECT COUNT(*) AS v FROM users WHERE role='customer'", one=True)["v"],
        "products": query("SELECT COUNT(*) AS v FROM products", one=True)["v"],
    }
    low_stock = query("SELECT id, name, stock FROM products WHERE stock < 5 ORDER BY stock")
    charts, forecast = {}, None

    # 1) Monthly revenue + simple linear-regression forecast (numpy)
    monthly = pd.DataFrame(query(
        "SELECT DATE_FORMAT(created_at,'%Y-%m') AS month, SUM(total) AS revenue "
        "FROM orders WHERE status<>'Cancelled' GROUP BY DATE_FORMAT(created_at,'%Y-%m') ORDER BY month"))
    if not monthly.empty:
        monthly["revenue"] = monthly["revenue"].astype(float)
        fig, ax = plt.subplots(figsize=(7, 3.6))
        x = np.arange(len(monthly))
        ax.plot(monthly["month"], monthly["revenue"], marker="o", color="#0f5c5c", label="Revenue")
        if len(monthly) >= 3:
            slope, intercept = np.polyfit(x, monthly["revenue"], 1)
            forecast = max(0, float(slope * len(monthly) + intercept))
            ax.plot([monthly["month"].iloc[-1], "next"], [monthly["revenue"].iloc[-1], forecast],
                    "--", color="#c8691c", marker="o", label="Forecast")
        ax.set_title("Monthly revenue")
        ax.legend()
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        charts["monthly"] = fig_to_base64(fig)

    # 2) Top selling products
    top = pd.DataFrame(query(
        "SELECT p.name, SUM(oi.quantity) AS sold FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status<>'Cancelled' GROUP BY p.id, p.name ORDER BY sold DESC LIMIT 10"))
    if not top.empty:
        top["sold"] = top["sold"].astype(int)
        fig, ax = plt.subplots(figsize=(7, 3.6))
        ax.barh(top["name"][::-1], top["sold"][::-1], color="#0f5c5c")
        ax.set_title("Top selling products (units)")
        charts["top"] = fig_to_base64(fig)

    # 3) Revenue by category
    cats = pd.DataFrame(query(
        "SELECT COALESCE(c.name,'Uncategorised') AS category, SUM(oi.quantity*oi.price) AS revenue "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "LEFT JOIN categories c ON c.id = p.category_id JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status<>'Cancelled' GROUP BY COALESCE(c.name,'Uncategorised')"))
    if not cats.empty:
        cats["revenue"] = cats["revenue"].astype(float)
        fig, ax = plt.subplots(figsize=(5, 3.6))
        ax.pie(cats["revenue"], labels=cats["category"], autopct="%1.0f%%",
               colors=["#0f5c5c", "#c8691c", "#7a9e7e", "#d9b86c"])
        ax.set_title("Revenue by category")
        charts["category"] = fig_to_base64(fig)

    # 4) Orders by status
    status = pd.DataFrame(query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status"))
    if not status.empty:
        fig, ax = plt.subplots(figsize=(5, 3.6))
        ax.bar(status["status"], status["n"].astype(int), color="#c8691c")
        ax.set_title("Orders by status")
        charts["status"] = fig_to_base64(fig)

    return render_template("admin_dashboard.html", stats=stats, charts=charts,
                           forecast=forecast, low_stock=low_stock)


@app.route("/admin/products")
@admin_required
def admin_products():
    rows = query("SELECT p.*, c.name AS category FROM products p "
                 "LEFT JOIN categories c ON c.id = p.category_id ORDER BY p.id DESC")
    return render_template("admin_products.html", products=rows)


@app.route("/admin/products/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    if request.method == "POST":
        image = save_image(request.files.get("image"))
        query("INSERT INTO products (name, description, price, stock, image, category_id) "
              "VALUES (%s,%s,%s,%s,%s,%s)",
              (request.form["name"], request.form["description"], request.form["price"],
               request.form["stock"], image, request.form["category_id"] or None), commit=True)
        flash("Product added.", "success")
        return redirect(url_for("admin_products"))
    return render_template("product_form.html", p=None,
                           categories=query("SELECT * FROM categories ORDER BY name"))


@app.route("/admin/products/edit/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(pid):
    p = query("SELECT * FROM products WHERE id=%s", (pid,), one=True)
    if not p:
        return redirect(url_for("admin_products"))
    if request.method == "POST":
        image = save_image(request.files.get("image")) or p["image"]
        query("UPDATE products SET name=%s, description=%s, price=%s, stock=%s, image=%s, category_id=%s "
              "WHERE id=%s",
              (request.form["name"], request.form["description"], request.form["price"],
               request.form["stock"], image, request.form["category_id"] or None, pid), commit=True)
        flash("Product updated.", "success")
        return redirect(url_for("admin_products"))
    return render_template("product_form.html", p=p,
                           categories=query("SELECT * FROM categories ORDER BY name"))


@app.route("/admin/products/delete/<int:pid>", methods=["POST"])
@admin_required
def admin_delete_product(pid):
    try:
        query("DELETE FROM products WHERE id=%s", (pid,), commit=True)
        flash("Product deleted.", "success")
    except mysql.connector.errors.IntegrityError:
        flash("This product is part of existing orders, so it can't be deleted. Set its stock to 0 instead.", "error")
    return redirect(url_for("admin_products"))


@app.route("/admin/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    if request.method == "POST":
        name = request.form["name"].strip()
        if name:
            try:
                query("INSERT INTO categories (name) VALUES (%s)", (name,), commit=True)
                flash("Category added.", "success")
            except mysql.connector.errors.IntegrityError:
                flash("That category already exists.", "error")
        return redirect(url_for("admin_categories"))
    return render_template("admin_categories.html",
                           categories=query("SELECT * FROM categories ORDER BY name"))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    rows = query("SELECT o.*, u.name AS customer FROM orders o JOIN users u ON u.id = o.user_id "
                 "ORDER BY o.created_at DESC")
    return render_template("admin_orders.html", orders=rows)


@app.route("/admin/orders/<int:oid>/status", methods=["POST"])
@admin_required
def admin_update_order(oid):
    status = request.form["status"]
    if status in ("Placed", "Packed", "Shipped", "Delivered", "Cancelled"):
        query("UPDATE orders SET status=%s WHERE id=%s", (status, oid), commit=True)
        flash(f"Order #{oid} marked as {status}.", "success")
    return redirect(url_for("admin_orders"))


if __name__ == "__main__":
    app.run(debug=True)
