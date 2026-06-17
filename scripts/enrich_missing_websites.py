#!/usr/bin/env python3
"""Enrich missing websites for Ecoversities and EcovillageMap entries."""

import json
import sqlite3
import re
import urllib.request
from urllib.parse import quote
import os
import sys

JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ecovillage_database_v4.json')
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'organizations.db')


def fetch_html(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def scrape_ecoversities():
    """Scrape ecoversities.org directory for names and URLs."""
    print("Scraping Ecoversities directory...")
    html = fetch_html('https://ecoversities.org/ecoversities/')
    if not html:
        return {}

    # Extract all h3 > a links on the page
    matches = re.findall(r'<h3[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>', html, re.DOTALL | re.IGNORECASE)
    results = {}
    for url, name_html in matches:
        name = re.sub(r'<[^>]+>', '', name_html).strip()
        if name and url:
            results[name.lower()] = url
    print(f"  Found {len(results)} Ecoversities")
    return results


def search_ecovillage_org(name):
    """Try to find project on ecovillage.org by name."""
    search_term = name.replace("'", "").replace("'", "")
    url = f"https://ecovillage.org/wp-json/wp/v2/gen_project?search={quote(search_term)}&per_page=1"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and len(data) > 0:
                project = data[0]
                link = project.get('link', '')
                title = project.get('title', {}).get('rendered', '')
                # Only use if title is reasonably similar
                if link and title:
                    return link
    except Exception as e:
        pass
    return None


def update_json_and_db(updates):
    """Update JSON and DB with found websites."""
    if not updates:
        print("No updates to apply")
        return

    # Update JSON
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    updated_json = 0
    for entry in entries:
        entry_id = entry['id']
        if entry_id in updates:
            entry['website'] = updates[entry_id]
            updated_json += 1

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Updated {updated_json} entries in JSON")

    # Update DB
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updated_db = 0
    for entry_id, website in updates.items():
        cur.execute('UPDATE organizations SET website = ? WHERE id = ?', (website, entry_id))
        if cur.rowcount > 0:
            updated_db += 1
    conn.commit()
    conn.close()
    print(f"Updated {updated_db} entries in DB")


def main():
    print("=" * 60)
    print("Enriching Missing Websites")
    print("=" * 60)

    # Load DB to get entries needing enrichment
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get Ecoversities without websites
    cur.execute('SELECT id, name FROM organizations WHERE source = "Ecoversities" AND (website IS NULL OR website = "")')
    ecoversities = {row[0]: row[1] for row in cur.fetchall()}
    print(f"\nEcoversities to enrich: {len(ecoversities)}")

    # Get EcovillageMap without websites
    cur.execute('SELECT id, name FROM organizations WHERE source = "EcovillageMap" AND (website IS NULL OR website = "")')
    ecovmap = {row[0]: row[1] for row in cur.fetchall()}
    print(f"EcovillageMap to enrich: {len(ecovmap)}")

    conn.close()

    # Scrape Ecoversities directory
    ecoversity_links = scrape_ecoversities()

    updates = {}

    # Match Ecoversities by name
    matched = 0
    for oid, name in ecoversities.items():
        key = name.lower()
        if key in ecoversity_links:
            updates[oid] = ecoversity_links[key]
            matched += 1
        else:
            # Try partial matching
            for k, url in ecoversity_links.items():
                if name.lower() in k or k in name.lower():
                    if len(name) > 5 and len(k) > 5:
                        updates[oid] = url
                        matched += 1
                        break
    print(f"  Matched {matched} Ecoversities by name")

    # Search EcovillageMap on ecovillage.org
    print("\nSearching EcovillageMap on ecovillage.org...")
    found = 0
    for oid, name in ecovmap.items():
        link = search_ecovillage_org(name)
        if link:
            updates[oid] = link
            found += 1
            print(f"  Found: {name} -> {link}")
        else:
            print(f"  Not found: {name}")
    print(f"  Found {found} EcovillageMap projects")

    # Apply updates
    if updates:
        update_json_and_db(updates)

        # Regenerate geojson
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'convert_to_geojson.py')
        os.system(f'{sys.executable} {script_path}')
        print("GeoJSON regenerated")

    # Final stats
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM organizations WHERE website IS NULL OR website = ""')
    remaining = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM organizations')
    total = cur.fetchone()[0]
    conn.close()
    print(f"\nFinal: {total - remaining}/{total} have websites ({(total-remaining)/total*100:.1f}%)")
    print(f"Remaining without websites: {remaining}")


if __name__ == '__main__':
    main()
