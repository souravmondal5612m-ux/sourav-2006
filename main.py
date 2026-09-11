import asyncio
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import sqlite3
import uvicorn
from typing import Optional
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import threading
import time

# ---------- Database Setup ----------
def init_db():
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT,
        product_items TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        order_date TEXT NOT NULL,
        delivery_date TEXT NOT NULL,
        special_instructions TEXT,
        status TEXT DEFAULT 'Pending'
    )""")
    conn.commit()
    conn.close()

init_db()

# ---------- Pydantic Models ----------
class OrderCreate(BaseModel):
    order_id: str
    customer_name: str
    customer_phone: Optional[str] = ""
    product_items: str
    quantity: int = 1
    delivery_date: str
    special_instructions: Optional[str] = ""

class OrderUpdate(BaseModel):
    status: str

# ---------- FastAPI App ----------
app = FastAPI(title="Order & Delivery Reminder AI Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect("orders.db")
    conn.row_factory = sqlite3.Row
    return conn

def parse_date(date_str):
    if date_str.lower() == "today":
        return datetime.today().date().isoformat()
    elif date_str.lower() == "tomorrow":
        return (datetime.today().date() + timedelta(days=1)).isoformat()
    elif date_str.lower() == "day_after_tomorrow":
        return (datetime.today().date() + timedelta(days=2)).isoformat()
    else:
        return date_str

# ---------- API Endpoints ----------
@app.post("/add_order")
async def add_order(order: OrderCreate):
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order.order_id,)).fetchone()
    if existing:
        return {"message": f"Order {order.order_id} already exists!"}
    conn.execute("""INSERT INTO orders 
        (order_id, customer_name, customer_phone, product_items, quantity, order_date, delivery_date, special_instructions, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (order.order_id, order.customer_name, order.customer_phone, order.product_items, 
        order.quantity, datetime.today().date().isoformat(), order.delivery_date, 
        order.special_instructions, "Pending"))
    conn.commit()
    conn.close()
    return {"message": f"Order {order.order_id} added successfully!"}

@app.put("/update_status/{order_id}")
async def update_status(order_id: str, update: OrderUpdate):
    valid_statuses = ["Pending", "In Production", "Ready", "Delivered", "Delayed", "Cancelled"]
    if update.status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (update.status, order_id))
    conn.commit()
    conn.close()
    return {"message": f"Order {order_id} updated to {update.status}"}

@app.get("/orders")
async def get_orders(
    q: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    conn = get_db()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if q:
        q_lower = q.lower()
        if "today" in q_lower:
            query += " AND delivery_date = ?"
            params.append(datetime.today().date().isoformat())
        elif "tomorrow" in q_lower:
            query += " AND delivery_date = ?"
            params.append((datetime.today().date() + timedelta(days=1)).isoformat())
        if "pending" in q_lower:
            query += " AND status = 'Pending'"
        if "delayed" in q_lower:
            query += " AND status = 'Delayed'"
        name_match = re.search(r"status of (\w+)", q_lower)
        if name_match:
            query += " AND customer_name LIKE ?"
            params.append(f"%{name_match.group(1)}%")
        id_match = re.search(r"#?(\d+)", q_lower)
        if id_match and "order" in q_lower:
            query += " AND order_id = ?"
            params.append(id_match.group(1))
    if date:
        parsed = parse_date(date)
        query += " AND delivery_date = ?"
        params.append(parsed)
    if customer:
        query += " AND customer_name LIKE ?"
        params.append(f"%{customer}%")
    if status:
        query += " AND status = ?"
        params.append(status)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/today_deliveries")
async def today_deliveries():
    conn = get_db()
    today = datetime.today().date().isoformat()
    rows = conn.execute("SELECT * FROM orders WHERE delivery_date = ?", (today,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/")
async def root():
    return {"message": "Order & Delivery Reminder AI Agent is running!", "docs": "/docs"}

# ---------- Background Scheduler (Proper Threading) ----------
def reminder_job():
    print("\n🔔 Running Reminder Check...")
    conn = get_db()
    today = datetime.today().date()
    today_orders = conn.execute("SELECT * FROM orders WHERE delivery_date = ? AND status != 'Delivered'", (today.isoformat(),)).fetchall()
    if today_orders:
        msg = "🚚 Today's Deliveries:\n" + "\n".join([f"{row['order_id']} - {row['customer_name']}" for row in today_orders])
        print(msg)
    conn.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(reminder_job, CronTrigger(hour=8, minute=0))
    scheduler.start()
    print("✅ Scheduler started successfully!")

# Scheduler ke alada thread e run korbo (Windows er jonno safe)
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

# ---------- Run ----------
if __name__ == "__main__":
    print("🚀 Server is starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)