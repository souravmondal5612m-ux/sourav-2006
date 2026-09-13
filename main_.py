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
class OrderBase(BaseModel):
    customer_name: str
    customer_phone: Optional[str] = ""
    product_items: str
    quantity: int = 1
    delivery_date: str
    special_instructions: Optional[str] = ""

class OrderCreate(OrderBase):
    order_id: str

class OrderUpdate(BaseModel):
    status: Optional[str] = None

class OrderEdit(OrderBase):
    pass

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

# ---------- API Endpoints ----------
@app.post("/add_order")
async def add_order(order: OrderCreate):
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order.order_id,)).fetchone()
    if existing:
        conn.close()
        return {"message": f"Order {order.order_id} already exists! Please use Update option."}
    
    conn.execute("""INSERT INTO orders 
                (order_id, customer_name, customer_phone, product_items, quantity, order_date, delivery_date, special_instructions, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order.order_id, order.customer_name, order.customer_phone, order.product_items, 
                order.quantity, datetime.today().date().isoformat(), order.delivery_date, 
                order.special_instructions, "Pending"))
    conn.commit()
    conn.close()
    return {"message": f"Order {order.order_id} added successfully!"}

# NEW: Update Order Details
@app.put("/update_order/{order_id}")
async def update_order_details(order_id: str, order: OrderEdit):
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    conn.execute("""UPDATE orders SET 
                customer_name = ?, customer_phone = ?, product_items = ?, 
                quantity = ?, delivery_date = ?, special_instructions = ?
                WHERE order_id = ?""",
                (order.customer_name, order.customer_phone, order.product_items, 
                order.quantity, order.delivery_date, order.special_instructions, order_id))
    conn.commit()
    conn.close()
    return {"message": f"Order {order_id} details updated successfully!"}

# NEW: Delete Order
@app.delete("/delete_order/{order_id}")
async def delete_order(order_id: str):
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"message": f"Order {order_id} deleted successfully!"}

@app.put("/update_status/{order_id}")
async def update_status(order_id: str, update: OrderUpdate):
    if update.status not in ["Pending", "In Production", "Ready", "Delivered", "Delayed", "Cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = get_db()
    existing = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (update.status, order_id))
    conn.commit()
    conn.close()
    return {"message": f"Order {order_id} updated to {update.status}"}

@app.get("/orders")
async def get_orders(q: Optional[str] = None):
    conn = get_db()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    today = datetime.today().date().isoformat()
    
    if q:
        q_lower = q.lower()
        if "today" in q_lower:
            query += " AND delivery_date = ?"
            params.append(today)
        elif "tomorrow" in q_lower:
            query += " AND delivery_date = ?"
            params.append((datetime.today().date() + timedelta(days=1)).isoformat())
        elif "delayed" in q_lower:
            query += " AND delivery_date < ? AND status NOT IN ('Delivered', 'Cancelled')"
            params.append(today)
        elif "pending" in q_lower:
            query += " AND status = 'Pending'"
        
        name_match = re.search(r"status of (\w+)", q_lower)
        if name_match:
            query += " AND customer_name LIKE ?"
            params.append(f"%{name_match.group(1)}%")
    
    query += " ORDER BY delivery_date ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/today_deliveries")
async def today_deliveries():
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE delivery_date = ?", (datetime.today().date().isoformat(),)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/delayed_orders")
async def get_delayed():
    conn = get_db()
    today = datetime.today().date().isoformat()
    rows = conn.execute("SELECT * FROM orders WHERE delivery_date < ? AND status NOT IN ('Delivered', 'Cancelled')", (today,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/")
async def root():
    return {"message": "Order & Delivery Reminder AI Agent is running!"}

# Scheduler (unchanged)
def reminder_job():
    print("\n🔔 Running Reminder Check...")
    # (same as before)

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(reminder_job, CronTrigger(hour=8, minute=0))
    scheduler.start()

threading.Thread(target=start_scheduler, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)