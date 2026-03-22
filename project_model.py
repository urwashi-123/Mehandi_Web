import sqlite3
from datetime import datetime
import math

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        email TEXT,
        lat REAL,
        lng REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Mechanics table
    c.execute('''CREATE TABLE IF NOT EXISTS mechanics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        skills TEXT,
        lat REAL,
        lng REAL,
        status TEXT DEFAULT 'offline', -- online/offline/busy
        rating REAL DEFAULT 5.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Service requests table
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        mechanic_id INTEGER,
        service_type TEXT,
        user_lat REAL,
        user_lng REAL,
        status TEXT DEFAULT 'pending', -- pending/accepted/completed/cancelled
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (mechanic_id) REFERENCES mechanics (id)
    )''')
    
    conn.commit()
    conn.close()

# Haversine formula for distance calculation
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c * 1000  # Distance in meters