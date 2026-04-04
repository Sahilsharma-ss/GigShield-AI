"""
GigShield-AI Database Layer
SQLite database with full schema for the parametric insurance fraud detection system.
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'gigshield.db')


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_db() as db:
        db.executescript("""
        -- ═══════════════════════════════════════════════════
        -- WORKERS
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS workers (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            phone           TEXT UNIQUE,
            city            TEXT NOT NULL,
            zone            TEXT NOT NULL,
            reliability_score REAL DEFAULT 5.0,
            total_claims    INTEGER DEFAULT 0,
            approved_claims INTEGER DEFAULT 0,
            flagged_claims  INTEGER DEFAULT 0,
            is_banned       INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        -- ═══════════════════════════════════════════════════
        -- CLAIMS
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS claims (
            id              TEXT PRIMARY KEY,
            worker_id       TEXT NOT NULL REFERENCES workers(id),
            city            TEXT NOT NULL,
            zone            TEXT NOT NULL,
            latitude        REAL,
            longitude       REAL,
            disruption_type TEXT NOT NULL,
            amount          REAL NOT NULL,
            status          TEXT NOT NULL DEFAULT 'PROCESSING'
                            CHECK(status IN (
                                'PROCESSING',
                                'AUTO_APPROVED',
                                'STEP_UP_VERIFICATION',
                                'STEP_UP_APPROVED',
                                'STEP_UP_REJECTED',
                                'INVESTIGATE_HOLD',
                                'ANALYST_APPROVED',
                                'ANALYST_REJECTED',
                                'GRACE_QUEUED',
                                'APPEALED',
                                'APPEAL_APPROVED',
                                'APPEAL_REJECTED'
                            )),
            individual_score REAL,
            cluster_score    REAL,
            cluster_id       TEXT,
            decision_reason  TEXT,
            payout_at        TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            updated_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_claims_worker ON claims(worker_id);
        CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
        CREATE INDEX IF NOT EXISTS idx_claims_zone_time ON claims(city, zone, created_at);
        CREATE INDEX IF NOT EXISTS idx_claims_cluster ON claims(cluster_id);

        -- ═══════════════════════════════════════════════════
        -- SENSOR SIGNALS (per-claim raw + scored signals)
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS claim_signals (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id              TEXT NOT NULL UNIQUE REFERENCES claims(id),
            -- Raw sensor data
            gps_lat               REAL,
            gps_lng               REAL,
            gps_accuracy          REAL,
            accelerometer_data    TEXT,  -- JSON array
            barometric_pressure   REAL,
            barometric_altitude   REAL,
            mock_location_on      INTEGER DEFAULT 0,
            is_rooted             INTEGER DEFAULT 0,
            is_emulator           INTEGER DEFAULT 0,
            attestation_token     TEXT,
            attestation_valid     INTEGER DEFAULT 1,
            network_type          TEXT,
            ip_address            TEXT,
            session_duration_sec  INTEGER,
            -- Scored signals (0-10, higher = riskier)
            movement_continuity   REAL NOT NULL,
            device_integrity      REAL NOT NULL,
            environmental_match   REAL NOT NULL,
            historical_reliability REAL NOT NULL,
            behavioral_anomaly    REAL NOT NULL,
            created_at            TEXT DEFAULT (datetime('now'))
        );

        -- ═══════════════════════════════════════════════════
        -- CLUSTERS (geo-cell groupings)
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS clusters (
            id              TEXT PRIMARY KEY,
            city            TEXT NOT NULL,
            zone            TEXT NOT NULL,
            state           TEXT NOT NULL DEFAULT 'NORMAL'
                            CHECK(state IN (
                                'NORMAL','YELLOW_ALERT','RED_ALERT',
                                'INVESTIGATING','RESOLVED','BANNED'
                            )),
            cluster_score   REAL DEFAULT 0,
            claim_count     INTEGER DEFAULT 0,
            fraud_count     INTEGER DEFAULT 0,
            shared_fingerprints INTEGER DEFAULT 0,
            circuit_breaker_active INTEGER DEFAULT 0,
            payout_throttled      INTEGER DEFAULT 0,
            analyst_id       TEXT,
            notes            TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            resolved_at      TEXT,
            updated_at       TEXT DEFAULT (datetime('now'))
        );

        -- ═══════════════════════════════════════════════════
        -- WEATHER DATA (cached per zone)
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS weather_data (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            city            TEXT NOT NULL,
            zone            TEXT NOT NULL,
            disruption_type TEXT,
            severity        REAL,
            rainfall_mm     REAL,
            wind_speed_kmh  REAL,
            is_active       INTEGER DEFAULT 1,
            fetched_at      TEXT DEFAULT (datetime('now'))
        );

        -- ═══════════════════════════════════════════════════
        -- AUDIT LOG (immutable trail)
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type      TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            entity_id       TEXT NOT NULL,
            actor           TEXT DEFAULT 'SYSTEM',
            details         TEXT,  -- JSON
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type);

        -- ═══════════════════════════════════════════════════
        -- APPEALS
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS appeals (
            id              TEXT PRIMARY KEY,
            claim_id        TEXT NOT NULL REFERENCES claims(id),
            worker_id       TEXT NOT NULL REFERENCES workers(id),
            reason          TEXT NOT NULL,
            evidence        TEXT,  -- JSON (photo URLs, etc.)
            status          TEXT DEFAULT 'PENDING'
                            CHECK(status IN ('PENDING','APPROVED','REJECTED')),
            reviewer_notes  TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            resolved_at     TEXT
        );

        -- ═══════════════════════════════════════════════════
        -- GRACE QUEUE (connectivity-issue claims)
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS grace_queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id        TEXT NOT NULL REFERENCES claims(id),
            reason          TEXT NOT NULL,
            retry_count     INTEGER DEFAULT 0,
            max_retries     INTEGER DEFAULT 3,
            next_retry_at   TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- ═══════════════════════════════════════════════════
        -- MODEL RETRAINING LOG
        -- ═══════════════════════════════════════════════════
        CREATE TABLE IF NOT EXISTS retraining_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_type    TEXT NOT NULL,
            trigger_id      TEXT,
            samples_added   INTEGER,
            accuracy_before REAL,
            accuracy_after  REAL,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        """)
    print("[DB] Database initialized successfully.")


def dict_from_row(row):
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]
