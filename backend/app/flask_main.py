"""Volunteer Map - Flask version with live static file serving (no cache)."""
import os
import html
import sqlite3
import datetime
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'organizations.db')
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), 'frontend')

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path='')
CORS(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def generate_popup(org):
    """Generate popup HTML for a marker. Full description with scrollable container."""
    parts = ['<strong>' + html.escape(org['name']) + '</strong><br>']
    if org['description'] and len(org['description']) > 10:
        desc = html.escape(org['description'])
        parts.append(
            '<p style="max-height:200px;overflow-y:auto;font-size:12px;line-height:1.4;">' + desc + '</p>'
        )
    badges = []
    if org['accepts_volunteers']:
        badges.append('<span style="background:#ffc107;color:black;padding:2px 6px;border-radius:3px;margin:1px;">Volunteer</span>')
    if org['accepts_visitors']:
        if org['accepts_shortterm']:
            badges.append('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Short-term</span>')
        if org['accepts_longterm']:
            badges.append('<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Long-term</span>')
    if org['has_jobs']:
        badges.append('<span style="background:#dc3545;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Jobs</span>')
    if badges:
        parts.append(' '.join(badges) + '<br>')
    
    # Show address if available
    if org.get('address'):
        addr = html.escape(str(org['address']))
        parts.append('<div style="margin:4px 0;font-size:11px;color:#555;\"><i class=\"fas fa-map-marker-alt\" style=\"color:#e74c3c;\"></i> ' + addr[:150] + '</div>')
    
    lines = []
    if org.get('city') or org.get('region') or org.get('country'):
        location_parts = []
        if org.get('city'):
            location_parts.append(html.escape(str(org['city'])))
        if org.get('region'):
            location_parts.append(html.escape(str(org['region'])))
        if org.get('country'):
            location_parts.append(html.escape(str(org['country'])))
        parts.append('<div style="margin:2px 0;font-size:11px;color:#666;font-style:italic;\">' + ', '.join(location_parts) + '</div>')
    
    lines = []
    if org.get('website'):
        lines.append('<a href=\"' + html.escape(org['website']) + '\" target=\"_blank\" style=\"color:#007bff;text-decoration:none;\">Website</a>')
    if org['email']:
        lines.append('<a href="mailto:' + html.escape(org['email']) + '" style="color:#007bff;">Email</a>')
    if org['phone']:
        lines.append(html.escape(org['phone']))
    if lines:
        parts.append('<div style="margin:4px 0;">' + ' | '.join(lines) + '</div>')
    return ' '.join(parts)


# ---------------------------------------------------------------------------
# Static files (Flask send_from_directory = instant updates, no cache)
# ---------------------------------------------------------------------------

@app.route('/')
def root():
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/<path:path>')
def static_files(path):
    resp = send_from_directory(FRONTEND_DIR, path)
    # Force no caching for instant reflection of changes
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route('/api/organizations/geojson/')
def organizations_geojson():
    source = request.args.get('source')
    accepts_volunteers = request.args.get('accepts_volunteers')
    accepts_visitors = request.args.get('accepts_visitors')
    accepts_shortterm = request.args.get('accepts_shortterm')
    accepts_longterm = request.args.get('accepts_longterm')
    has_jobs = request.args.get('has_jobs')

    query = """
        SELECT id, name, description, website, email, phone,
               address, city, region, country, postal_code,
               latitude, longitude, location, source,
               accepts_volunteers, accepts_visitors, accepts_shortterm, accepts_longterm,
               has_jobs,
               popup_html
        FROM organizations
        WHERE (latitude IS NOT NULL AND longitude IS NOT NULL) OR (address IS NOT NULL AND address != '')
    """
    params = []

    if source:
        query += " AND source = ?"
        params.append(source)
    if accepts_volunteers is not None:
        query += " AND accepts_volunteers = ?"
        params.append(1 if accepts_volunteers.lower() in ('true', '1') else 0)
    if accepts_visitors is not None:
        query += " AND accepts_visitors = ?"
        params.append(1 if accepts_visitors.lower() in ('true', '1') else 0)
    if accepts_shortterm is not None:
        query += " AND accepts_shortterm = ?"
        params.append(1 if accepts_shortterm.lower() in ('true', '1') else 0)
    if accepts_longterm is not None:
        query += " AND accepts_longterm = ?"
        params.append(1 if accepts_longterm.lower() in ('true', '1') else 0)
    if has_jobs is not None:
        query += " AND has_jobs = ?"
        params.append(1 if has_jobs.lower() in ('true', '1') else 0)

    conn = get_db()
    orgs = conn.execute(query, params).fetchall()
    conn.close()

    features = []
    for org in orgs:
        org_dict = dict(org)
        phtml = org_dict.get('popup_html') or ''
        popup_html = phtml if phtml else generate_popup(org_dict)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [org_dict['longitude'], org_dict['latitude']]
            },
            "properties": {
                "id": org_dict['id'],
                "name": org_dict['name'],
                "description": org_dict.get('description', '') or "",
                "address": org_dict.get('address', '') or "",
                "city": org_dict.get('city', '') or "",
                "region": org_dict.get('region', '') or "",
                "popup": popup_html,
                "source": org_dict.get('source', ''),
                "country": org_dict.get('country', '') or "",
                "website": org_dict.get('website', '') or "",
                "acceptsVolunteers": bool(org_dict.get('accepts_volunteers')),
                "acceptsVisitors": bool(org_dict.get('accepts_visitors')),
                "acceptsShortterm": bool(org_dict.get('accepts_shortterm')),
                "acceptsLongterm": bool(org_dict.get('accepts_longterm')),
                "hasJobs": bool(org_dict.get('has_jobs'))
            }
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": features
    })


@app.route('/api/organizations/')
def read_organizations():
    source = request.args.get('source')
    accepts_volunteers = request.args.get('accepts_volunteers')
    accepts_visitors = request.args.get('accepts_visitors')
    accepts_shortterm = request.args.get('accepts_shortterm')
    accepts_longterm = request.args.get('accepts_longterm')
    has_jobs = request.args.get('has_jobs')
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)

    query = "SELECT * FROM organizations"
    params = []
    conditions = []
    if source:
        conditions.append("source = ?")
        params.append(source)
    if accepts_volunteers is not None:
        conditions.append("accepts_volunteers = ?")
        params.append(1 if accepts_volunteers.lower() in ('true', '1') else 0)
    if accepts_visitors is not None:
        conditions.append("accepts_visitors = ?")
        params.append(1 if accepts_visitors.lower() in ('true', '1') else 0)
    if accepts_shortterm is not None:
        conditions.append("accepts_shortterm = ?")
        params.append(1 if accepts_shortterm.lower() in ('true', '1') else 0)
    if accepts_longterm is not None:
        conditions.append("accepts_longterm = ?")
        params.append(1 if accepts_longterm.lower() in ('true', '1') else 0)
    if has_jobs is not None:
        conditions.append("has_jobs = ?")
        params.append(1 if has_jobs.lower() in ('true', '1') else 0)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, skip])

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])


@app.route('/api/organizations/<int:org_id>')
def read_organization(org_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.route('/api/statistics/')
def get_statistics():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    volunteers = conn.execute("SELECT COUNT(*) FROM organizations WHERE accepts_volunteers = 1").fetchone()[0]
    visitors = conn.execute("SELECT COUNT(*) FROM organizations WHERE accepts_visitors = 1").fetchone()[0]
    shortterm = conn.execute("SELECT COUNT(*) FROM organizations WHERE accepts_shortterm = 1").fetchone()[0]
    longterm = conn.execute("SELECT COUNT(*) FROM organizations WHERE accepts_longterm = 1").fetchone()[0]
    jobs = conn.execute("SELECT COUNT(*) FROM organizations WHERE has_jobs = 1").fetchone()[0]

    sources = conn.execute("SELECT source, COUNT(*) FROM organizations GROUP BY source").fetchall()
    countries = conn.execute("SELECT country, COUNT(*) FROM organizations WHERE country IS NOT NULL GROUP BY country").fetchall()
    conn.close()

    return jsonify({
        "total_organizations": total,
        "total_opportunities": 0,
        "by_source": {r['source']: r[1] for r in sources},
        "by_country": {r['country']: r[1] for r in countries},
        "feature_counts": {
            "accepts_volunteers": volunteers,
            "accepts_visitors": visitors,
            "accepts_shortterm": shortterm,
            "accepts_longterm": longterm,
            "has_jobs": jobs
        }
    })


@app.route('/api/healthz')
def health_check():
    return jsonify({"status": "healthy", "service": "volunteer-map-flask", "version": "2.0.0"})


@app.route('/api-info/')
def api_info():
    return jsonify({
        "message": "Volunteer Map HTTP Server",
        "version": "2.0.0",
        "endpoints": {
            "organizations": {
                "list": "GET /api/organizations/",
                "geojson": "GET /api/organizations/geojson/",
                "read": "GET /api/organizations/{id}",
            },
            "stats": "GET /api/statistics/",
            "health": "GET /api/healthz",
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
