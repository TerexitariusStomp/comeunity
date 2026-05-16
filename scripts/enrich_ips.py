"""
Matomo IP Enrichment Pipeline
Runs enrichment tools (Chickadee) on visitor IPs from Matomo
and stores the results for analysis.
"""
import json
import subprocess
import sqlite3
import time
import os
from datetime import datetime, timedelta

# Config
MATOMO_TOKEN = "9ff829d6a73a3ae0772605fc1cfe75df"
MATOMO_URL = "http://localhost:8003/index.php"
SITE_ID = 1
DB_PATH = "/opt/volunteer-map/backend/organizations.db"
CHICKADEE_PATH = "/opt/chickadee"

def get_recent_visits(minutes=5):
    """Fetch recent Matomo visits."""
    period = "range"
    date_from = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    date_to = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    
    import urllib.request
    url = f"{MATOMO_URL}?module=API&method=Live.getLastVisitsDetails&idSite={SITE_ID}&period=day&date=today&format=json&token_auth={MATOMO_TOKEN}&filter_limit=100"
    
    try:
        resp = urllib.request.urlopen(url, timeout=15)
        data = json.loads(resp.read())
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"Error fetching Matomo visits: {e}")
        return []

def enrich_ip_with_chickadee(ip):
    """Run Chickadee on a single IP."""
    try:
        result = subprocess.run(
            ["uv", "run", "chickadee", ip],
            capture_output=True, text=True, timeout=15,
            cwd=CHICKADEE_PATH
        )
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
        return None
    except Exception as e:
        print(f"Chickadee error for {ip}: {e}")
        return None

def ensure_enrichment_table():
    """Create the enrichment table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ip_enrichments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            ip TEXT,
            country TEXT,
            country_code TEXT,
            region TEXT,
            city TEXT,
            zip TEXT,
            lat REAL,
            lon REAL,
            timezone TEXT,
            isp TEXT,
            org TEXT,
            as_number TEXT,
            enriched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_enrich_ip ON ip_enrichments(ip)
    """)
    conn.commit()
    conn.close()

def store_enrichment(visitor_id, ip, data):
    """Store enrichment data."""
    if not data:
        return
    conn = sqlite3.connect(DB_PATH)
    # Check if we already enriched this IP recently
    existing = conn.execute(
        "SELECT id FROM ip_enrichments WHERE ip = ? AND enriched_at > datetime('now', '-1 day')",
        (ip,)
    ).fetchone()
    if existing:
        conn.close()
        return
    
    conn.execute("""
        INSERT INTO ip_enrichments 
        (visitor_id, ip, country, country_code, region, city, zip, lat, lon, timezone, isp, org, as_number)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        visitor_id,
        ip,
        data.get("country"),
        data.get("countryCode"),
        data.get("regionName"),
        data.get("city"),
        data.get("zip"),
        data.get("lat"),
        data.get("lon"),
        data.get("timezone"),
        data.get("isp"),
        data.get("org"),
        data.get("as"),
    ))
    conn.commit()
    conn.close()
    print(f"  Stored enrichment for {ip}: {data.get('city', '?')}, {data.get('country', '?')} - {data.get('isp', '?')}")

def main():
    print(f"[{datetime.now().isoformat()}] Running IP enrichment...")
    ensure_enrichment_table()
    
    visits = get_recent_visits()
    if not visits:
        print("  No recent visits found.")
        return
    
    enriched_count = 0
    for visit in visits:
        visitor_id = visit.get("visitorId", "?")
        visit_ip = visit.get("visitIp", "")
        
        if not visit_ip or visit_ip in ("127.0.0.1", "::1", ""):
            continue
        
        print(f"  Enriching {visit_ip} (visitor: {visitor_id})...")
        data = enrich_ip_with_chickadee(visit_ip)
        if data:
            store_enrichment(visitor_id, visit_ip, data)
            enriched_count += 1
    
    print(f"  Done. Enriched {enriched_count} IPs.")

if __name__ == "__main__":
    main()
