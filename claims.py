"""
Claims API Routes
Handles the full claim lifecycle: submit → ingest → score → decide → payout/hold.
"""

from flask import Blueprint, request, jsonify
import uuid
import json
from datetime import datetime

from backend.database import get_db, dict_from_row, rows_to_list
from backend.services.claim_processor import process_claim
from backend.services.decision_engine import log_audit, update_worker_stats

claims_bp = Blueprint('claims', __name__)


# ─── POST /api/claims — Submit a new claim ──────────────────────────
@claims_bp.route('/api/claims', methods=['POST'])
def submit_claim():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    worker_id = data.get('worker_id')
    if not worker_id:
        return jsonify({'error': 'worker_id required'}), 400

    try:
        result = process_claim(
            worker_id=worker_id,
            city=data.get('city', ''),
            zone=data.get('zone', ''),
            disruption_type=data.get('disruption_type', 'Heavy Rainfall'),
            amount=data.get('amount', 500),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            signals=data.get('signals', {}),
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ─── GET /api/claims — List claims with filters ─────────────────────
@claims_bp.route('/api/claims', methods=['GET'])
def list_claims():
    status = request.args.get('status')
    worker_id = request.args.get('worker_id')
    city = request.args.get('city')
    zone = request.args.get('zone')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    query = """
        SELECT c.*, w.name as worker_name,
               cs.movement_continuity, cs.device_integrity,
               cs.environmental_match, cs.historical_reliability,
               cs.behavioral_anomaly, cs.mock_location_on, cs.is_rooted
        FROM claims c
        LEFT JOIN workers w ON w.id = c.worker_id
        LEFT JOIN claim_signals cs ON cs.claim_id = c.id
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND c.status = ?"
        params.append(status)
    if worker_id:
        query += " AND c.worker_id = ?"
        params.append(worker_id)
    if city:
        query += " AND c.city = ?"
        params.append(city)
    if zone:
        query += " AND c.zone = ?"
        params.append(zone)

    # Count total
    count_query = query.replace(
        "SELECT c.*, w.name as worker_name,\n               cs.movement_continuity, cs.device_integrity,\n               cs.environmental_match, cs.historical_reliability,\n               cs.behavioral_anomaly, cs.mock_location_on, cs.is_rooted",
        "SELECT COUNT(*)"
    )

    query += " ORDER BY c.created_at DESC LIMIT ? OFFSET ?"
    params_with_limit = params + [limit, offset]

    with get_db() as db:
        total = db.execute(count_query, params).fetchone()[0]
        rows = db.execute(query, params_with_limit).fetchall()

    return jsonify({
        'claims': rows_to_list(rows),
        'total': total,
        'limit': limit,
        'offset': offset,
    })


# ─── GET /api/claims/<id> — Get claim detail ────────────────────────
@claims_bp.route('/api/claims/<claim_id>', methods=['GET'])
def get_claim(claim_id):
    with get_db() as db:
        claim = dict_from_row(db.execute("""
            SELECT c.*, w.name as worker_name, w.reliability_score,
                   w.total_claims as worker_total_claims
            FROM claims c
            LEFT JOIN workers w ON w.id = c.worker_id
            WHERE c.id = ?
        """, (claim_id,)).fetchone())

        if not claim:
            return jsonify({'error': 'Claim not found'}), 404

        signals = dict_from_row(db.execute(
            "SELECT * FROM claim_signals WHERE claim_id = ?", (claim_id,)
        ).fetchone())

        audit = rows_to_list(db.execute(
            "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY created_at DESC",
            (claim_id,)
        ).fetchall())

    return jsonify({
        'claim': claim,
        'signals': signals,
        'audit_trail': audit,
    })


# ─── PATCH /api/claims/<id>/review — Analyst review ─────────────────
@claims_bp.route('/api/claims/<claim_id>/review', methods=['PATCH'])
def review_claim(claim_id):
    data = request.get_json()
    action = data.get('action')  # 'approve' or 'reject'
    analyst = data.get('analyst', 'analyst-001')
    notes = data.get('notes', '')

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action must be approve or reject'}), 400

    with get_db() as db:
        claim = dict_from_row(db.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone())

        if not claim:
            return jsonify({'error': 'Claim not found'}), 404

        if claim['status'] not in ('INVESTIGATE_HOLD', 'STEP_UP_VERIFICATION'):
            return jsonify({'error': f'Cannot review claim in status: {claim["status"]}'}), 400

        new_status = 'ANALYST_APPROVED' if action == 'approve' else 'ANALYST_REJECTED'
        payout_at = datetime.now().isoformat() if action == 'approve' else None

        db.execute("""
            UPDATE claims SET status = ?, decision_reason = ?,
                payout_at = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (new_status, f"Analyst {analyst}: {notes}", payout_at, claim_id))

    log_audit(new_status, 'CLAIM', claim_id, analyst, {'notes': notes, 'action': action})
    update_worker_stats(claim['worker_id'], new_status)

    return jsonify({'claim_id': claim_id, 'status': new_status})


# ─── POST /api/claims/<id>/appeal — Worker appeal ───────────────────
@claims_bp.route('/api/claims/<claim_id>/appeal', methods=['POST'])
def appeal_claim(claim_id):
    data = request.get_json()

    with get_db() as db:
        claim = dict_from_row(db.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone())

        if not claim:
            return jsonify({'error': 'Claim not found'}), 404

        if claim['status'] not in ('ANALYST_REJECTED', 'STEP_UP_REJECTED', 'INVESTIGATE_HOLD'):
            return jsonify({'error': 'Claim cannot be appealed in current status'}), 400

        appeal_id = f"APL-{uuid.uuid4().hex[:8].upper()}"
        db.execute("""
            INSERT INTO appeals (id, claim_id, worker_id, reason, evidence)
            VALUES (?, ?, ?, ?, ?)
        """, (appeal_id, claim_id, claim['worker_id'],
              data.get('reason', ''), json.dumps(data.get('evidence', []))))

        db.execute(
            "UPDATE claims SET status = 'APPEALED', updated_at = datetime('now') WHERE id = ?",
            (claim_id,)
        )

    log_audit('APPEAL_SUBMITTED', 'CLAIM', claim_id, claim['worker_id'],
              {'appeal_id': appeal_id, 'reason': data.get('reason')})

    return jsonify({'appeal_id': appeal_id, 'status': 'PENDING'}), 201


# ─── PATCH /api/appeals/<id>/resolve ─────────────────────────────────
@claims_bp.route('/api/appeals/<appeal_id>/resolve', methods=['PATCH'])
def resolve_appeal(appeal_id):
    data = request.get_json()
    action = data.get('action')  # 'approve' or 'reject'

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action must be approve or reject'}), 400

    with get_db() as db:
        appeal = dict_from_row(db.execute(
            "SELECT * FROM appeals WHERE id = ?", (appeal_id,)
        ).fetchone())

        if not appeal:
            return jsonify({'error': 'Appeal not found'}), 404

        new_appeal_status = 'APPROVED' if action == 'approve' else 'REJECTED'
        new_claim_status = 'APPEAL_APPROVED' if action == 'approve' else 'APPEAL_REJECTED'

        db.execute("""
            UPDATE appeals SET status = ?, reviewer_notes = ?,
                resolved_at = datetime('now') WHERE id = ?
        """, (new_appeal_status, data.get('notes', ''), appeal_id))

        db.execute("""
            UPDATE claims SET status = ?, updated_at = datetime('now') WHERE id = ?
        """, (new_claim_status, appeal['claim_id']))

    # If appeal approved, trigger model retraining
    if action == 'approve':
        with get_db() as db:
            db.execute("""
                INSERT INTO retraining_log (trigger_type, trigger_id, samples_added, notes)
                VALUES ('APPEAL_APPROVED', ?, 1, 'False positive corrected via appeal')
            """, (appeal_id,))

    log_audit(f'APPEAL_{new_appeal_status}', 'APPEAL', appeal_id,
              data.get('reviewer', 'SYSTEM'), {'claim_id': appeal['claim_id']})

    update_worker_stats(appeal['worker_id'], new_claim_status)

    return jsonify({'appeal_id': appeal_id, 'status': new_appeal_status})
