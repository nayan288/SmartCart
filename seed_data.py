"""Creates fake customers and orders so the dashboard charts and recommender have data."""
import random
from datetime import datetime, timedelta
import numpy as np
from werkzeug.security import generate_password_hash
from db import get_db

random.seed(42)
np.random.seed(42)

conn = get_db()
cur = conn.cursor(dictionary=True)

cur.execute("SELECT id, price FROM products")
products = cur.fetchall()

pw = generate_password_hash("password123")
for i in range(1, 21):
    cur.execute(
        "INSERT IGNORE INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
        (f"Customer {i}", f"customer{i}@example.com", pw),
    )
conn.commit()

cur.execute("SELECT id FROM users WHERE role='customer'")
user_ids = [r["id"] for r in cur.fetchall()]

now = datetime.now()
for _ in range(150):
    uid = random.choice(user_ids)
    when = now - timedelta(days=int(np.random.randint(0, 180)), hours=int(np.random.randint(0, 24)))
    chosen = random.sample(products, k=random.randint(1, 3))
    total, rows = 0.0, []
    for p in chosen:
        qty = random.randint(1, 3)
        total += float(p["price"]) * qty
        rows.append((p["id"], qty, p["price"]))
    cur.execute(
        "INSERT INTO orders (user_id, total, address, payment_method, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (uid, round(total, 2), "Sample address", random.choice(["COD", "Card"]),
         random.choice(["Delivered", "Delivered", "Shipped", "Placed"]), when),
    )
    order_id = cur.lastrowid
    for pid, qty, price in rows:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s, %s, %s, %s)",
            (order_id, pid, qty, price),
        )

conn.commit()
cur.close()
conn.close()
print("Sample customers (password: password123) and 150 orders added.")
