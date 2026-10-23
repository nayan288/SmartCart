import os
import mysql.connector


def get_db():
    """Return a new MySQL connection. Change the defaults or set environment variables."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "nayanuser"),
        password=os.environ.get("DB_PASSWORD", "Nayan@1234567890"),
        database=os.environ.get("DB_NAME", "smartcart"),
    )
