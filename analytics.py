"""
Analytics, Clusters, and Audit API Routes
"""

from flask import Blueprint, request, jsonify
from backend.database import get_db, dict_from_row, rows_to_list
from backend.services.decision_engine import log_audit

analytics_bp = Blueprint('analytics', __name__)
clusters_bp = Blueprint('clusters', __name__)
audit_bp = Blueprint('audit', __name__)


# ═════════════════════════════════════════════════════════════════════
# ANALYTICS / DASHBOARD
# ═════════════════════════════════════════════════════════════════════

@analytics_bp.route('/api/analytics/dashboard', methods=['GET'])
def dashboard():
    """Main dashboard stats."""
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        approved = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status IN ('AUTO_APPROVED','STEP_UP_APPROVED','ANALYST_APPROVED','APPEAL_APPROVED')"
        ).fetchone()[0]
        step_up = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status = 'STEP_UP_VERIFICATION'"
        ).fetchone()[0]
        held = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status = 'INVESTIGATE_HOLD'"
        ).fetchone()[0]
        rejected = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status IN ('ANALYST_REJECTED','STEP_UP_REJECTED','APPEAL_REJECTED')"
        ).fetchone()[0]
        grace = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status = 'GRACE_QUEUED'"
        ).fetchone()[0]
        appealed = db.execute(
            "SELECT COUNT(*) FROM claims WHERE status = 'APPEALED'"
        ).fetchone()[0]

        # Amount calculations
        total_amount = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM claims"
        ).fetchone()[0]
        approved_amount = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM claims WHERE status IN ('AUTO_APPROVED','STEP_UP_APPROVED','ANALYST_APPROVED','APPEAL_APPROVED')"
        ).fetchone()[0]
        saved_amount = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM claims WHERE status IN ('INVESTIGATE_HOLD','ANALYST_REJECTED','STEP_UP_REJECTED','APPEAL_REJECTED')"
        ).fetchone()[0]

        # Avg scores
        avg_individual = db.execute(
            "SELECT COALESCE(AVG(individual_score), 0) FROM claims WHERE individual_score IS NOT NULL"
        ).fetchone()[0]
        avg_cluster = db.execute(
            "SELECT COALESCE(AVG(cluster_score), 0) FROM claims WHERE cluster_score IS NOT NULL"
        ).fetchone()[0]
        max_cluster = db.execute(
            "SELECT COALESCE(MAX(cluster_score), 0) FROM claims"
        ).fetchone()[0]

        # Active clusters
        active_clusters = db.execute(
            "SELECT COUNT(*) FROM clusters WHERE state NOT IN ('RESOLVED','BANNED','NORMAL')"
        ).fetchone()[0]

        # Workers
        total_workers = db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
        banned_workers = db.execute("SELECT COUNT(*) FROM workers WHERE is_banned = 1").fetchone()[0]

        # Recent claims per status for sparkline
        recent_by_status = rows_to_list(db.execute("""
            SELECT status, COUNT(*) as count
            FROM claims
            WHERE created_at >= datetime('now', '-1 hour')
            GROUP BY status
        """).fetchall())

        # Claims per city
        by_city = rows_to_list(db.execute("""
            SELECT city, COUNT(*) as count,
                   AVG(individual_score) as avg_score
            FROM claims GROUP BY city
        """).fetchall())

    return jsonify({
        'claims': {
            'total': total,
            'approved': approved,
            'step_up': step_up,
            'held': held,
            'rejected': rejected,
            'grace_queued': grace,
            'appealed': appealed,
        },
        'amounts': {
            'total_claimed': round(total_amount, 2),
            'total_approved': round(approved_amount, 2),
            'total_saved': round(saved_amount, 2),
        },
        'scores': {
            'avg_individual': round(avg_individual, 2),
            'avg_cluster': round(avg_cluster, 2),
            'max_cluster': round(max_cluster, 2),
        },
        'clusters': {
            'active': active_clusters,
        },
        'workers': {
            'total': total_workers,
            'banned': banned_workers,
        },
        'recent_by_status': recent_by_status,
        'by_city': by_city,
    })


@analytics_bp.route('/api/analytics/risk-distribution', methods=['GET'])
def risk_distribution():
    """Risk score distribution for histogram."""
    with get_db() as db:
        rows = rows_to_list(db.execute("""
            SELECT
                CASE
                    WHEN individual_score < 1 THEN '0-1'
                    WHEN individual_score < 2 THEN '1-2'
                    WHEN individual_score < 3 THEN '2-3'
                    WHEN individual_score < 4 THEN '3-4'
                    WHEN individual_score < 5 THEN '4-5'
                    WHEN individual_score < 6 THEN '5-6'
                    WHEN individual_score < 7 THEN '6-7'
                    WHEN individual_score < 8 THEN '7-8'
                    WHEN individual_score < 9 THEN '8-9'
                    ELSE '9-10'
                END as bucket,
                COUNT(*) as count
            FROM claims
            WHERE individual_score IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
        """).fetchall())
    return jsonify({'distribution': rows})


@analytics_bp.route('/api/analytics/signal-averages', methods=['GET'])
def signal_averages():
    """Average signal scores across all claims."""
    with get_db() as db:
        row = dict_from_row(db.execute("""
            SELECT
                ROUND(AVG(movement_continuity), 2) as avg_movement,
                ROUND(AVG(device_integrity), 2) as avg_device,
                ROUND(AVG(environmental_match), 2) as avg_environment,
                ROUND(AVG(historical_reliability), 2) as avg_historical,
                ROUND(AVG(behavioral_anomaly), 2) as avg_behavioral
            FROM claim_signals
        """).fetchone())
    return jsonify(row or {})


@analytics_bp.route('/api/analytics/throughput', methods=['GET'])
def throughput():
    """Claims per minute over last hour."""
    with get_db() as db:
        rows = rows_to_list(db.execute("""
            SELECT
                strftime('%H:%M', created_at) as minute,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'AUTO_APPROVED' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status = 'STEP_UP_VERIFICATION' THEN 1 ELSE 0 END) as step_up,
                SUM(CASE WHEN status = 'INVESTIGATE_HOLD' THEN 1 ELSE 0 END) as held
            FROM claims
            WHERE created_at >= datetime('now', '-1 hour')
            GROUP BY minute
            ORDER BY minute
        """).fetchall())
    return jsonify({'throughput': rows})


# ═════════════════════════════════════════════════════════════════════
# CLUSTERS
# ═════════════════════════════════════════════════════════════════════

@clusters_bp.route('/api/clusters', methods=['GET'])
def list_clusters():
    state = request.args.get('state')
    query = "SELECT * FROM clusters WHERE 1=1"
    params = []
    if state:
        query += " AND state = ?"
        params.append(state)
    query += " ORDER BY updated_at DESC LIMIT 50"

    with get_db() as db:
        rows = rows_to_list(db.execute(query, params).fetchall())
    return jsonify({'clusters': rows})


@clusters_bp.route('/api/clusters/<cluster_id>', methods=['GET'])
def get_cluster(cluster_id):
    with get_db() as db:
        cluster = dict_from_row(db.execute(
            "SELECT * FROM clusters WHERE id = ?", (cluster_id,)
        ).fetchone())

        if not cluster:
            return jsonify({'error': 'Cluster not found'}), 404

        claims = rows_to_list(db.execute("""
            SELECT c.*, w.name as worker_name,
                   cs.mock_location_on, cs.ip_address
            FROM claims c
            LEFT JOIN workers w ON w.id = c.worker_id
            LEFT JOIN claim_signals cs ON cs.claim_id = c.id
            WHERE c.cluster_id = ?
            ORDER BY c.created_at DESC
        """, (cluster_id,)).fetchall())

    return jsonify({'cluster': cluster, 'claims': claims})


@clusters_bp.route('/api/clusters/<cluster_id>/resolve', methods=['PATCH'])
def resolve_cluster(cluster_id):
    data = request.get_json() or {}
    action = data.get('action', 'resolve')  # 'resolve' or 'ban'
    analyst = data.get('analyst', 'analyst-001')

    new_state = 'BANNED' if action == 'ban' else 'RESOLVED'

    with get_db() as db:
        db.execute("""
            UPDATE clusters SET state = ?, analyst_id = ?, notes = ?,
                circuit_breaker_active = 0, payout_throttled = 0,
                resolved_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
        """, (new_state, analyst, data.get('notes', ''), cluster_id))

        # If banning, ban all workers in the cluster
        if action == 'ban':
            db.execute("""
                UPDATE workers SET is_banned = 1, updated_at = datetime('now')
                WHERE id IN (
                    SELECT DISTINCT worker_id FROM claims WHERE cluster_id = ?
                    AND individual_score > 6.0
                )
            """, (cluster_id,))

    log_audit(f'CLUSTER_{new_state}', 'CLUSTER', cluster_id, analyst,
              {'action': action, 'notes': data.get('notes')})

    # Trigger model retraining
    if action == 'ban':
        with get_db() as db:
            db.execute("""
                INSERT INTO retraining_log (trigger_type, trigger_id, notes)
                VALUES ('CLUSTER_BANNED', ?, 'Fraud ring confirmed, retraining with new samples')
            """, (cluster_id,))

    return jsonify({'cluster_id': cluster_id, 'state': new_state})


# ═════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═════════════════════════════════════════════════════════════════════

@audit_bp.route('/api/audit', methods=['GET'])
def list_audit():
    event_type = request.args.get('event_type')
    entity_type = request.args.get('entity_type')
    entity_id = request.args.get('entity_id')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if entity_type:
        query += " AND entity_type = ?"
        params.append(entity_type)
    if entity_id:
        query += " AND entity_id = ?"
        params.append(entity_id)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        rows = rows_to_list(db.execute(query, params).fetchall())

    return jsonify({'logs': rows, 'total': total})


# ═════════════════════════════════════════════════════════════════════
# WEATHER DATA (admin)
# ═════════════════════════════════════════════════════════════════════

@analytics_bp.route('/api/weather', methods=['GET'])
def list_weather():
    with get_db() as db:
        rows = rows_to_list(db.execute(
            "SELECT * FROM weather_data WHERE is_active = 1 ORDER BY fetched_at DESC"
        ).fetchall())
    return jsonify({'weather': rows})


@analytics_bp.route('/api/weather', methods=['POST'])
def add_weather():
    data = request.get_json()
    with get_db() as db:
        db.execute("""
            INSERT INTO weather_data (city, zone, disruption_type, severity, rainfall_mm, wind_speed_kmh)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data['city'], data['zone'], data.get('disruption_type'),
              data.get('severity', 5), data.get('rainfall_mm', 20),
              data.get('wind_speed_kmh', 30)))
    return jsonify({'created': True}), 201
