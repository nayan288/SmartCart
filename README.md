# SmartCart - Flask + MySQL e-commerce project

Features: register/login, product search/filter/sort, cart, checkout with stock locking and coupons,
order history and cancellation, reviews, admin panel (products, categories, orders),
analytics dashboard (pandas + matplotlib), sales forecast (numpy) and product recommendations (cosine similarity).

## Setup steps

1. Install Python 3.10+ and MySQL Server.
2. Create a virtual environment and install packages:
       python3 -m venv venv
       source venv/bin/activate
       pip install -r requirements.txt
3. Create the database and tables (enter your MySQL password when asked):
       mysql -u root -p < schema.sql
4. Open `db.py` and put your MySQL password in, or set the environment variable:
       export DB_PASSWORD="your_password"
5. Create your admin account:
       python create_admin.py
6. (Optional) Add fake customers and 150 orders so the charts and recommendations have data:
       python seed_data.py
7. Run the app:
       python app.py
   Open http://127.0.0.1:5000

## Try it
- Log in as admin, open Admin, and add products with images.
- Register a customer, add products to the cart, check out with coupon SAVE10.
- As admin, change the order status and watch the customer's order page update.
- Open any product to see "Customers also bought" (works after seed_data.py).

## Folder layout
    app.py             routes (auth, shop, cart, checkout, admin, dashboard)
    db.py              MySQL connection
    schema.sql         tables and sample products
    ml/recommender.py  item-based collaborative filtering
    seed_data.py       fake data generator
    create_admin.py    makes an admin user
    templates/         HTML (Jinja2)
    static/css         styling
    static/images      uploaded product images

## Before going live
- Set a strong SECRET_KEY environment variable and turn off debug mode.
- The payment step is a demo only; use a real gateway (Razorpay, Stripe) for real payments.
# SmartCart
