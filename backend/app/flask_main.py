"""Volunteer Map - Flask version with live static file serving (no cache)."""
import os
import html
import sqlite3
import json
import re
import time
from collections import defaultdict
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
# Rate limiter (simple in-memory sliding window)
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10
_rate_store = defaultdict(list)

def rate_limit(ip):
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_store[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def sanitize_text(text):
    if not text:
        return ''
    text = str(text).strip()
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'(?i)\\bjavascript\\s*:', '', text)
    text = re.sub(r'(?i)\\bdata\\s*:', '', text)
    return text[:2000]


def validate_url(url):
    if not url or not url.strip():
        return ''
    url = url.strip()[:500]
    if not re.match(r'^https?://', url):
        return ''
    blocked = ['<script', 'javascript:', 'data:', 'vbscript:', 'file:', 'ftp:']
    for b in blocked:
        if b in url.lower():
            return ''
    return url


def get_client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(self), camera=(), microphone=()'
    return response


from app.semantic_engine import get_engine as get_semantic_engine, build_search_text

# Initialize semantic search engine
print("Loading semantic search engine (bi-encoder + cross-encoder)...")
SEMANTIC_ENGINE = get_semantic_engine()
print(f"✓ Semantic search ready with cross-encoder re-ranking")

# Ensure enrichment table exists with full schema
def init_enrichment_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ip_enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT UNIQUE,
                enriched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                country TEXT, country_code TEXT, region TEXT, region_name TEXT,
                city TEXT, zip TEXT, lat REAL, lon REAL, timezone TEXT,
                isp TEXT, org TEXT, as_number TEXT, reverse_dns TEXT,
                mobile BOOLEAN, proxy BOOLEAN, hosting BOOLEAN,
                vt_as_owner TEXT, vt_continent TEXT, vt_network TEXT,
                vt_registry TEXT, vt_reputation INTEGER, vt_harmless_votes INTEGER,
                vt_malicious_votes INTEGER, vt_last_analysis_date TEXT,
                vt_whois TEXT, vt_jarm TEXT, vt_tags TEXT, vt_detection_samples TEXT,
                sf_whois_org TEXT, sf_whois_netrange TEXT, sf_blacklist TEXT,
                sf_open_ports TEXT, sf_hosting_provider TEXT, sf_reverse_domains TEXT,
                sf_proxy_vpn TEXT, sf_ssl_cert TEXT, sf_reputation_risk TEXT,
                sf_bgp_asn TEXT, sf_bgp_cidr TEXT, sf_threat_scores TEXT,
                th_reverse_dns TEXT, th_virtual_hosts TEXT, th_dns_servers TEXT,
                th_open_ports TEXT, th_associated_urls TEXT, th_banners TEXT,
                th_emails TEXT, th_social_media TEXT,
                th_entity_description TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass

init_enrichment_db()


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
    
    if org.get('address'):
        addr = html.escape(str(org['address']))
        parts.append('<div style="margin:4px 0;font-size:11px;color:#555;\\"><i class=\\"fas fa-map-marker-alt\\" style=\\"color:#e74c3c;\\"></i> ' + addr[:150] + '</div>')
    
    lines = []
    if org.get('city') or org.get('region') or org.get('country'):
        location_parts = []
        if org.get('city'):
            location_parts.append(html.escape(str(org['city'])))
        if org.get('region'):
            location_parts.append(html.escape(str(org['region'])))
        if org.get('country'):
            location_parts.append(html.escape(str(org['country'])))
        parts.append('<div style="margin:2px 0;font-size:11px;color:#666;font-style:italic;\\">' + ', '.join(location_parts) + '</div>')
    
    lines = []
    if org.get('website'):
        lines.append('<a href=\\"' + html.escape(org['website']) + '\\" target=\\"_blank\\" style=\\"color:#007bff;text-decoration:none;\\">Website</a>')
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
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 100, type=int)

    query = "SELECT * FROM organizations"
    params = []
    conditions = []
    if source:
        conditions.append("source = ?")
        params.append(source)
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


# ---------------------------------------------------------------------------
# Semantic search endpoint
# ---------------------------------------------------------------------------

@app.route('/api/semantic-search', methods=['POST', 'GET'])
def semantic_search():
    try:
        if request.method == 'GET':
            query = request.args.get('query', '').strip()
            top_k = min(int(request.args.get('top_k', 200)), 500)
            country_filter = request.args.get('country', '').strip()
        else:
            data = request.get_json()
            if data is None:
                return jsonify({'error': 'Invalid JSON body'}), 400
            query = data.get('query', '').strip()
            top_k = min(int(data.get('top_k', 200)), 500)
            country_filter = data.get('country', '').strip()
        
        if not query:
            return jsonify({'error': 'Query required'}), 400
        
        results = SEMANTIC_ENGINE.search(
            query=query,
            top_k=top_k,
            country=country_filter or None,
        )

        return jsonify({'query': query, 'count': len(results), 'results': results})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Search failed'}), 500


# ---------------------------------------------------------------------------
# Ecovillage submission endpoint (sanitized + rate-limited)
# ---------------------------------------------------------------------------

@app.route('/api/submit-ecovillage', methods=['POST'])
def submit_ecovillage():
    """Accept a new ecovillage submission, sanitize, validate, and store."""
    ip = get_client_ip()
    if not rate_limit(ip):
        return jsonify({'error': 'Too many submissions. Please wait a minute and try again.'}), 429

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON body'}), 400

        name = sanitize_text(data.get('name', ''))
        description = sanitize_text(data.get('description', ''))
        country = sanitize_text(data.get('country', ''))
        city = sanitize_text(data.get('city', ''))
        website = validate_url(data.get('website', ''))
        email = sanitize_text(data.get('email', ''))

        errors = []
        if not name or len(name) < 2:
            errors.append('Name is required (min 2 characters)')
        if not description or len(description) < 20:
            errors.append('Description is required (min 20 characters)')
        if not country:
            errors.append('Country is required')

        lat = data.get('latitude')
        lng = data.get('longitude')
        if lat is not None and lng is not None:
            try:
                lat = float(lat)
                lng = float(lng)
                if not (-90 <= lat <= 90):
                    errors.append('Latitude must be between -90 and 90')
                if not (-180 <= lng <= 180):
                    errors.append('Longitude must be between -180 and 180')
            except (ValueError, TypeError):
                errors.append('Latitude and longitude must be valid numbers')
        else:
            errors.append('Latitude and longitude are required')

        if email and not re.match(r'^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$', email):
            errors.append('Invalid email format')

        if errors:
            return jsonify({'error': '; '.join(errors)}), 400

        accepts_volunteers = bool(data.get('accepts_volunteers', False))
        accepts_visitors = bool(data.get('accepts_visitors', False))
        accepts_shortterm = bool(data.get('accepts_shortterm', False))
        accepts_longterm = bool(data.get('accepts_longterm', False))
        has_jobs = bool(data.get('has_jobs', False))

        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO organizations
                (name, description, website, email, city, country,
                 latitude, longitude, source, accepts_volunteers,
                 accepts_visitors, accepts_shortterm, accepts_longterm, has_jobs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user-submitted', ?, ?, ?, ?, ?)
        """, (
            name, description, website, email, city, country,
            lat, lng, accepts_volunteers, accepts_visitors,
            accepts_shortterm, accepts_longterm, has_jobs
        ))
        conn.commit()
        org_id = cursor.lastrowid
        conn.close()

        try:
            SEMANTIC_ENGINE.build_index(force=True)
        except Exception as e:
            print(f'Warning: could not rebuild embeddings: {e}')

        return jsonify({
            'success': True,
            'id': org_id,
            'message': f'{name} has been added to the map!'
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Submission failed'}), 500


@app.route('/api/healthz')
def health_check():
    return jsonify({"status": "healthy", "service": "volunteer-map-flask", "version": "2.0.0"})


@app.route('/api/enriched-ips', methods=['GET', 'DELETE'])
def enriched_ips_api():
    """Return all enriched IP data as JSON, or delete a specific IP."""
    if request.method == 'DELETE':
        ip = request.args.get('ip', '')
        if not ip:
            return jsonify({'error': 'ip parameter required'}), 400
        
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
        try:
            from compliance import delete_enriched_ip
            deleted = delete_enriched_ip(ip)
            return jsonify({'deleted': deleted, 'ip': ip})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # GET: return all enriched IPs
    source = request.args.get('source', 'all')
    limit = min(int(request.args.get('limit', 100)), 500)
    offset = int(request.args.get('offset', 0))
    
    conn = get_db()
    rows = conn.execute("SELECT * FROM ip_enrichments ORDER BY enriched_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM ip_enrichments").fetchone()[0]
    conn.close()
    
    return jsonify({
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [dict(r) for r in rows]
    })


@app.route('/enriched-ips')
def enriched_ips_dashboard():
    """Render the enriched IPs dashboard page."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM ip_enrichments ORDER BY enriched_at DESC LIMIT 200").fetchall()
    total = conn.execute("SELECT COUNT(*) FROM ip_enrichments").fetchone()[0]
    conn.close()
    
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enriched IPs Dashboard - volunteer.templeearth.cc</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:system-ui,sans-serif; background:#f5f7fa; color:#333; padding:20px; }
        .header { max-width:1400px; margin:0 auto 20px; display:flex; justify-content:space-between; align-items:center; }
        h1 { font-size:22px; }
        .count { color:#666; font-size:14px; }
        table { width:100%; max-width:1400px; margin:0 auto; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.08); }
        th { background:#667eea; color:white; padding:10px 8px; font-size:12px; text-align:left; white-space:nowrap; cursor:pointer; }
        td { padding:8px; font-size:12px; border-bottom:1px solid #edf2f7; vertical-align:top; max-width:200px; overflow:hidden; text-overflow:ellipsis; }
        tr:hover td { background:#f8f9ff; }
        .ip { font-family:monospace; font-weight:600; color:#667eea; }
        .badge { display:inline-block; padding:1px 6px; border-radius:3px; font-size:10px; margin:1px; }
        .badge-green { background:#c6f6d5; color:#22543d; }
        .badge-red { background:#fed7d7; color:#742a2a; }
        .badge-blue { background:#bee3f8; color:#2a4365; }
        .nav { max-width:1400px; margin:20px auto; text-align:center; font-size:13px; }
        .nav a { color:#667eea; text-decoration:none; }
        .nav a:hover { text-decoration:underline; }
        .empty { text-align:center; padding:60px 20px; color:#888; }
        .latlon { font-size:11px; color:#888; }
        @media (max-width:768px) { th, td { font-size:11px; padding:6px 4px; } }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Enriched IPs</h1>
            <span class="count">''' + str(total) + ''' enriched IPs</span>
        </div>
        <div>
            <a href="/" style="color:#667eea;text-decoration:none;font-size:14px;">&larr; Ecovillage Map</a>
            &nbsp;
            <a href="/analytics/" style="color:#667eea;text-decoration:none;font-size:14px;">Matomo</a>
        </div>
    </div>'''
    
    if not rows:
        html += '<div class="empty"><p>No enriched IPs yet. Enrichment runs every 2 minutes and on consent accept.</p></div>'
    else:
        html += '''<div style="overflow-x:auto;"><table>
        <thead><tr>
            <th>IP</th><th>Country</th><th>City</th><th>Region</th><th>Coordinates</th>
            <th>ISP</th><th>Organization</th><th>ASN</th><th>Reverse DNS</th>
            <th>Proxy/VPN</th><th>Hosting</th><th>Mobile</th>
            <th>VT Reputation</th><th>VT Votes</th><th>Blacklist</th>
            <th>Open Ports</th><th>th Hosts</th><th>Emails</th><th>Social</th><th>Entity Description</th><th>Enriched</th>
        </tr></thead><tbody>'''
        
        for r in rows:
            d = dict(r)
            loc_badge = ''
            if d.get('proxy'): loc_badge += '<span class="badge badge-red">VPN</span> '
            if d.get('hosting'): loc_badge += '<span class="badge badge-blue">Hosting</span> '
            if d.get('mobile'): loc_badge += '<span class="badge badge-green">Mobile</span> '
            
            vt_reputation = d.get('vt_reputation', '')
            vt_votes = ''
            if d.get('vt_harmless_votes') is not None or d.get('vt_malicious_votes') is not None:
                vt_votes = f"⬜{d.get('vt_harmless_votes',0)}⬛{d.get('vt_malicious_votes',0)}"
            
            blacklist = ''
            bad_colors = {'Y': '<span class="badge badge-red">BLOCKED</span>', 'N': '<span class="badge badge-green">Clean</span>'}
            if d.get('sf_blacklist'):
                blacklist = bad_colors.get(d['sf_blacklist'], d['sf_blacklist'])
            
            html += f'''<tr>
                <td class="ip">{d.get('ip','')}</td>
                <td>{d.get('country','')} ({d.get('country_code','')})</td>
                <td>{d.get('city','')}</td>
                <td>{d.get('region_name','')}</td>
                <td class="latlon">{d.get('lat','')}, {d.get('lon','')}</td>
                <td>{d.get('isp','')}</td>
                <td>{d.get('org','')}</td>
                <td>{d.get('as_number','')}</td>
                <td style="font-size:11px;">{d.get('reverse_dns','')}</td>
                <td>{loc_badge}</td>
                <td>{'Yes' if d.get('hosting') else ''}</td>
                <td>{'Yes' if d.get('mobile') else ''}</td>
                <td>{vt_reputation}</td>
                <td style="font-size:11px;">{vt_votes}</td>
                <td>{blacklist}{'Yes' if d.get('sf_blacklist') else ''}</td>
                <td style="font-size:11px;">{(d.get('sf_open_ports') or '')[:50]}</td>
                <td style="font-size:11px;">{(d.get('th_reverse_dns') or '')[:60]}</td>
                <td style="font-size:11px;">{(d.get('th_emails') or '')[:60]}</td>
                <td style="font-size:11px;">{(d.get('th_social_media') or '')[:60]}</td>
                <td style="font-size:11px;max-width:300px;">{(d.get('th_entity_description') or '')[:200]}</td>
                <td style="font-size:11px;">{d.get('enriched_at','')}</td>
            </tr>'''
        
        html += '</tbody></table></div>'
    
    html += '''
    <div class="nav">
        <a href="/api/enriched-ips">JSON API</a> &middot;
        <a href="/privacy.html">Privacy Policy</a>
    </div>
</body>
</html>'''
    
    return html


@app.route('/api/compliance')
def compliance_stats():
    """Return compliance statistics."""
    import sys, os as _os
    scripts_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'scripts')
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import compliance
        import importlib
        importlib.reload(compliance)
        return jsonify(compliance.get_stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/enrich-ip', methods=['POST'])
def enrich_ip():
    """Enrich the visitor's IP with location/ISP data via Chickadee."""
    try:
        ip = get_client_ip()
        if not ip or ip in ('127.0.0.1', '::1', '0.0.0.0'):
            return jsonify({'ok': True, 'ip': ip, 'note': 'local'})
        
        # Run Chickadee
        import subprocess, sqlite3, json
        result = subprocess.run(
            ['uv', 'run', 'chickadee', ip],
            capture_output=True, text=True, timeout=15,
            cwd='/opt/chickadee'
        )
        if result.returncode != 0:
            return jsonify({'ok': False, 'error': 'enrichment failed'}), 500
        
        data = json.loads(result.stdout.strip())
        
        # Store in DB
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT OR IGNORE INTO ip_enrichments 
            (ip, country, country_code, region, city, lat, lon, isp, org, as_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ip,
            data.get('country'),
            data.get('countryCode'),
            data.get('regionName'),
            data.get('city'),
            data.get('lat'),
            data.get('lon'),
            data.get('isp'),
            data.get('org'),
            data.get('as'),
        ))
        conn.commit()
        conn.close()
        
        return jsonify({'ok': True, 'ip': ip, 'enriched': data.get('city'), 'isp': data.get('isp')})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api-info/', strict_slashes=False, methods=['GET'])
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
            "semantic_search": "POST /api/semantic-search",
            "submit_ecovillage": "POST /api/submit-ecovillage",
            "enrich_ip": "POST /api/enrich-ip",
            "enriched_ips": "GET /api/enriched-ips",
            "compliance_stats": "GET /api/compliance",
            "stats": "GET /api/statistics/",
            "health": "GET /api/healthz",
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
