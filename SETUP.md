# GigShield-AI — Setup & Run Guide

## Prerequisites

You only need **Python 3.9+** installed. That's it — no Docker, no Node.js, no external database.

### Check if Python is installed

Open your terminal (Command Prompt / PowerShell on Windows, Terminal on Mac/Linux) and run:

```bash
python3 --version
```

If this shows `Python 3.9` or higher, you're good. On Windows you might need `python` instead of `python3`.

### Install Flask (the only dependency)

```bash
pip install flask
```

Or on some systems:

```bash
pip3 install flask
```

If you get a permissions error, add `--user`:

```bash
pip3 install flask --user
```

---

## Step-by-Step Setup

### Step 1 — Download and unzip the project

After downloading the `gigshield-ai` folder, your structure should look like:

```
gigshield-ai/
├── backend/
│   ├── __init__.py
│   ├── app.py              ← Main server file
│   ├── database.py
│   ├── models/
│   │   └── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── analytics.py
│   │   ├── claims.py
│   │   ├── simulation.py
│   │   └── workers.py
│   └── services/
│       ├── __init__.py
│       ├── claim_processor.py
│       ├── decision_engine.py
│       └── risk_engine.py
├── frontend/
│   └── index.html           ← Dashboard UI
├── scripts/
│   └── seed.py
├── README.md
└── SETUP.md                 ← You are here
```

### Step 2 — Open terminal in the project folder

**Windows:**
- Open File Explorer, navigate to the `gigshield-ai` folder
- Click the address bar, type `cmd`, press Enter
- Or: `cd C:\Users\YourName\Downloads\gigshield-ai`

**Mac / Linux:**
```bash
cd ~/Downloads/gigshield-ai
```

### Step 3 — Run the server

```bash
python3 backend/app.py
```

On Windows (if `python3` doesn't work):
```bash
python backend/app.py
```

You should see:

```
[DB] Database initialized successfully.
[SEED] Inserted 35 workers.
[SEED] Inserted 16 weather records.
[SEED] Database seeded successfully!

============================================================
  GigShield-AI Server
  Forensic Device Intelligence · Parametric Fraud Defense
============================================================

  🌐 Dashboard:  http://localhost:5000
  📡 API Index:  http://localhost:5000/api
  💚 Health:     http://localhost:5000/api/health

  Built for Guidewire DEVTrails 2026
============================================================
```

### Step 4 — Open the dashboard

Open your browser and go to:

```
http://localhost:5000
```

That's it! The dashboard is live.

---

## Using the Dashboard

### Start a Live Simulation
Click **▶ Start Simulation** in the top-right. This generates realistic claims every 1.5 seconds — a mix of legitimate workers and ~15% fraud attempts. Watch the stats update in real time.

### Trigger the 500-Worker Attack
Click **🚨 Cluster Attack**. This simulates the coordinated GPS spoofing scenario from the pitch — 25 fraudulent claims targeting the same geo-cell simultaneously. You'll see:
- Cluster score spike to 9.8
- Circuit breaker activate
- Claims get held for review
- Amount saved counter jump

### Review Claims
Go to the **Claims Feed** tab. Click any claim to see:
- Full 5-signal decomposition with scores
- Device flags (mock location, root, emulator)
- Decision reason
- For held claims: **Approve** or **Reject** buttons

### View Architecture
The **Architecture** tab shows the full system diagram, claim processing sequence, and cluster state machine.

### Audit Trail
The **Audit Log** tab shows every decision the system has made — immutable trail for compliance.

---

## Testing the API Directly

You can also hit the API with curl or Postman:

```bash
# Health check
curl http://localhost:5000/api/health

# See all API routes
curl http://localhost:5000/api

# List workers
curl http://localhost:5000/api/workers

# Submit a legitimate claim
curl -X POST http://localhost:5000/api/simulate/claim \
  -H "Content-Type: application/json" \
  -d '{"is_fraud": false}'

# Submit a fraud claim
curl -X POST http://localhost:5000/api/simulate/claim \
  -H "Content-Type: application/json" \
  -d '{"is_fraud": true}'

# Run a batch of 20 claims (30% fraud)
curl -X POST http://localhost:5000/api/simulate/batch \
  -H "Content-Type: application/json" \
  -d '{"count": 20, "fraud_ratio": 0.3}'

# Trigger cluster attack
curl -X POST http://localhost:5000/api/simulate/cluster-attack \
  -H "Content-Type: application/json" \
  -d '{"count": 25, "city": "Mumbai", "zone": "Andheri"}'

# Dashboard analytics
curl http://localhost:5000/api/analytics/dashboard

# Reset everything
curl -X POST http://localhost:5000/api/simulate/reset
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
Flask isn't installed. Run: `pip3 install flask`

### "ModuleNotFoundError: No module named 'backend'"
You're running from the wrong directory. Make sure you `cd` into the `gigshield-ai` folder first, then run `python3 backend/app.py`.

### "Address already in use" / port 5000 busy
Another process is using port 5000. Either stop it, or edit `backend/app.py` and change the port number on the last line:
```python
app.run(host='0.0.0.0', port=8080, debug=True)  # change 5000 to 8080
```
Then open `http://localhost:8080` instead.

On Mac, AirPlay Receiver sometimes uses port 5000. Go to System Settings → General → AirDrop & Handoff → Turn off AirPlay Receiver. Or just use port 8080.

### "python3 not found" (Windows)
Try `python` instead of `python3`. If that doesn't work, download Python from https://www.python.org/downloads/ — make sure to check "Add Python to PATH" during installation.

### Database gets corrupted
Delete the `gigshield.db` file in the project root and restart the server. It will auto-recreate and reseed.

```bash
rm gigshield.db       # Mac/Linux
del gigshield.db      # Windows
python3 backend/app.py
```

---

## What Happens on First Run

1. SQLite database (`gigshield.db`) is auto-created in the project root
2. 9 tables are initialized (workers, claims, signals, clusters, etc.)
3. 35 gig workers across Mumbai, Delhi, and Bangalore are seeded
4. 16 active weather zones are populated
5. Server starts on port 5000
6. Frontend is served at the root URL

No manual setup steps needed — everything is automatic.
