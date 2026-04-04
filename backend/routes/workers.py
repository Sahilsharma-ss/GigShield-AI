"""
Workers API Routes
"""

from flask import Blueprint, request, jsonify
import uuid
from backend.database import get_db, dict_from_row, rows_to_list
from backend.services.decision_engine import log_audit

workers_bp = Blueprint('workers', __name__)


@workers_bp.route('/api/workers', methods=['POST'])
def create_worker():
    data = request.get_json()
    worker_id = f"WRK-{uuid.uuid4().hex[:8].upper()}"

    with get_db() as db:
        db.execute("""
            INSERT INTO workers (id, name, phone, city, zone)
            VALUES (?, ?, ?, ?, ?)
        """, (worker_id, data['name'], data.get('phone'),
              data['city'], data['zone']))

    log_audit('WORKER_CREATED', 'WORKER', worker_id, details={'name': data['name']})
    return jsonify({'id': worker_id, 'name': data['name']}), 201


@workers_bp.route('/api/workers', methods=['GET'])
def list_workers():
    city = request.args.get('city')
    zone = request.args.get('zone')
    banned = request.args.get('banned')
    sort = request.args.get('sort', 'reliability_score')
    order = request.args.get('order', 'DESC')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    query = "SELECT * FROM workers WHERE 1=1"
    params = []

    if city:
        query += " AND city = ?"
        params.append(city)
    if zone:
        query += " AND zone = ?"
        params.append(zone)
    if banned is not None:
        query += " AND is_banned = ?"
        params.append(1 if banned == 'true' else 0)

    allowed_sorts = ['reliability_score', 'total_claims', 'flagged_claims', 'created_at', 'name']
    if sort in allowed_sorts:
        query += f" ORDER BY {sort} {order}"

    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM workers", []).fetchone()[0]
        rows = db.execute(query, params).fetchall()

    return jsonify({'workers': rows_to_list(rows), 'total': total})


@workers_bp.route('/api/workers/<worker_id>', methods=['GET'])
def get_worker(worker_id):
    with get_db() as db:
        worker = dict_from_row(db.execute(
            "SELECT * FROM workers WHERE id = ?", (worker_id,)
        ).fetchone())

        if not worker:
            return jsonify({'error': 'Worker not found'}), 404

        recent_claims = rows_to_list(db.execute("""
            SELECT id, status, individual_score, cluster_score,
                   disruption_type, amount, created_at
            FROM claims WHERE worker_id = ?
            ORDER BY created_at DESC LIMIT 20
        """, (worker_id,)).fetchall())

    return jsonify({'worker': worker, 'recent_claims': recent_claims})


@workers_bp.route('/api/workers/<worker_id>', methods=['PATCH'])
def update_worker(worker_id):
    data = request.get_json()
    allowed = ['name', 'phone', 'city', 'zone']
    updates = {k: v for k, v in data.items() if k in allowed}

    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [worker_id]

    with get_db() as db:
        db.execute(
            f"UPDATE workers SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            values
        )

    return jsonify({'updated': True})


@workers_bp.route('/api/workers/<worker_id>/ban', methods=['POST'])
def ban_worker(worker_id):
    data = request.get_json() or {}
    with get_db() as db:
        db.execute(
            "UPDATE workers SET is_banned = 1, updated_at = datetime('now') WHERE id = ?",
            (worker_id,)
        )
    log_audit('WORKER_BANNED', 'WORKER', worker_id,
              actor=data.get('analyst', 'SYSTEM'),
              details={'reason': data.get('reason', 'Fraud confirmed')})
    return jsonify({'banned': True})


@workers_bp.route('/api/workers/<worker_id>/unban', methods=['POST'])
def unban_worker(worker_id):
    with get_db() as db:
        db.execute(
            "UPDATE workers SET is_banned = 0, reliability_score = 3.0, updated_at = datetime('now') WHERE id = ?",
            (worker_id,)
        )
    log_audit('WORKER_UNBANNED', 'WORKER', worker_id)
    return jsonify({'unbanned': True})
