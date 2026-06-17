#!/usr/bin/env python3
"""Aggressively search ecovillage.org for EcovillageMap entries."""

import json
import sqlite3
import urllib.request
from urllib.parse import quote
import os
import sys
import re

JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ecovillage_database_v4.json')
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'organizations.db')


def fetch_json(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def slugify(name):
    """Create WordPress-like slug from name."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s)
    return s


def try_direct_slug(name):
    """Try to construct ecovillage.org project URL from name slug."""
    slug = slugify(name)
    url = f"https://ecovillage.org/project/{slug}/"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')
            # Check if it's a real project page (not 404)
            if 'og:title' in html or 'entry-title' in html or 'gen_project' in html:
                # Extract title to verify
                title_match = re.search(r'<title>(.*?)</title>', html)
                if title_match:
                    title = title_match.group(1).strip()
                    if 'Page not found' not in title and '404' not in title:
                        return url
    except urllib.error.HTTPError as e:
        if e.code == 404:
            pass
    except Exception:
        pass
    return None


def try_search_api(name):
    """Try WordPress search API with different variations."""
    for search_term in [name, name.split('(')[0].strip(), name.split('-')[0].strip()]:
        search_term = search_term.strip()
        if len(search_term) < 3:
            continue
        url = f"https://ecovillage.org/wp-json/wp/v2/gen_project?search={quote(search_term)}&per_page=5"
        data = fetch_json(url)
        if data and len(data) > 0:
            for project in data:
                title = project.get('title', {}).get('rendered', '')
                link = project.get('link', '')
                # Check if title is reasonably similar
                if title and link:
                    # Very loose matching - just check if any significant word matches
                    name_words = set(re.sub(r'[^a-z]', ' ', name.lower()).split())
                    title_words = set(re.sub(r'[^a-z]', ' ', title.lower()).split())
                    if len(name_words) > 0:
                        overlap = name_words & title_words
                        if len(overlap) >= min(2, len(name_words)) or any(w in title.lower() for w in name.lower().split() if len(w) > 4):
                            return link
    return None


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, name FROM organizations WHERE source = "EcovillageMap" AND (website IS NULL OR website = "")')
    entries = cur.fetchall()
    conn.close()

    print(f"Trying to enrich {len(entries)} EcovillageMap entries")
    updates = {}

    for i, (oid, name) in enumerate(entries):
        print(f"[{i+1}/{len(entries)}] {name}")

        # Try direct slug first
        url = try_direct_slug(name)
        if url:
            print(f"  -> Found via slug: {url}")
            updates[oid] = url
            continue

        # Try search API
        url = try_search_api(name)
        if url:
            print(f"  -> Found via API: {url}")
            updates[oid] = url
            continue

        print(f"  -> Not found")

    if updates:
        print(f"\nFound {len(updates)} websites")

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
    else:
        print("No new websites found")


if __name__ == '__main__':
    main()
