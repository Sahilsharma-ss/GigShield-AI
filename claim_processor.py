"""
GigShield-AI Claim Processor
Core claim processing pipeline extracted for reuse by both API routes and simulation.
"""

import uuid
import json
from datetime import datetime

from backend.database import get_db, dict_from_row, rows_to_list
from backend.services.risk_engine import compute_individual_risk_score, compute_cluster_risk
from backend.services.decision_engine import (
    make_decision, update_cluster_state, log_audit, update_worker_stats
)


def process_claim(worker_id: str, city: str, zone: str, disruption_type: str,
                  amount: float, latitude: float = None, longitude: float = None,
                  signals: dict = None) -> dict:
    """
    Full claim processing pipeline:
    1. Validate worker
    2. Store claim + signals
    3. Risk scoring (5 signals → individual score)
    4. Cluster detection
    5. Decision engine
    6. Audit logging
    7. Worker stats update

    Returns dict with full result or raises ValueError.
    """
    signals = signals or {}

    # Validate worker
    with get_db() as db:
        worker = dict_from_row(db.execute(
            "SELECT * FROM workers WHERE id = ?", (worker_id,)
        ).fetchone())

    if not worker:
        raise ValueError('Worker not found')
    if worker.get('is_banned'):
        raise ValueError('Worker account is suspended')

    # Fall back to worker defaults for city/zone
    if not city:
        city = worker['city']
    if not zone:
        zone = worker['zone']

    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

    # ── Step 1: Store claim ──────────────────────────────────────────
    with get_db() as db:
        db.execute("""
            INSERT INTO claims (id, worker_id, city, zone, latitude, longitude,
                disruption_type, amount, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSING')
        """, (claim_id, worker_id, city, zone, latitude, longitude,
              disruption_type, amount))

    # ── Step 2: Store sensor signals ─────────────────────────────────
    accel_data = signals.get('accelerometer_data', [])
    if isinstance(accel_data, list):
        accel_data = json.dumps(accel_data)

    with get_db() as db:
        db.execute("""
            INSERT INTO claim_signals (
                claim_id, gps_lat, gps_lng, gps_accuracy,
                accelerometer_data, barometric_pressure, barometric_altitude,
                mock_location_on, is_rooted, is_emulator,
                attestation_token, attestation_valid,
                network_type, ip_address, session_duration_sec,
                movement_continuity, device_integrity, environmental_match,
                historical_reliability, behavioral_anomaly
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)
        """, (
            claim_id,
            signals.get('gps_lat', latitude),
            signals.get('gps_lng', longitude),
            signals.get('gps_accuracy', 10),
            accel_data,
            signals.get('barometric_pressure'),
            signals.get('barometric_altitude'),
            1 if signals.get('mock_location_on') else 0,
            1 if signals.get('is_rooted') else 0,
            1 if signals.get('is_emulator') else 0,
            signals.get('attestation_token', ''),
            1 if signals.get('attestation_valid', True) else 0,
            signals.get('network_type', 'LTE'),
            signals.get('ip_address', ''),
            signals.get('session_duration_sec', 300),
        ))

    # ── Step 3: Fetch weather data ───────────────────────────────────
    with get_db() as db:
        weather_row = db.execute("""
            SELECT * FROM weather_data
            WHERE city = ? AND zone = ? AND is_active = 1
            ORDER BY fetched_at DESC LIMIT 1
        """, (city, zone)).fetchone()
        weather = dict_from_row(weather_row) if weather_row else None

    # ── Step 4: Get recent claims for behavioral analysis ────────────
    with get_db() as db:
        recent_rows = db.execute("""
            SELECT c.*, cs.ip_address, cs.mock_location_on
            FROM claims c
            LEFT JOIN claim_signals cs ON cs.claim_id = c.id
            WHERE c.city = ? AND c.zone = ?
            AND c.created_at >= datetime('now', '-15 minutes')
            AND c.id != ?
        """, (city, zone, claim_id)).fetchall()
        recent_claims = rows_to_list(recent_rows)

    # ── Step 5: Compute individual risk score ────────────────────────
    signals_for_scoring = dict(signals)
    signals_for_scoring['disruption_type'] = disruption_type

    risk_result = compute_individual_risk_score(
        signals=signals_for_scoring,
        worker=worker,
        weather=weather,
        claim={'created_at': datetime.now().isoformat(),
               'ip_address': signals.get('ip_address', ''),
               'amount': amount},
        recent_claims=recent_claims
    )

    individual_score = risk_result['individual_score']

    # ── Step 6: Cluster detection ────────────────────────────────────
    cluster_result = compute_cluster_risk(claim_id, city, zone)
    cluster_score = cluster_result['cluster_score']

    # Update or create cluster record
    cluster_id = update_cluster_state(city, zone, cluster_result)

    # ── Step 7: Decision engine ──────────────────────────────────────
    has_connectivity = signals.get('network_type') == 'NONE'
    decision = make_decision(
        claim_id=claim_id,
        individual_score=individual_score,
        cluster_score=cluster_score,
        cluster_state=cluster_result['cluster_state'],
        circuit_breaker=cluster_result['circuit_breaker'],
        has_connectivity_issues=has_connectivity,
    )

    status = decision['status']
    payout_at = None
    if status == 'AUTO_APPROVED':
        payout_at = datetime.now().isoformat()

    # ── Step 8: Update claim with results ────────────────────────────
    with get_db() as db:
        db.execute("""
            UPDATE claims SET
                status = ?, individual_score = ?, cluster_score = ?,
                cluster_id = ?, decision_reason = ?, payout_at = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (status, individual_score, cluster_score,
              cluster_id, decision['reason'], payout_at, claim_id))

        db.execute("""
            UPDATE claim_signals SET
                movement_continuity = ?, device_integrity = ?,
                environmental_match = ?, historical_reliability = ?,
                behavioral_anomaly = ?
            WHERE claim_id = ?
        """, (risk_result['movement_continuity'], risk_result['device_integrity'],
              risk_result['environmental_match'], risk_result['historical_reliability'],
              risk_result['behavioral_anomaly'], claim_id))

    # ── Step 9: Grace queue ──────────────────────────────────────────
    if status == 'GRACE_QUEUED':
        with get_db() as db:
            db.execute("""
                INSERT INTO grace_queue (claim_id, reason, next_retry_at)
                VALUES (?, ?, datetime('now', '+30 minutes'))
            """, (claim_id, 'Network connectivity issues'))

    # ── Step 10: Audit log ───────────────────────────────────────────
    log_audit(
        event_type=status,
        entity_type='CLAIM',
        entity_id=claim_id,
        details={
            'worker_id': worker_id,
            'individual_score': individual_score,
            'cluster_score': cluster_score,
            'cluster_state': cluster_result['cluster_state'],
            'circuit_breaker': cluster_result['circuit_breaker'],
            'signals': risk_result,
        }
    )

    # ── Step 11: Update worker stats ─────────────────────────────────
    update_worker_stats(worker_id, status)

    return {
        'claim_id': claim_id,
        'status': status,
        'individual_score': individual_score,
        'cluster_score': cluster_score,
        'cluster_state': cluster_result['cluster_state'],
        'circuit_breaker': cluster_result['circuit_breaker'],
        'decision_reason': decision['reason'],
        'worker_message': decision.get('worker_message'),
        'estimated_wait': decision.get('estimated_wait'),
        'signals': risk_result,
        'cluster_details': cluster_result,
        'amount': amount,
        'payout_at': payout_at,
    }
