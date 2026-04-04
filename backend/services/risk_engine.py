"""
GigShield-AI Risk Intelligence Engine
Implements the 5-signal risk scoring pipeline + cluster anomaly detection.
Matches riskScore.mmd flowchart exactly.
"""

import math
import random
from datetime import datetime, timedelta
from backend.database import get_db, rows_to_list

# ─── RISK WEIGHTS (from flowchart) ──────────────────────────────────
WEIGHTS = {
    'movement_continuity':    0.30,
    'device_integrity':       0.25,
    'environmental_match':    0.20,
    'historical_reliability': 0.15,
    'behavioral_anomaly':     0.10,
}

# ─── INDIVIDUAL THRESHOLDS ──────────────────────────────────────────
INDIVIDUAL_THRESHOLDS = {
    'auto_approve': 2.5,
    'step_up':      6.0,
    # > 6.0 → investigate hold
}

# ─── CLUSTER THRESHOLDS (from stateMachine.mmd) ─────────────────────
CLUSTER_THRESHOLDS = {
    'normal':       3.0,
    'yellow_alert': 6.5,
    # > 6.5 → red alert
}

CLUSTER_WINDOW_MINUTES = 15
CLUSTER_MIN_CLAIMS = 5
CLUSTER_RADIUS_KM = 2


def clamp(value, lo=0.0, hi=10.0):
    return max(lo, min(hi, value))


# ═════════════════════════════════════════════════════════════════════
# SIGNAL SCORING FUNCTIONS
# ═════════════════════════════════════════════════════════════════════

def score_movement_continuity(signals: dict) -> float:
    """
    Check movement continuity (accelerometer + GPS breadcrumbs).
    Returns 0-10 risk score. Higher = more suspicious.
    """
    score = 0.0

    # Mock location is a huge red flag
    if signals.get('mock_location_on'):
        score += 5.0

    # Check GPS accuracy — very high accuracy with no movement is suspicious
    accuracy = signals.get('gps_accuracy', 10)
    if accuracy > 100:
        score += 1.5  # poor GPS, could be indoor/spoofed
    elif accuracy < 2:
        score += 2.0  # suspiciously perfect

    # Check accelerometer — no movement data when claiming outdoor disruption
    accel_data = signals.get('accelerometer_data', [])
    if isinstance(accel_data, str):
        try:
            import json
            accel_data = json.loads(accel_data)
        except:
            accel_data = []

    if len(accel_data) == 0:
        score += 3.0  # no accelerometer data at all
    elif len(accel_data) < 5:
        score += 1.5  # very little movement data
    else:
        # Check variance — real movement has variance
        if all(abs(v) < 0.01 for v in accel_data[:10] if isinstance(v, (int, float))):
            score += 2.5  # perfectly still = suspicious

    # Session duration check
    session_dur = signals.get('session_duration_sec', 300)
    if session_dur < 30:
        score += 1.5  # submitted too quickly

    return clamp(score)


def score_device_integrity(signals: dict) -> float:
    """
    Check device integrity (mock location, root, emulator flags).
    """
    score = 0.0

    if signals.get('mock_location_on'):
        score += 4.0
    if signals.get('is_rooted'):
        score += 3.0
    if signals.get('is_emulator'):
        score += 4.0
    if not signals.get('attestation_valid', True):
        score += 3.0

    return clamp(score)


def score_environmental_match(signals: dict, weather_data: dict) -> float:
    """
    Fetch hyperlocal weather + nearby disruption data.
    Does environment match the claimed disruption?
    """
    score = 0.0

    if not weather_data or not weather_data.get('is_active'):
        score += 5.0  # no active weather event but claiming disruption
        return clamp(score)

    # Check barometric pressure consistency
    baro = signals.get('barometric_pressure')
    if baro:
        # During heavy rain, pressure typically drops
        severity = weather_data.get('severity', 5)
        if severity > 7 and baro > 1020:
            score += 2.0  # high pressure during supposed storm
        elif severity < 3 and baro < 1000:
            score += 1.5  # low pressure but no real storm

    # Check altitude consistency
    altitude = signals.get('barometric_altitude')
    if altitude and altitude < -100 or (altitude and altitude > 5000):
        score += 2.0  # impossible altitude

    # Weather severity vs claim type mismatch
    rainfall = weather_data.get('rainfall_mm', 0)
    disruption = signals.get('disruption_type', '')
    if 'flood' in disruption.lower() and rainfall < 10:
        score += 3.0  # claiming flood with barely any rain
    if 'heavy rain' in disruption.lower() and rainfall < 5:
        score += 2.5

    return clamp(score)


def score_historical_reliability(worker: dict) -> float:
    """Load worker historical reliability score."""
    if not worker:
        return 5.0  # unknown worker = neutral

    total = worker.get('total_claims', 0)
    if total == 0:
        return 3.0  # new worker, slightly elevated

    approved_ratio = worker.get('approved_claims', 0) / max(total, 1)
    flagged_ratio = worker.get('flagged_claims', 0) / max(total, 1)

    # Convert reliability_score (0-10 where 10 = very reliable, invert for risk)
    reliability = worker.get('reliability_score', 5.0)
    risk = 10.0 - reliability

    # Adjust based on history
    if flagged_ratio > 0.3:
        risk += 2.0
    elif flagged_ratio > 0.1:
        risk += 1.0

    if approved_ratio > 0.9 and total > 10:
        risk -= 1.5  # consistently honest worker

    return clamp(risk)


def score_behavioral_anomaly(claim: dict, worker: dict, recent_claims: list) -> float:
    """
    Does this claim pattern look like anyone else's right now?
    Check for coordinated submission patterns.
    """
    score = 0.0

    if not recent_claims:
        return 0.5  # no peers to compare

    # Check timing similarity
    claim_time = datetime.fromisoformat(claim.get('created_at', datetime.now().isoformat()))
    similar_time_count = 0
    same_ip_count = 0
    same_amount_count = 0

    claim_ip = claim.get('ip_address', '')
    claim_amount = claim.get('amount', 0)

    for rc in recent_claims:
        rc_time = datetime.fromisoformat(rc.get('created_at', datetime.now().isoformat()))
        if abs((claim_time - rc_time).total_seconds()) < 60:
            similar_time_count += 1
        if rc.get('ip_address') == claim_ip and claim_ip:
            same_ip_count += 1
        if abs(rc.get('amount', 0) - claim_amount) < 10:
            same_amount_count += 1

    # Many claims at exact same time = coordinated
    if similar_time_count > 10:
        score += 4.0
    elif similar_time_count > 5:
        score += 2.5
    elif similar_time_count > 2:
        score += 1.0

    # Same IP address
    if same_ip_count > 3:
        score += 3.0
    elif same_ip_count > 1:
        score += 1.5

    # Same amount pattern
    if same_amount_count > 5:
        score += 1.5

    return clamp(score)


# ═════════════════════════════════════════════════════════════════════
# MAIN RISK SCORING PIPELINE
# ═════════════════════════════════════════════════════════════════════

def compute_individual_risk_score(signals: dict, worker: dict, weather: dict,
                                   claim: dict, recent_claims: list) -> dict:
    """
    Full individual risk scoring pipeline.
    Returns dict with each signal score and weighted total.
    """
    movement = score_movement_continuity(signals)
    device = score_device_integrity(signals)
    environment = score_environmental_match(signals, weather)
    historical = score_historical_reliability(worker)
    behavioral = score_behavioral_anomaly(claim, worker, recent_claims)

    total = (
        movement   * WEIGHTS['movement_continuity'] +
        device     * WEIGHTS['device_integrity'] +
        environment * WEIGHTS['environmental_match'] +
        historical * WEIGHTS['historical_reliability'] +
        behavioral * WEIGHTS['behavioral_anomaly']
    )

    return {
        'movement_continuity': round(movement, 2),
        'device_integrity': round(device, 2),
        'environmental_match': round(environment, 2),
        'historical_reliability': round(historical, 2),
        'behavioral_anomaly': round(behavioral, 2),
        'individual_score': round(clamp(total), 2),
    }


# ═════════════════════════════════════════════════════════════════════
# CLUSTER DETECTION (from stateMachine.mmd)
# ═════════════════════════════════════════════════════════════════════

def compute_cluster_risk(claim_id: str, city: str, zone: str) -> dict:
    """
    Run cluster check: recent claims in same geo-cell, last 15 min, radius < 2km.
    5+ claims with shared fingerprints or sync timestamps → elevate cluster score.
    """
    with get_db() as db:
        # Use SQLite's datetime('now') for consistent UTC comparison
        rows = db.execute("""
            SELECT c.*, cs.mock_location_on, cs.ip_address, cs.is_rooted,
                   cs.attestation_valid, cs.device_integrity
            FROM claims c
            LEFT JOIN claim_signals cs ON cs.claim_id = c.id
            WHERE c.city = ? AND c.zone = ?
            AND c.created_at >= datetime('now', '-15 minutes')
            AND c.id != ?
        """, (city, zone, claim_id)).fetchall()

        recent = rows_to_list(rows)
        claim_count = len(recent)

        if claim_count < 3:
            return {
                'cluster_score': round(claim_count * 0.5, 2),
                'cluster_state': 'NORMAL',
                'claim_count': claim_count,
                'shared_fingerprints': 0,
                'circuit_breaker': False,
            }

        # Count shared fingerprints
        mock_count = sum(1 for c in recent if c.get('mock_location_on'))
        failed_attest = sum(1 for c in recent if not c.get('attestation_valid', True))

        # Group by IP
        ips = [c.get('ip_address') for c in recent if c.get('ip_address')]
        ip_counts = {}
        for ip in ips:
            ip_counts[ip] = ip_counts.get(ip, 0) + 1
        shared_ip = sum(1 for v in ip_counts.values() if v > 2)

        shared_fingerprints = mock_count + failed_attest + shared_ip

        # Compute cluster score
        if claim_count >= CLUSTER_MIN_CLAIMS and shared_fingerprints >= 3:
            ratio = shared_fingerprints / max(claim_count, 1)
            cluster_score = clamp(6.5 + ratio * 3.5, 6.5, 9.8)
            state = 'RED_ALERT'
            circuit_breaker = True
        elif claim_count >= 3:
            cluster_score = clamp(3.0 + (claim_count / 15) * 3.5, 3.0, 6.5)
            state = 'YELLOW_ALERT'
            circuit_breaker = False
        else:
            cluster_score = clamp(claim_count * 0.8, 0, 3.0)
            state = 'NORMAL'
            circuit_breaker = False

        return {
            'cluster_score': round(cluster_score, 2),
            'cluster_state': state,
            'claim_count': claim_count,
            'shared_fingerprints': shared_fingerprints,
            'circuit_breaker': circuit_breaker,
            'mock_location_count': mock_count,
            'failed_attestation_count': failed_attest,
            'shared_ip_groups': shared_ip,
        }
