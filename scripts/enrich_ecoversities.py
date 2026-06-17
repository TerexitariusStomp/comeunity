#!/usr/bin/env python3
"""Enrich Ecoversities entries with better fuzzy matching."""

import json
import sqlite3
import urllib.request
import re
import os
import sys
from difflib import SequenceMatcher

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
    """Scrape ecoversities.org directory for all names and URLs."""
    print("Scraping Ecoversities directory...")
    html = fetch_html('https://ecoversities.org/ecoversities/')
    if not html:
        return {}

    # Extract all h3 > a links
    matches = re.findall(r'<h3[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>', html, re.DOTALL | re.IGNORECASE)
    results = {}
    for url, name_html in matches:
        name = re.sub(r'<[^>]+>', '', name_html).strip()
        if name and url:
            results[name.lower()] = url
    print(f"  Found {len(results)} Ecoversities")
    return results


def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM organizations WHERE source = "Ecoversities" AND (website IS NULL OR website = "")')
    entries = cur.fetchall()
    conn.close()

    print(f"Ecoversities to enrich: {len(entries)}")

    ecoversity_links = scrape_ecoversities()
    if not ecoversity_links:
        print("Could not scrape Ecoversities directory")
        return

    updates = {}

    # Try exact match first, then fuzzy match
    for oid, name in entries:
        key = name.lower()
        if key in ecoversity_links:
            updates[oid] = ecoversity_links[key]
            continue

        # Try fuzzy matching
        best_match = None
        best_score = 0
        for k, url in ecoversity_links.items():
            score = similar(name, k)
            if score > best_score:
                best_score = score
                best_match = url

        if best_match and best_score > 0.6:
            updates[oid] = best_match
            print(f"  Fuzzy match: '{name}' -> score {best_score:.2f}")

    print(f"\nMatched {len(updates)} Ecoversities")

    if updates:
        # Update JSON
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for entry in data:
            if entry['id'] in updates:
                entry['website'] = updates[entry['id']]
        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Update DB
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for oid, url in updates.items():
            cur.execute('UPDATE organizations SET website = ? WHERE id = ?', (url, oid))
        conn.commit()
        conn.close()

        # Regenerate geojson
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'convert_to_geojson.py')
        os.system(f'{sys.executable} {script_path}')
        print("GeoJSON regenerated")

    # Stats
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM organizations WHERE website IS NULL OR website = ""')
    remaining = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM organizations')
    total = cur.fetchone()[0]
    conn.close()
    print(f"\nFinal: {total - remaining}/{total} have websites ({(total-remaining)/total*100:.1f}%)")


if __name__ == '__main__':
    main()
