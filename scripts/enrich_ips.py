"""
Comprehensive IP Enrichment Pipeline
Runs Chickadee, SpiderFoot, and theHarvester on visitor IPs.
Captures ALL data points from each tool.
"""
import json
import subprocess
import sqlite3
import os
import re
from datetime import datetime

DB_PATH = "/opt/volunteer-map/backend/organizations.db"
CHICKADEE_PATH = "/opt/chickadee"
SPIDERFOOT_PATH = "/opt/spiderfoot"
THEHARVESTER_PATH = "/opt/theHarvester"

# ---------------------------------------------------------------------------
# DB Schema: all enrichment data points
# ---------------------------------------------------------------------------
ENRICHMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT UNIQUE,
    enriched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- ip-api.com / Chickadee (Tier 1)
    country TEXT,
    country_code TEXT,
    region TEXT,
    region_name TEXT,
    city TEXT,
    zip TEXT,
    lat REAL,
    lon REAL,
    timezone TEXT,
    isp TEXT,
    org TEXT,
    as_number TEXT,
    reverse_dns TEXT,
    mobile BOOLEAN,
    proxy BOOLEAN,
    hosting BOOLEAN,
    
    -- VirusTotal (Chickadee Tier 2)
    vt_as_owner TEXT,
    vt_continent TEXT,
    vt_network TEXT,
    vt_registry TEXT,
    vt_reputation INTEGER,
    vt_harmless_votes INTEGER,
    vt_malicious_votes INTEGER,
    vt_last_analysis_date TEXT,
    vt_whois TEXT,
    vt_jarm TEXT,
    vt_tags TEXT,
    vt_detection_samples TEXT,
    
    -- SpiderFoot (Tier 3)
    sf_whois_org TEXT,
    sf_whois_netrange TEXT,
    sf_blacklist TEXT,
    sf_open_ports TEXT,
    sf_hosting_provider TEXT,
    sf_reverse_domains TEXT,
    sf_proxy_vpn TEXT,
    sf_ssl_cert TEXT,
    sf_reputation_risk TEXT,
    sf_bgp_asn TEXT,
    sf_bgp_cidr TEXT,
    sf_threat_scores TEXT,
    
    -- theHarvester (Tier 2)
    th_reverse_dns TEXT,
    th_virtual_hosts TEXT,
    th_dns_servers TEXT,
    th_open_ports TEXT,
    th_associated_urls TEXT,
    th_banners TEXT
);
"""

def ensure_schema():
    conn = sqlite3.connect(DB_PATH)
    # Check if columns exist and add any missing ones
    existing_cols = set()
    try:
        existing = conn.execute("PRAGMA table_info(ip_enrichments)").fetchall()
        existing_cols = {r[1] for r in existing}
    except Exception:
        pass
    
    if not existing_cols:
        conn.execute(ENRICHMENT_SCHEMA)
        conn.commit()
    else:
        # Add missing columns
        additions = {
            "reverse_dns": "TEXT", "mobile": "BOOLEAN", "proxy": "BOOLEAN", "hosting": "BOOLEAN",
            "vt_as_owner": "TEXT", "vt_continent": "TEXT", "vt_network": "TEXT", "vt_registry": "TEXT",
            "vt_reputation": "INTEGER", "vt_harmless_votes": "INTEGER", "vt_malicious_votes": "INTEGER",
            "vt_last_analysis_date": "TEXT", "vt_whois": "TEXT", "vt_jarm": "TEXT", "vt_tags": "TEXT",
            "vt_detection_samples": "TEXT",
            "sf_whois_org": "TEXT", "sf_whois_netrange": "TEXT", "sf_blacklist": "TEXT",
            "sf_open_ports": "TEXT", "sf_hosting_provider": "TEXT", "sf_reverse_domains": "TEXT",
            "sf_proxy_vpn": "TEXT", "sf_ssl_cert": "TEXT", "sf_reputation_risk": "TEXT",
            "sf_bgp_asn": "TEXT", "sf_bgp_cidr": "TEXT", "sf_threat_scores": "TEXT",
            "th_reverse_dns": "TEXT", "th_virtual_hosts": "TEXT", "th_dns_servers": "TEXT",
            "th_open_ports": "TEXT", "th_associated_urls": "TEXT", "th_banners": "TEXT",
        }
        for col, coltype in additions.items():
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE ip_enrichments ADD COLUMN {col} {coltype}")
                except Exception:
                    pass
        conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Tier 1: Chickadee (ip-api.com) - FAST
# ---------------------------------------------------------------------------
def enrich_chickadee_ipapi(ip):
    """Run Chickadee with ip-api.com. Returns dict with all data points."""
    try:
        result = subprocess.run(
            ["uv", "run", "chickadee", "-r", "ip_api", ip],
            capture_output=True, text=True, timeout=15,
            cwd=CHICKADEE_PATH
        )
        if result.returncode != 0:
            return None
        
        # Parse the JSON output
        data = json.loads(result.stdout.strip())
        # ip-api.com returns the data directly (not wrapped)
        # It might be a list if multiple IPs
        if isinstance(data, list):
            data = data[0] if data else {}
        
        return {
            "country": data.get("country"),
            "country_code": data.get("countryCode"),
            "region": data.get("region"),
            "region_name": data.get("regionName"),
            "city": data.get("city"),
            "zip": data.get("zip"),
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "timezone": data.get("timezone"),
            "isp": data.get("isp"),
            "org": data.get("org"),
            "as_number": data.get("as"),
            "reverse_dns": data.get("reverse", data.get("rdns")),
            "mobile": data.get("mobile", False),
            "proxy": data.get("proxy", False),
            "hosting": data.get("hosting", False),
        }
    except Exception as e:
        print(f"  Chickadee ip-api error: {e}")
        return None


# ---------------------------------------------------------------------------
# Tier 2a: theHarvester (reverse DNS, virtual hosts, ports)
# ---------------------------------------------------------------------------
def enrich_theharvester(ip):
    """Run theHarvester against an IP for reverse DNS and host discovery."""
    try:
        # theHarvester's -d flag expects a domain, but we can use IP-based search
        # Use dns reverse lookup, bing, etc.
        result = subprocess.run(
            ["uv", "run", "theHarvester", "-d", ip, "-b", "dns,bing,duckduckgo", "-l", "20"],
            capture_output=True, text=True, timeout=60,
            cwd=THEHARVESTER_PATH
        )
        output = result.stdout + result.stderr
        
        data = {}
        hosts = re.findall(r'(?:Host|IP):\s*(\S+)', output)
        vhosts = [h for h in hosts if h != ip]
        if vhosts:
            data["th_reverse_dns"] = ", ".join(vhosts[:20])
        
        urls = re.findall(r'https?://[^\s"\']+', output)
        if urls:
            data["th_associated_urls"] = ", ".join(urls[:20])
        
        return data
    except Exception as e:
        print(f"  theHarvester error: {e}")
        return None


# ---------------------------------------------------------------------------
# Tier 3: SpiderFoot (deep OSINT - run in background)
# ---------------------------------------------------------------------------
def enrich_spiderfoot(ip):
    """Run SpiderFoot scan against IP for deep enrichment. Returns immediately,
    results are stored asynchronously via the background output parser."""
    try:
        spiderfoot_dir = SPIDERFOOT_PATH
        venv_python = f"{spiderfoot_dir}/.venv/bin/python"
        sfcli = f"{spiderfoot_dir}/sfcli.py"
        
        # SpiderFoot CLI can output JSON with -o json flag
        result = subprocess.run(
            [venv_python, sfcli, "-s", ip, "-o", "json", "-q"],
            capture_output=True, text=True, timeout=300,
            cwd=spiderfoot_dir
        )
        output = result.stdout + result.stderr
        
        data = {}
        
        # Parse key SpiderFoot findings
        orgs = re.findall(r'(?:Organization|Owner):\s*(.+?)(?:\n|$)', output)
        if orgs:
            data["sf_whois_org"] = orgs[0].strip()
        
        netranges = re.findall(r'(?:NetRange|CIDR|Network):\s*(\S+)', output)
        if netranges:
            data["sf_whois_netrange"] = ", ".join(netranges[:5])
        
        # Blacklist / threat detection
        if re.search(r'(?:Blacklist|BLACKLISTED|Spamhaus|SURBL|blocked|malicious)', output, re.IGNORECASE):
            data["sf_blacklist"] = "Y"
        
        # Open ports
        ports = re.findall(r'(?:Port|port)\s*(\d+)', output)
        if ports:
            data["sf_open_ports"] = ", ".join(ports[:20])
        
        # Hosting provider
        hosters = re.findall(r'(?:Hosting|Provider|hosted by):\s*(.+?)(?:\n|$)', output)
        if hosters:
            data["sf_hosting_provider"] = hosters[0].strip()
        
        # BGP / ASN data
        bgp_asns = re.findall(r'(?:AS|ASN):\s*(\d+)', output)
        if bgp_asns:
            data["sf_bgp_asn"] = bgp_asns[0]
        
        # Proxy/VPN detection
        if re.search(r'(?:Proxy|VPN|Tor|anonymizer)', output, re.IGNORECASE):
            data["sf_proxy_vpn"] = "Y"
        
        # Reputation risk (GreyNoise, AlienVault, etc)
        rep_scores = re.findall(r'(?:Score|score|reputation):\s*([-\d.]+)', output)
        if rep_scores:
            data["sf_reputation_risk"] = rep_scores[0]
        
        # Threat scores (multiple sources)
        threats = re.findall(r'(?:Malicious|malicious|Suspicious|suspicious|Threat|threat)', output)
        if threats:
            data["sf_threat_scores"] = str(len(threats))
        
        # SSL certificate info
        ssl_matches = re.findall(r'(?:SSL|TLS|Certificate|certificate)[^:]*:\s*(.+?)(?:\n|$)', output)
        if ssl_matches:
            data["sf_ssl_cert"] = ssl_matches[0].strip()[:200]
        
        # Reverse domains
        rev_domains = re.findall(r'(?:Reverse|PTR|rDNS):\s*(\S+)', output)
        if rev_domains:
            data["sf_reverse_domains"] = ", ".join(rev_domains[:10])
        
        return data
        
    except subprocess.TimeoutExpired:
        print(f"  SpiderFoot timed out for {ip}")
        return {"sf_reputation_risk": "timeout"}
    except Exception as e:
        print(f"  SpiderFoot error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------
def enrich_ip(ip, tiers="123"):
    """Enrich a single IP. tiers: '1'=quick, '12'=medium, '123'=full (slow)."""
    if not ip or ip in ("127.0.0.1", "::1", "0.0.0.0"):
        return {"note": "local"}
    
    print(f"  Enriching {ip}...")
    data = {}
    
    # Tier 1: Chickadee (ip-api.com) - FAST
    try:
        chick = enrich_chickadee_ipapi(ip)
        if chick:
            data.update(chick)
            print(f"    ✓ Chickadee: {chick.get('city', '?')}, {chick.get('country', '?')} - {chick.get('isp', '?')}")
    except Exception as e:
        print(f"    ✗ Chickadee: {e}")
    
    # Tier 2: theHarvester - MEDIUM
    if '2' in tiers or '3' in tiers:
        try:
            th = enrich_theharvester(ip)
            if th:
                data.update(th)
                if th.get("th_reverse_dns"):
                    print(f"    ✓ theHarvester: {th['th_reverse_dns']}")
        except Exception as e:
            print(f"    ✗ theHarvester: {e}")
    
    # Also try Chickadee with VirusTotal if API key is set
    vt_api_key = os.environ.get("VT_API_KEY")
    if vt_api_key and ('2' in tiers or '3' in tiers):
        try:
            vt_result = subprocess.run(
                ["uv", "run", "chickadee", "-r", "virustotal", ip],
                capture_output=True, text=True, timeout=30,
                cwd=CHICKADEE_PATH,
                env={**os.environ, "VT_API_KEY": vt_api_key}
            )
            if vt_result.returncode == 0:
                vt_data = json.loads(vt_result.stdout.strip())
                if isinstance(vt_data, list):
                    vt_data = vt_data[0] if vt_data else {}
                data["vt_reputation"] = vt_data.get("reputation", vt_data.get("vt_reputation"))
                data["vt_as_owner"] = vt_data.get("as_owner", vt_data.get("as"))
                data["vt_continent"] = vt_data.get("continent")
                data["vt_network"] = vt_data.get("network")
                data["vt_harmless_votes"] = vt_data.get("harmless_votes") or vt_data.get("total_harmless")
                data["vt_malicious_votes"] = vt_data.get("malicious_votes") or vt_data.get("total_malicious")
                print(f"    ✓ VirusTotal: rep={data['vt_reputation']}")
        except Exception as e:
            print(f"    ✗ VirusTotal: {e}")
    
    # Tier 3: SpiderFoot - SLOW (can take minutes per IP)
    if '3' in tiers:
        try:
            sf = enrich_spiderfoot(ip)
            if sf:
                data.update(sf)
                if sf.get("sf_open_ports"):
                    print(f"    ✓ SpiderFoot: ports={sf['sf_open_ports']}")
                elif sf.get("sf_blacklist"):
                    print(f"    ✓ SpiderFoot: blacklisted={sf['sf_blacklist']}")
                else:
                    print(f"    ✓ SpiderFoot: scan complete")
        except Exception as e:
            print(f"    ✗ SpiderFoot: {e}")
    
    return data


def store_enrichment(ip, data):
    """Store enrichment data in the database."""
    if not data or data.get("note") == "local":
        return
    
    conn = sqlite3.connect(DB_PATH)
    
    # Check if already exists
    existing = conn.execute(
        "SELECT id FROM ip_enrichments WHERE ip = ?", (ip,)
    ).fetchone()
    
    if existing:
        # Update
        set_clause = ", ".join(f"{k} = ?" for k in data.keys() if k not in ("note",))
        vals = [data[k] for k in data.keys() if k not in ("note",)]
        vals.append(ip)
        conn.execute(f"UPDATE ip_enrichments SET enriched_at = CURRENT_TIMESTAMP, {set_clause} WHERE ip = ?", vals)
    else:
        # Insert
        cols = list(data.keys() - {"note"})
        placeholders = ", ".join("?" for _ in cols)
        vals = [data.get(c) for c in cols]
        conn.execute(f"INSERT INTO ip_enrichments (ip, {', '.join(cols)}) VALUES (?, {placeholders})", [ip] + vals)
    
    conn.commit()
    conn.close()


def main(tiers="12"):
    """Run enrichment. tiers: '1'=fast, '12'=medium, '123'=full."""
    print(f"[{datetime.now().isoformat()}] Running IP enrichment (tiers={tiers})...")
    ensure_schema()
    
    # Get IPs from Matomo
    import urllib.request
    TOKEN = "9ff829d6a73a3ae0772605fc1cfe75df"
    MATOMO_URL = f"http://localhost:8003/index.php?module=API&method=Live.getLastVisitsDetails&idSite=1&period=day&date=today&format=json&token_auth={TOKEN}&filter_limit=50"
    
    try:
        resp = urllib.request.urlopen(MATOMO_URL, timeout=15)
        visits = json.loads(resp.read())
    except Exception as e:
        print(f"  Error fetching visits: {e}")
        visits = []
    
    if not isinstance(visits, list) or not visits:
        print("  No recent visits found.")
        return
    
    enriched = 0
    for visit in visits:
        ip = visit.get("visitIp", "")
        if not ip or ip in ("127.0.0.1", "::1", ""):
            continue
        
        data = enrich_ip(ip, tiers="12")  # Tiers 1+2 (skip SpiderFoot which is slow)
        if data and data.get("note") != "local":
            store_enrichment(ip, data)
            enriched += 1
    
    print(f"  Done. Enriched {enriched} IPs.")


if __name__ == "__main__":
    import sys
    tiers = sys.argv[1] if len(sys.argv) > 1 else "12"
    main(tiers=tiers)
