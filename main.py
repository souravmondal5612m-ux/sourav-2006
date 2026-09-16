from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import uvicorn
from typing import Optional
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import threading

# ---------- Database Setup ----------
# Render theke DATABASE_URL environment variable hishebe asbe
DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
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
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

# ---------- API Endpoints ----------
@app.post("/add_order")
async def add_order(order: OrderCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id = %s", (order.order_id,))
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
        return {"message": f"Order {order.order_id} already exists!"}
    
    cur.execute("""INSERT INTO orders 
                (order_id, customer_name, customer_phone, product_items, quantity, order_date, delivery_date, special_instructions, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (order.order_id, order.customer_name, order.customer_phone, order.product_items, 
                order.quantity, datetime.today().date().isoformat(), order.delivery_date, 
                order.special_instructions, "Pending"))
    conn.commit()
    cur.close(); conn.close()
    return {"message": f"Order {order.order_id} added successfully!"}

@app.put("/update_order/{order_id}")
async def update_order_details(order_id: str, order: OrderEdit):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    
    cur.execute("""UPDATE orders SET 
                customer_name = %s, customer_phone = %s, product_items = %s, 
                quantity = %s, delivery_date = %s, special_instructions = %s
                WHERE order_id = %s""",
                (order.customer_name, order.customer_phone, order.product_items, 
                order.quantity, order.delivery_date, order.special_instructions, order_id))
    conn.commit()
    cur.close(); conn.close()
    return {"message": f"Order {order_id} details updated successfully!"}

@app.delete("/delete_order/{order_id}")
async def delete_order(order_id: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
    if not cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    cur.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))
    conn.commit()
    cur.close(); conn.close()
    return {"message": f"Order {order_id} deleted successfully!"}

@app.put("/update_status/{order_id}")
async def update_status(order_id: str, update: OrderUpdate):
    if update.status not in ["Pending", "In Production", "Ready", "Delivered", "Delayed", "Cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = %s WHERE order_id = %s", (update.status, order_id))
    conn.commit()
    cur.close(); conn.close()
    return {"message": f"Order {order_id} updated to {update.status}"}

@app.get("/orders")
async def get_orders(q: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    today = datetime.today().date().isoformat()
    
    if q:
        q_lower = q.lower()
        if "today" in q_lower:
            query += " AND delivery_date = %s"
            params.append(today)
        elif "tomorrow" in q_lower:
            query += " AND delivery_date = %s"
            params.append((datetime.today().date() + timedelta(days=1)).isoformat())
        elif "delayed" in q_lower:
            query += " AND delivery_date < %s AND status NOT IN ('Delivered', 'Cancelled')"
            params.append(today)
        elif "pending" in q_lower:
            query += " AND status = 'Pending'"
        
        name_match = re.search(r"status of (\w+)", q_lower)
        if name_match:
            query += " AND customer_name LIKE %s"
            params.append(f"%{name_match.group(1)}%")
    
    query += " ORDER BY delivery_date ASC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(row) for row in rows]

@app.get("/today_deliveries")
async def today_deliveries():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE delivery_date = %s", (datetime.today().date().isoformat(),))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(row) for row in rows]

@app.get("/delayed_orders")
async def get_delayed():
    conn = get_db()
    cur = conn.cursor()
    today = datetime.today().date().isoformat()
    cur.execute("SELECT * FROM orders WHERE delivery_date < %s AND status NOT IN ('Delivered', 'Cancelled')", (today,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(row) for row in rows]

@app.get("/")
async def root():
    return {"message": "Order & Delivery Reminder AI Agent is running!"}

# Scheduler 
def reminder_job():
    print("\n🔔 Running Reminder Check...")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(reminder_job, CronTrigger(hour=8, minute=0))
    scheduler.start()

threading.Thread(target=start_scheduler, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)