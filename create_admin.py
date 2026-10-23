from getpass import getpass
from werkzeug.security import generate_password_hash
from db import get_db

name = input("Admin name: ").strip()
email = input("Admin email: ").strip().lower()
password = getpass("Admin password: ")

conn = get_db()
cur = conn.cursor()
cur.execute(
    "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')",
    (name, email, generate_password_hash(password)),
)
conn.commit()
cur.close()
conn.close()
print("Admin created.")
