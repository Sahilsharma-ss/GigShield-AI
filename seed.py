"""
Database Seed Script
Populates workers, weather data, and initial state.
"""

import sys
import os
import uuid
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.database import init_db, get_db

WORKERS = [
    # Mumbai
    ("Ramesh Kumar", "Mumbai", "Andheri"), ("Priya Sharma", "Mumbai", "Bandra"),
    ("Arjun Mehta", "Mumbai", "Dadar"), ("Deepa Rao", "Mumbai", "Borivali"),
    ("Vikram Tiwari", "Mumbai", "Thane"), ("Anita Patil", "Mumbai", "Kurla"),
    ("Suresh Bhatt", "Mumbai", "Andheri"), ("Kavita Desai", "Mumbai", "Bandra"),
    ("Mohan Lal", "Mumbai", "Dadar"), ("Neha Gupta", "Mumbai", "Thane"),
    ("Rajesh Verma", "Mumbai", "Kurla"), ("Sunita Chopra", "Mumbai", "Borivali"),
    ("Amit Hegde", "Mumbai", "Andheri"), ("Pooja Nair", "Mumbai", "Bandra"),
    ("Kiran Joshi", "Mumbai", "Dadar"),
    # Delhi
    ("Lakshmi Yadav", "Delhi", "Connaught Place"), ("Sanjay Kapoor", "Delhi", "Dwarka"),
    ("Meera Singh", "Delhi", "Rohini"), ("Arun Pandey", "Delhi", "Saket"),
    ("Divya Agarwal", "Delhi", "Karol Bagh"), ("Rahul Mishra", "Delhi", "Connaught Place"),
    ("Smita Khanna", "Delhi", "Dwarka"), ("Gaurav Thakur", "Delhi", "Rohini"),
    ("Ritu Saxena", "Delhi", "Saket"), ("Nikhil Bhat", "Delhi", "Karol Bagh"),
    # Bangalore
    ("Ajay Reddy", "Bangalore", "Koramangala"), ("Swati Iyer", "Bangalore", "Indiranagar"),
    ("Prakash Gowda", "Bangalore", "Whitefield"), ("Meghana Rao", "Bangalore", "Jayanagar"),
    ("Harish Shetty", "Bangalore", "HSR Layout"), ("Anjali Murthy", "Bangalore", "Koramangala"),
    ("Vinod Hegde", "Bangalore", "Indiranagar"), ("Rekha Das", "Bangalore", "Whitefield"),
    ("Sunil Kumar", "Bangalore", "Jayanagar"), ("Preethi Nair", "Bangalore", "HSR Layout"),
]

WEATHER_DATA = [
    ("Mumbai", "Andheri", "Heavy Rainfall", 7.5, 45, 35),
    ("Mumbai", "Bandra", "Heavy Rainfall", 8.0, 60, 40),
    ("Mumbai", "Dadar", "Flash Flood", 9.0, 80, 45),
    ("Mumbai", "Borivali", "Waterlogging", 6.5, 35, 25),
    ("Mumbai", "Thane", "Heavy Rainfall", 7.0, 40, 30),
    ("Mumbai", "Kurla", "Traffic Blackout", 5.0, 25, 20),
    ("Delhi", "Connaught Place", "Heavy Rainfall", 6.0, 30, 28),
    ("Delhi", "Dwarka", "Waterlogging", 7.0, 50, 32),
    ("Delhi", "Rohini", "Flash Flood", 8.5, 70, 38),
    ("Delhi", "Saket", "Heavy Rainfall", 5.5, 20, 22),
    ("Delhi", "Karol Bagh", "Traffic Blackout", 4.5, 15, 18),
    ("Bangalore", "Koramangala", "Heavy Rainfall", 7.0, 40, 30),
    ("Bangalore", "Indiranagar", "Flash Flood", 8.0, 55, 35),
    ("Bangalore", "Whitefield", "Road Collapse", 6.0, 30, 25),
    ("Bangalore", "Jayanagar", "Heavy Rainfall", 5.5, 25, 20),
    ("Bangalore", "HSR Layout", "Waterlogging", 7.5, 45, 28),
]


def seed():
    init_db()

    with get_db() as db:
        # Check if already seeded
        count = db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
        if count > 0:
            print(f"[SEED] Database already has {count} workers. Skipping seed.")
            return

        # Insert workers
        for name, city, zone in WORKERS:
            worker_id = f"WRK-{uuid.uuid4().hex[:8].upper()}"
            phone = f"+91{random.randint(7000000000, 9999999999)}"
            reliability = round(random.uniform(4.0, 9.5), 1)

            db.execute("""
                INSERT INTO workers (id, name, phone, city, zone, reliability_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (worker_id, name, phone, city, zone, reliability))

        print(f"[SEED] Inserted {len(WORKERS)} workers.")

        # Insert weather data
        for city, zone, dtype, severity, rain, wind in WEATHER_DATA:
            db.execute("""
                INSERT INTO weather_data (city, zone, disruption_type, severity, rainfall_mm, wind_speed_kmh)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (city, zone, dtype, severity, rain, wind))

        print(f"[SEED] Inserted {len(WEATHER_DATA)} weather records.")

    print("[SEED] Database seeded successfully!")


if __name__ == '__main__':
    seed()
