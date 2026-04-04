"""
Simulation API Routes
Generates realistic test claims for demo and testing.
Includes the coordinated 500-worker GPS spoofing attack scenario.
"""

from flask import Blueprint, request, jsonify
import random
import json
import uuid

from backend.database import get_db, rows_to_list
from backend.services.claim_processor import process_claim
from backend.services.decision_engine import log_audit

simulation_bp = Blueprint('simulation', __name__)

CITIES = {
    'Mumbai': {
        'lat': 19.076, 'lng': 72.877,
        'zones': ['Andheri', 'Bandra', 'Dadar', 'Borivali', 'Thane', 'Kurla']
    },
    'Delhi': {
        'lat': 28.613, 'lng': 77.209,
        'zones': ['Connaught Place', 'Dwarka', 'Rohini', 'Saket', 'Karol Bagh']
    },
    'Bangalore': {
        'lat': 12.971, 'lng': 77.594,
        'zones': ['Koramangala', 'Indiranagar', 'Whitefield', 'Jayanagar', 'HSR Layout']
    }
}

DISRUPTIONS = ['Heavy Rainfall', 'Flash Flood', 'Traffic Blackout', 'Road Collapse', 'Waterlogging']


def _rand(lo, hi):
    return random.uniform(lo, hi)


def _generate_legit_signals(city_data):
    return {
        'gps_lat': city_data['lat'] + _rand(-0.02, 0.02),
        'gps_lng': city_data['lng'] + _rand(-0.02, 0.02),
        'gps_accuracy': _rand(5, 25),
        'accelerometer_data': [round(_rand(-2, 2), 3) for _ in range(30)],
        'barometric_pressure': _rand(1005, 1015),
        'barometric_altitude': _rand(5, 50),
        'mock_location_on': False,
        'is_rooted': False,
        'is_emulator': False,
        'attestation_valid': True,
        'network_type': random.choice(['LTE', '4G', '5G', 'WIFI']),
        'ip_address': f"103.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
        'session_duration_sec': random.randint(120, 600),
    }


def _generate_fraud_signals(city_data, shared_ip=None):
    return {
        'gps_lat': city_data['lat'] + _rand(-0.005, 0.005),
        'gps_lng': city_data['lng'] + _rand(-0.005, 0.005),
        'gps_accuracy': _rand(0.5, 2),
        'accelerometer_data': [0.0] * 5,
        'barometric_pressure': _rand(1018, 1025),
        'barometric_altitude': _rand(0, 5),
        'mock_location_on': random.random() > 0.15,
        'is_rooted': random.random() > 0.5,
        'is_emulator': random.random() > 0.8,
        'attestation_valid': random.random() > 0.7,
        'network_type': 'LTE',
        'ip_address': shared_ip or f"45.{random.randint(1,255)}.{random.randint(1,10)}.{random.randint(1,255)}",
        'session_duration_sec': random.randint(5, 30),
    }


def _get_random_workers(limit=1):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, city, zone FROM workers WHERE is_banned = 0 ORDER BY RANDOM() LIMIT ?",
            (limit,)
        ).fetchall()
    return rows_to_list(rows)


def _process_one(worker, city_name, zone, is_fraud, shared_ip=None):
    city = CITIES.get(city_name, CITIES['Mumbai'])
    signals = _generate_fraud_signals(city, shared_ip) if is_fraud else _generate_legit_signals(city)

    try:
        return process_claim(
            worker_id=worker['id'],
            city=city_name,
            zone=zone,
            disruption_type=random.choice(DISRUPTIONS),
            amount=random.randint(200, 800),
            latitude=signals.get('gps_lat'),
            longitude=signals.get('gps_lng'),
            signals=signals,
        )
    except ValueError as e:
        return {'error': str(e), 'worker_id': worker['id']}


@simulation_bp.route('/api/simulate/claim', methods=['POST'])
def simulate_single_claim():
    data = request.get_json() or {}
    is_fraud = data.get('is_fraud', random.random() < 0.15)

    workers = _get_random_workers(1)
    if not workers:
        return jsonify({'error': 'No workers in database. Run seed first.'}), 400

    worker = workers[0]
    city_name = data.get('city', worker['city'])
    zone = data.get('zone', worker['zone'])

    result = _process_one(worker, city_name, zone, is_fraud)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result), 201


@simulation_bp.route('/api/simulate/batch', methods=['POST'])
def simulate_batch():
    data = request.get_json() or {}
    count = min(data.get('count', 10), 100)
    fraud_ratio = data.get('fraud_ratio', 0.15)

    workers = _get_random_workers(count)
    if not workers:
        return jsonify({'error': 'No workers. Run seed first.'}), 400

    results = []
    for i in range(count):
        is_fraud = random.random() < fraud_ratio
        worker = random.choice(workers)
        result = _process_one(worker, worker['city'], worker['zone'], is_fraud)
        results.append(result)

    summary = {
        'total': len(results),
        'auto_approved': sum(1 for r in results if r.get('status') == 'AUTO_APPROVED'),
        'step_up': sum(1 for r in results if r.get('status') == 'STEP_UP_VERIFICATION'),
        'held': sum(1 for r in results if r.get('status') == 'INVESTIGATE_HOLD'),
        'grace': sum(1 for r in results if r.get('status') == 'GRACE_QUEUED'),
    }

    return jsonify({'summary': summary, 'claims': results})


@simulation_bp.route('/api/simulate/cluster-attack', methods=['POST'])
def simulate_cluster_attack():
    data = request.get_json() or {}
    count = min(data.get('count', 20), 50)
    city_name = data.get('city', random.choice(list(CITIES.keys())))
    city = CITIES[city_name]
    zone = data.get('zone', random.choice(city['zones']))

    shared_ip = f"45.33.{random.randint(1,10)}.{random.randint(1,255)}"

    log_audit('CLUSTER_ATTACK_SIMULATED', 'SIMULATION', f'SIM-{uuid.uuid4().hex[:6]}',
              details={'city': city_name, 'zone': zone, 'count': count})

    workers = _get_random_workers(count)
    if len(workers) < 5:
        return jsonify({'error': 'Need at least 5 workers for attack simulation'}), 400

    results = []
    for worker in workers[:count]:
        result = _process_one(worker, city_name, zone, is_fraud=True, shared_ip=shared_ip)
        results.append(result)

    summary = {
        'attack_target': f'{zone}, {city_name}',
        'total_claims': len(results),
        'auto_approved': sum(1 for r in results if r.get('status') == 'AUTO_APPROVED'),
        'step_up': sum(1 for r in results if r.get('status') == 'STEP_UP_VERIFICATION'),
        'held': sum(1 for r in results if r.get('status') == 'INVESTIGATE_HOLD'),
        'circuit_breaker_triggered': any(r.get('circuit_breaker') for r in results),
        'max_cluster_score': max((r.get('cluster_score', 0) for r in results), default=0),
        'amount_saved': sum(r.get('amount', 0) for r in results
                           if r.get('status') == 'INVESTIGATE_HOLD'),
    }

    return jsonify({'summary': summary, 'claims': results})


@simulation_bp.route('/api/simulate/reset', methods=['POST'])
def reset_simulation():
    with get_db() as db:
        db.execute("DELETE FROM claim_signals")
        db.execute("DELETE FROM grace_queue")
        db.execute("DELETE FROM appeals")
        db.execute("DELETE FROM audit_log")
        db.execute("DELETE FROM clusters")
        db.execute("DELETE FROM retraining_log")
        db.execute("DELETE FROM claims")
        db.execute("""
            UPDATE workers SET total_claims = 0, approved_claims = 0,
                flagged_claims = 0, reliability_score = 5.0, is_banned = 0,
                updated_at = datetime('now')
        """)
    return jsonify({'reset': True})
