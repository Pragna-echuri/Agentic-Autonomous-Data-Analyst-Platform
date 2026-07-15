"""
Database Initialization Script
==============================
Seeds the SQLite database with rich sample data for the Data Analyst Agent.
Creates: customers, products, orders, and order_items tables.

Usage:
    python data/init_db.py
"""

import sqlite3
import os
import random
from pathlib import Path

DB_PATH = Path(__file__).parent / "example.db"


def init_database():
    """Create and seed the sample database."""
    # Remove existing DB for clean slate
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # ── Create Tables ────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            age INTEGER,
            country TEXT,
            signup_date TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    # ── Seed Customers ───────────────────────────────────────────────

    customers = [
        ("Alice Johnson", "alice@example.com", 30, "USA", "2024-01-15"),
        ("Bob Smith", "bob@example.com", 24, "UK", "2024-02-20"),
        ("Charlie Brown", "charlie@example.com", 29, "Canada", "2024-01-05"),
        ("Diana Prince", "diana@example.com", 33, "USA", "2024-03-10"),
        ("Eve Wilson", "eve@example.com", 27, "Germany", "2024-02-14"),
        ("Frank Miller", "frank@example.com", 35, "France", "2024-04-01"),
        ("Grace Lee", "grace@example.com", 22, "Japan", "2024-03-22"),
        ("Henry Davis", "henry@example.com", 41, "Australia", "2024-01-30"),
        ("Ivy Chen", "ivy@example.com", 26, "USA", "2024-05-05"),
        ("Jack Taylor", "jack@example.com", 31, "UK", "2024-04-18"),
        ("Karen White", "karen@example.com", 28, "Canada", "2024-06-01"),
        ("Leo Martinez", "leo@example.com", 37, "Spain", "2024-02-28"),
        ("Mia Anderson", "mia@example.com", 25, "USA", "2024-07-12"),
        ("Nathan Brown", "nathan@example.com", 33, "India", "2024-03-15"),
        ("Olivia Garcia", "olivia@example.com", 29, "Brazil", "2024-08-20"),
    ]
    cursor.executemany(
        "INSERT INTO customers (name, email, age, country, signup_date) VALUES (?, ?, ?, ?, ?)",
        customers,
    )

    # ── Seed Products ────────────────────────────────────────────────

    products = [
        ("Laptop Pro 15", "Electronics", 1299.99, 45),
        ("Wireless Mouse", "Electronics", 29.99, 200),
        ("USB-C Hub", "Electronics", 49.99, 150),
        ("Mechanical Keyboard", "Electronics", 89.99, 120),
        ("Monitor 27-inch", "Electronics", 349.99, 60),
        ("Python Cookbook", "Books", 39.99, 300),
        ("Data Science Handbook", "Books", 44.99, 250),
        ("AI Engineering", "Books", 54.99, 180),
        ("Standing Desk", "Furniture", 499.99, 30),
        ("Ergonomic Chair", "Furniture", 399.99, 40),
        ("Desk Lamp LED", "Furniture", 34.99, 100),
        ("Noise-Cancelling Headphones", "Electronics", 199.99, 80),
        ("Webcam HD", "Electronics", 79.99, 110),
        ("External SSD 1TB", "Electronics", 109.99, 90),
        ("Notebook Set", "Office Supplies", 12.99, 500),
    ]
    cursor.executemany(
        "INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)",
        products,
    )

    # ── Seed Orders ──────────────────────────────────────────────────

    statuses = ["completed", "pending", "shipped", "cancelled"]
    months = [f"2024-{m:02d}" for m in range(1, 13)]

    orders_data = []
    order_items_data = []
    order_id = 1

    random.seed(42)  # Reproducible

    for _ in range(50):
        cust_id = random.randint(1, 15)
        month = random.choice(months)
        day = random.randint(1, 28)
        date = f"{month}-{day:02d}"
        status = random.choice(statuses)

        # 1-4 items per order
        num_items = random.randint(1, 4)
        total = 0.0

        for _ in range(num_items):
            prod_id = random.randint(1, 15)
            qty = random.randint(1, 3)
            price = products[prod_id - 1][2]
            total += qty * price
            order_items_data.append((order_id, prod_id, qty, price))

        orders_data.append((cust_id, date, round(total, 2), status))
        order_id += 1

    cursor.executemany(
        "INSERT INTO orders (customer_id, order_date, total_amount, status) VALUES (?, ?, ?, ?)",
        orders_data,
    )
    cursor.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
        order_items_data,
    )

    conn.commit()
    conn.close()

    print(f"✅ Database initialized at: {DB_PATH}")
    print(f"   → {len(customers)} customers")
    print(f"   → {len(products)} products")
    print(f"   → {len(orders_data)} orders")
    print(f"   → {len(order_items_data)} order items")


if __name__ == "__main__":
    init_database()
