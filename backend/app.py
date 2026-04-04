"""
GigShield-AI — Main Application
Flask server with full REST API for parametric insurance fraud detection.
"""

import os
import sys
import json
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.database import init_db
from backend.routes.claims import claims_bp
from backend.routes.workers import workers_bp
from backend.routes.analytics import analytics_bp, clusters_bp, audit_bp
from backend.routes.simulation import simulation_bp


def create_app():
    app = Flask(__name__,
                static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'),
                static_url_path='')

    # ── CORS (manual since flask-cors not available) ─────────────────
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        if request.method == 'OPTIONS':
            response.status_code = 204
        return response

    # ── Register Blueprints ──────────────────────────────────────────
    app.register_blueprint(claims_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(clusters_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(simulation_bp)

    # ── Error Handlers ───────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

    # ── Health Check ─────────────────────────────────────────────────
    @app.route('/api/health', methods=['GET'])
    def health():
        from backend.database import get_db
        try:
            with get_db() as db:
                db.execute("SELECT 1")
            db_ok = True
        except:
            db_ok = False

        return jsonify({
            'status': 'healthy' if db_ok else 'degraded',
            'database': 'connected' if db_ok else 'error',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0',
            'service': 'GigShield-AI',
        })

    # ── API Index ────────────────────────────────────────────────────
    @app.route('/api', methods=['GET'])
    def api_index():
        return jsonify({
            'service': 'GigShield-AI API',
            'version': '1.0.0',
            'endpoints': {
                'health': 'GET /api/health',
                'claims': {
                    'list':   'GET    /api/claims',
                    'create': 'POST   /api/claims',
                    'get':    'GET    /api/claims/<id>',
                    'review': 'PATCH  /api/claims/<id>/review',
                    'appeal': 'POST   /api/claims/<id>/appeal',
                },
                'workers': {
                    'list':   'GET    /api/workers',
                    'create': 'POST   /api/workers',
                    'get':    'GET    /api/workers/<id>',
                    'update': 'PATCH  /api/workers/<id>',
                    'ban':    'POST   /api/workers/<id>/ban',
                    'unban':  'POST   /api/workers/<id>/unban',
                },
                'appeals': {
                    'resolve': 'PATCH /api/appeals/<id>/resolve',
                },
                'clusters': {
                    'list':    'GET   /api/clusters',
                    'get':     'GET   /api/clusters/<id>',
                    'resolve': 'PATCH /api/clusters/<id>/resolve',
                },
                'analytics': {
                    'dashboard':    'GET  /api/analytics/dashboard',
                    'risk_dist':    'GET  /api/analytics/risk-distribution',
                    'signals':      'GET  /api/analytics/signal-averages',
                    'throughput':   'GET  /api/analytics/throughput',
                },
                'weather': {
                    'list':   'GET  /api/weather',
                    'create': 'POST /api/weather',
                },
                'audit': {
                    'list': 'GET /api/audit',
                },
                'simulation': {
                    'single':  'POST /api/simulate/claim',
                    'batch':   'POST /api/simulate/batch',
                    'attack':  'POST /api/simulate/cluster-attack',
                    'reset':   'POST /api/simulate/reset',
                },
            },
        })

    # ── Serve Frontend ───────────────────────────────────────────────
    @app.route('/')
    def serve_frontend():
        return send_from_directory(app.static_folder, 'index.html')

    # Initialize database on startup
    with app.app_context():
        init_db()
        # Auto-seed if empty
        from backend.database import get_db as _get_db
        with _get_db() as _db:
            if _db.execute("SELECT COUNT(*) FROM workers").fetchone()[0] == 0:
                from scripts.seed import seed
                seed()

    return app


if __name__ == '__main__':
    app = create_app()
    print("\n" + "="*60)
    print("  GigShield-AI Server")
    print("  Forensic Device Intelligence · Parametric Fraud Defense")
    print("="*60)
    print(f"\n  🌐 Dashboard:  http://localhost:5000")
    print(f"  📡 API Index:  http://localhost:5000/api")
    print(f"  💚 Health:     http://localhost:5000/api/health")
    print(f"\n  Built for Guidewire DEVTrails 2026")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
