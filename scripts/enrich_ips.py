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
    th_banners TEXT,
    th_emails TEXT,
    th_social_media TEXT,
    th_entity_description TEXT
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
            "th_emails": "TEXT", "th_social_media": "TEXT",
            "th_entity_description": "TEXT", "otx_asn": "TEXT",
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
# Tier 2b: Robtex - Free IP/DNS enrichment (no API key needed)
# ---------------------------------------------------------------------------
def enrich_robtex(ip):
    """Query Robtex for IP intelligence (free, no key needed)."""
    try:
        import urllib.request
        import json
        
        # Robtex has a free API for IP lookups
        url = f"https://freeapi.robtex.com/ipquery/{ip}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode()
        
        data = {}
        if raw.strip():
            try:
                robtex_data = json.loads(raw)
                if robtex_data.get("status") == "ok":
                    # Robtex returns: as, asname, asdesc, country, bgproute, pas (related domains)
                    rob_asn = robtex_data.get("as")
                    rob_asname = robtex_data.get("asname")
                    if rob_asn and not data.get("as_number"):
                        data["as_number"] = f"AS{rob_asn} {rob_asname or ''}"
                    if rob_asname and not data.get("org"):
                        data["org"] = rob_asname
                    
                    # Related domains (pas = potentially associated)
                    pas = robtex_data.get("pas")
                    if pas and isinstance(pas, list):
                        domains = [p.get("o", "") for p in pas if p.get("o")]
                        if domains:
                            data["th_associated_urls"] = ", ".join(domains[:30])
                    
                    # BGP route
                    bgp = robtex_data.get("bgproute")
                    if bgp:
                        data["sf_bgp_cidr"] = bgp
                    
                    # WHOIS description
                    whois = robtex_data.get("whoisdesc")
                    if whois and not data.get("sf_whois_org"):
                        data["sf_whois_org"] = whois
                    
                    print(f"    ✓ Robtex: AS={rob_asn}, domains={len(pas or [])}")
            except json.JSONDecodeError:
                pass
        
        return data
    except Exception as e:
        # Robtex might block or throttle
        return None


# ---------------------------------------------------------------------------
# Tier 2c: theHarvester (reverse DNS, emails, social, OSINT)
# ---------------------------------------------------------------------------
def enrich_theharvester(ip):
    """Run theHarvester with multiple OSINT sources for comprehensive enrichment."""
    try:
        # Use multiple search sources for maximum data coverage
        # dns: reverse DNS lookups
        # bing/duckduckgo: web search for social profiles, mentions
        # hunter: email discovery via Hunter.io API
        # censys: SSL cert metadata (hostnames, emails from certificates)
        # hackertarget: reverse IP/DNS lookups
        sources = "dns,bing,duckduckgo,hunter,censys,hackertarget"
        result = subprocess.run(
            ["uv", "run", "theHarvester", "-d", ip, "-b", sources, "-l", "100"],
            capture_output=True, text=True, timeout=180,
            cwd=THEHARVESTER_PATH
        )
        output = result.stdout + result.stderr
        
        data = {}
        
        # Reverse DNS hosts
        hosts = re.findall(r'(?:Host|IP):\s*(\S+)', output)
        vhosts = [h for h in hosts if h != ip]
        if vhosts:
            data["th_reverse_dns"] = ", ".join(vhosts[:20])
        
        # URLs
        urls = re.findall(r'https?://[^\s"\']+', output)
        if urls:
            data["th_associated_urls"] = ", ".join(urls[:20])
        
        # Emails from theHarvester output
        emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.+-]+', output)
        if emails:
            data["th_emails"] = ", ".join(set(emails[:50]))
            print(f"    ✓ Found emails: {len(set(emails))}")
        
        # Social media handles / profiles
        social_patterns = [
            r'(facebook\.com/[\w.]+)',
            r'(twitter\.com/[\w_]+)',
            r'(linkedin\.com/(?:company|in)/[\w-]+)',
            r'(instagram\.com/[\w_.]+)',
            r'(github\.com/[\w-]+)',
            r'(youtube\.com/@?[\w-]+)',
            r'(tiktok\.com/@?[\w.]+)',
        ]
        social_found = []
        for pat in social_patterns:
            matches = re.findall(pat, output, re.IGNORECASE)
            social_found.extend(matches[:5])
        if social_found:
            data["th_social_media"] = ", ".join(set(social_found[:20]))
            print(f"    ✓ Social profiles: {len(set(social_found))}")
        
        return data
    except Exception as e:
        print(f"  ✗ theHarvester error: {e}")
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
# Tier 2d: AlienVault OTX - Threat intelligence (free tier, needs API key)
# ---------------------------------------------------------------------------
OTX_API_KEY = "2399eabd8059bad30f59041c3485c88b93e05f220aa197ef03647b47fe42a0b3"

def enrich_alienvault(ip):
    """Query AlienVault OTX for threat intelligence data."""
    try:
        import urllib.request
        import json
        
        url = f"https://otx.alienvault.com/api/v1/indicators/IPv4/{ip}/general"
        req = urllib.request.Request(url, headers={
            'X-OTX-API-KEY': OTX_API_KEY,
            'User-Agent': 'Mozilla/5.0'
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        
        result = {}
        
        # Reputation score (0 = clean, negative = malicious)
        rep = data.get("reputation")
        if rep is not None:
            result["vt_reputation"] = rep
        
        # Pulse info - threat intelligence
        pulse_info = data.get("pulse_info", {})
        pulse_count = pulse_info.get("count", 0)
        if pulse_count > 0:
            result["sf_threat_scores"] = str(pulse_count)
            pulses = pulse_info.get("pulses", [])
            tags = set()
            for p in pulses[:10]:
                for t in p.get("tags", []):
                    tags.add(t)
            if tags:
                result["vt_tags"] = ", ".join(list(tags)[:20])
        
        # ASN from OTX
        otx_asn = data.get("asn")
        if otx_asn:
            # Format: "AS15169 google llc"
            result["otx_asn"] = otx_asn
        
        print(f"    ✓ AlienVault: rep={rep}, pulses={pulse_count}")
        return result
    except Exception as e:
        print(f"    ✗ AlienVault: {e}")
        return None


# ---------------------------------------------------------------------------
# Tier 2e: Entity Description Generator
# ---------------------------------------------------------------------------
def generate_entity_description(ip, data):
    """Generate a human-readable entity description from all enrichment data."""
    parts = []
    
    # Who owns it
    org = data.get("org") or data.get("isp") or data.get("sf_whois_org") or data.get("vt_as_owner")
    asn = data.get("as_number") or data.get("otx_asn", "")
    if org:
        parts.append(f"{ip} belongs to {org}")
        if asn:
            parts[-1] += f" ({asn})"
    elif asn:
        parts.append(f"{ip} is under {asn}")
    
    # Where is it
    city = data.get("city")
    region = data.get("region_name") or data.get("region")
    country = data.get("country") or data.get("country_code")
    loc_parts = [p for p in [city, region, country] if p]
    if loc_parts:
        parts.append(f"located in {', '.join(loc_parts)}")
    
    # What type
    types = []
    if data.get("hosting"): types.append("hosting infrastructure")
    if data.get("proxy"): types.append("proxy/VPN")
    if data.get("mobile"): types.append("mobile network")
    
    # Infer type from org/ASN if not flagged
    if not types:
        org_lower = (org or "").lower()
        if any(k in org_lower for k in ["google", "cloudflare", "aws", "amazon", "azure", "microsoft",
                                          "digitalocean", "linode", "ovh", "hetzner", "oracle",
                                          "ibm", "alibaba", "tencent", "vultr", "scaleway",
                                          "hosting", "host", "server", "cloud", "data center",
                                          "cdn", "dns", "transit"]):
            types.append("hosting/infrastructure")
        elif data.get("hosting") == False:
            types.append("residential/business IP")
    if types:
        parts.append(f"classified as {'/'.join(types)}")
    
    # Reputation assessment
    rep_assessment = []
    vt_rep = data.get("vt_reputation")
    if vt_rep is not None:
        try:
            rep_val = int(vt_rep)
            if rep_val < 0:
                rep_assessment.append(f"negative reputation ({rep_val})")
            elif rep_val == 0:
                rep_assessment.append("neutral reputation")
            else:
                rep_assessment.append(f"positive reputation ({rep_val})")
        except (ValueError, TypeError):
            pass
    
    if data.get("sf_blacklist"):
        rep_assessment.append("listed on blacklists")
    else:
        rep_assessment.append("not found on blacklists")
    
    threat_count = data.get("sf_threat_scores")
    if threat_count and threat_count != "0":
        rep_assessment.append(f"{threat_count} threat associations")
    
    if rep_assessment:
        parts.append("has " + ", ".join(rep_assessment))
    
    # ISP info
    isp = data.get("isp")
    if isp and isp != org:
        parts.append(f"served by {isp}")
    
    # Reverse DNS / hostname
    rdns = data.get("reverse_dns") or data.get("th_reverse_dns")
    if rdns:
        parts.append(f"identified as {rdns.split(',')[0].strip()}")
    
    # Associated domains
    domains = data.get("th_associated_urls")
    if domains:
        domain_list = domains.split(",")[:3]
        parts.append(f"associated with {', '.join(d.strip() for d in domain_list)}")
    
    # Threat tags
    tags = data.get("vt_tags")
    if tags:
        parts.append(f"tagged as: {tags[:100]}")
    
    # Build description
    description = ". ".join(parts) + "."
    if len(description) > 500:
        description = description[:497] + "..."
    
    return description


# ---------------------------------------------------------------------------
# Tier 2f: Entity Description Web Search Enrichment
# ---------------------------------------------------------------------------
def enrich_with_description_search(ip, description):
    """Use the entity description as a search query to find additional context."""
    if not description or len(description) < 30:
        return None
    
    try:
        import urllib.request
        import urllib.parse
        import json
        
        # Extract key terms from the description for a focused search
        # Find the organization name
        org_match = __import__('re').search(r'belongs to ([^(]+)', description)
        org_name = org_match.group(1).strip() if org_match else ""
        
        # Create a focused search query
        query_parts = [org_name] if org_name else []
        asn_match = __import__('re').search(r'AS(\d+)', description)
        if asn_match:
            query_parts.append(f"AS{asn_match.group(1)}")
        
        # Also add the IP to the search
        ip_match = __import__('re').search(r'^\d+\.\d+\.\d+\.\d+', description)
        if ip_match:
            query_parts.append(ip_match.group(0))
        
        search_query = " ".join(query_parts) if query_parts else description[:200]
        
        # Use DuckDuckGo for a free web search
        # DuckDuckGo's lite API doesn't need an API key
        encoded = urllib.parse.quote(search_query)
        search_url = f"https://lite.duckduckgo.com/lite/?q={encoded}"
        req = urllib.request.Request(search_url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode('utf-8', errors='ignore')
        
        # Extract result snippets from the HTML
        import re as _re
        snippets = _re.findall(r'class="result-snippet">(.*?)</', html, _re.DOTALL)
        if not snippets:
            # Fallback: extract any text between link tags
            snippets = _re.findall(r'<a[^>]*class="result-link"[^>]*>(.*?)</a>', html)
        
        result = {}
        if snippets:
            result["th_associated_urls_extra"] = " | ".join(s.strip() for s in snippets[:5] if s.strip())
            print(f"    ✓ Web search found {len(snippets)} results for '{search_query[:60]}...'")
        else:
            # Try the DDG instant answer API as fallback
            search_url2 = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
            req2 = urllib.request.Request(search_url2, headers={'User-Agent': 'Mozilla/5.0'})
            resp2 = urllib.request.urlopen(req2, timeout=10)
            ddg_data = json.loads(resp2.read().decode())
            if ddg_data.get("Abstract"):
                result["th_associated_urls_extra"] = ddg_data["Abstract"][:300]
                print(f"    ✓ DDG Abstract found: {ddg_data['Abstract'][:80]}...")
            elif ddg_data.get("Results"):
                titles = [r.get("Text", "") for r in ddg_data["Results"][:3] if r.get("Text")]
                if titles:
                    result["th_associated_urls_extra"] = " | ".join(titles)
                    print(f"    ✓ DDG Results found: {len(titles)}")
        
        return result
    except Exception as e:
        print(f"    ✗ Web search enrichment: {e}")
        return None


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------


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
    
    # Tier 2b: Robtex - FAST (free API, no key)
    if not data.get("note"):
        try:
            rob = enrich_robtex(ip)
            if rob:
                # Merge, preferring existing data
                for k, v in rob.items():
                    if v and not data.get(k):
                        data[k] = v
        except Exception as e:
            print(f"    ✗ Robtex: {e}")
    
    # Tier 2c: theHarvester - MEDIUM
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
    vt_api_key = os.environ.get("VT_API_KEY", "94ea215b1138aa1d3c1d933b4ff9d53f1293f83ee28734d4746b28f6b2d91d01")
    if vt_api_key and ('2' in tiers or '3' in tiers):
        try:
            import tempfile, os as _os
            # Create a temp config file for Chickadee with the VT key
            config_content = f"""[chickadee]
resolver = virustotal
virustotal = {vt_api_key}
"""
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
                f.write(config_content)
                config_path = f.name
            
            vt_result = subprocess.run(
                ["uv", "run", "chickadee", "-c", config_path, ip],
                capture_output=True, text=True, timeout=30,
                cwd=CHICKADEE_PATH
            )
            _os.unlink(config_path)
            
            if vt_result.returncode == 0 and vt_result.stdout.strip():
                vt_data_raw = vt_result.stdout.strip()
                # Parse - chickadee returns json array
                vt_data = json.loads(vt_data_raw)
                if isinstance(vt_data, list):
                    vt_data = vt_data[0] if vt_data else {}
                data["vt_reputation"] = vt_data.get("reputation")
                data["vt_as_owner"] = vt_data.get("as_owner") or vt_data.get("as")
                data["vt_continent"] = vt_data.get("continent")
                data["vt_network"] = vt_data.get("network")
                data["vt_harmless_votes"] = vt_data.get("harmless_votes") or vt_data.get("total_harmless")
                data["vt_malicious_votes"] = vt_data.get("malicious_votes") or vt_data.get("total_malicious")
                print(f"    ✓ VirusTotal: rep={data.get('vt_reputation')}")
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
    
    # Tier 2d: AlienVault OTX
    if not data.get("note"):
        try:
            av = enrich_alienvault(ip)
            if av:
                for k, v in av.items():
                    if v is not None and not data.get(k):
                        data[k] = v
        except Exception as e:
            print(f"    ✗ AlienVault: {e}")
    
    # Generate entity description from all collected data
    if data and not data.get("note"):
        try:
            desc = generate_entity_description(ip, data)
            if desc:
                data["th_entity_description"] = desc
                print(f"    ✓ Entity description generated ({len(desc)} chars)")
                
                # Use the description as a search query to find additional context
                search_data = enrich_with_description_search(ip, desc)
                if search_data:
                    for k, v in search_data.items():
                        if v and not data.get(k):
                            data[k] = v
        except Exception as e:
            print(f"    ✗ Description/search: {e}")
    
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
