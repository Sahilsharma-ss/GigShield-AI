"""
GigShield-AI Decision Orchestration Engine
Routes claims to: Auto-Approve / Step-Up Verification / Investigate Hold / Grace Queue
Matches claimDiagram.mmd sequence exactly.
"""

from datetime import datetime
from backend.database import get_db
from backend.services.risk_engine import (
    INDIVIDUAL_THRESHOLDS, CLUSTER_THRESHOLDS
)


def make_decision(claim_id: str, individual_score: float, cluster_score: float,
                  cluster_state: str, circuit_breaker: bool,
                  has_connectivity_issues: bool = False) -> dict:
    """
    Decision Engine — determines claim outcome.

    Rules (from claimDiagram.mmd):
    ─────────────────────────────────────────
    1. IND < 2.5 AND CLU < 3.0           → AUTO_APPROVED
    2. IND 2.5-6.0 OR CLU 3.0-6.5        → STEP_UP_VERIFICATION
    3. IND > 6.0 OR CLU > 6.5            → INVESTIGATE_HOLD
    4. Connectivity issues + low risk      → GRACE_QUEUED

    Additional rules:
    - Circuit breaker active → all claims in cell elevated
    - Grace queue for network-down scenarios
    """

    # Grace mode: if network is down and claim is not high-risk
    if has_connectivity_issues and individual_score < INDIVIDUAL_THRESHOLDS['step_up']:
        return {
            'status': 'GRACE_QUEUED',
            'reason': 'Connectivity issues detected. Claim queued with grace period.',
            'worker_message': 'We noticed network issues in your area. Your claim is safely queued and will be processed shortly.',
            'estimated_wait': '30 minutes',
        }

    # Circuit breaker override — force elevated review
    if circuit_breaker and individual_score >= INDIVIDUAL_THRESHOLDS['auto_approve']:
        return {
            'status': 'INVESTIGATE_HOLD',
            'reason': f'Geo-cell circuit breaker active. Cluster state: {cluster_state}. '
                      f'Individual: {individual_score:.1f}, Cluster: {cluster_score:.1f}',
            'worker_message': 'Quick safety check in progress — estimated wait: 5 minutes.',
            'estimated_wait': '5 minutes',
        }

    # Decision tree from claimDiagram.mmd
    if (individual_score < INDIVIDUAL_THRESHOLDS['auto_approve'] and
            cluster_score < CLUSTER_THRESHOLDS['normal']):
        return {
            'status': 'AUTO_APPROVED',
            'reason': f'Low risk. Individual: {individual_score:.1f}, Cluster: {cluster_score:.1f}. '
                      f'All signals within safe bounds.',
            'worker_message': None,  # instant payout, no message needed
            'estimated_wait': None,
            'payout_delay_ms': 100,
        }

    elif (individual_score < INDIVIDUAL_THRESHOLDS['step_up'] or
          cluster_score < CLUSTER_THRESHOLDS['yellow_alert']):
        return {
            'status': 'STEP_UP_VERIFICATION',
            'reason': f'Medium risk. Individual: {individual_score:.1f}, Cluster: {cluster_score:.1f}. '
                      f'Requesting lightweight verification.',
            'worker_message': 'We need a quick verification — please submit a photo of your current location.',
            'estimated_wait': '15 minutes',
            'verification_type': 'PHOTO_LOCATION',
        }

    else:
        return {
            'status': 'INVESTIGATE_HOLD',
            'reason': f'High risk. Individual: {individual_score:.1f}, Cluster: {cluster_score:.1f}. '
                      f'Held for analyst review. Cluster state: {cluster_state}.',
            'worker_message': 'Quick safety check in progress — estimated wait: 10 minutes.',
            'estimated_wait': '10 minutes',
        }


def update_cluster_state(city: str, zone: str, cluster_data: dict):
    """
    Update or create cluster record based on detection results.
    Implements stateMachine.mmd transitions.
    """
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM clusters WHERE city = ? AND zone = ? AND state != 'RESOLVED' AND state != 'BANNED'",
            (city, zone)
        ).fetchone()

        cluster_score = cluster_data['cluster_score']
        state = cluster_data['cluster_state']
        claim_count = cluster_data['claim_count']
        shared_fp = cluster_data['shared_fingerprints']
        cb = 1 if cluster_data['circuit_breaker'] else 0

        if existing:
            # Update existing cluster
            db.execute("""
                UPDATE clusters SET
                    state = ?, cluster_score = ?, claim_count = ?,
                    shared_fingerprints = ?, circuit_breaker_active = ?,
                    payout_throttled = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (state, cluster_score, claim_count, shared_fp, cb, cb, existing['id']))
            return existing['id']
        elif state != 'NORMAL':
            import uuid
            cluster_id = f"CLU-{uuid.uuid4().hex[:8].upper()}"
            db.execute("""
                INSERT INTO clusters (id, city, zone, state, cluster_score,
                    claim_count, shared_fingerprints, circuit_breaker_active, payout_throttled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cluster_id, city, zone, state, cluster_score,
                  claim_count, shared_fp, cb, cb))
            return cluster_id

    return None


def log_audit(event_type: str, entity_type: str, entity_id: str,
              actor: str = 'SYSTEM', details: dict = None):
    """Write immutable audit trail entry."""
    import json
    with get_db() as db:
        db.execute("""
            INSERT INTO audit_log (event_type, entity_type, entity_id, actor, details)
            VALUES (?, ?, ?, ?, ?)
        """, (event_type, entity_type, entity_id, actor,
              json.dumps(details) if details else None))


def update_worker_stats(worker_id: str, status: str):
    """Update worker statistics after claim decision."""
    with get_db() as db:
        db.execute("UPDATE workers SET total_claims = total_claims + 1, updated_at = datetime('now') WHERE id = ?",
                   (worker_id,))

        if status in ('AUTO_APPROVED', 'STEP_UP_APPROVED', 'ANALYST_APPROVED', 'APPEAL_APPROVED'):
            db.execute("""
                UPDATE workers SET
                    approved_claims = approved_claims + 1,
                    reliability_score = MIN(10, reliability_score + 0.1),
                    updated_at = datetime('now')
                WHERE id = ?
            """, (worker_id,))
        elif status in ('INVESTIGATE_HOLD', 'STEP_UP_REJECTED', 'ANALYST_REJECTED'):
            db.execute("""
                UPDATE workers SET
                    flagged_claims = flagged_claims + 1,
                    reliability_score = MAX(0, reliability_score - 0.3),
                    updated_at = datetime('now')
                WHERE id = ?
            """, (worker_id,))
