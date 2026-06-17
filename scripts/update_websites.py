#!/usr/bin/env python3
"""Clean and enrich organization data: fix websites, remove low-quality entries, update DB and GeoJSON."""

import json
import sqlite3
import os
import sys

# Paths
JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ecovillage_database_v4.json')
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ecovillage_database_v4.csv')
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'organizations.db')
GEOJSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'data', 'organizations.geojson')


def load_json_data():
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_data(data):
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(data)} records to {JSON_PATH}")


def remove_low_quality(entries):
    """Remove entries that are just generic coordinates without real names."""
    removed = 0
    kept = []
    for entry in entries:
        name = entry.get('name', '')
        # Remove PermacultureGlobal entries that are just "PermacultureGlobal Project #N"
        if name.startswith('PermacultureGlobal Project #') and not entry.get('website'):
            removed += 1
            continue
        # Remove entries with no name or empty name
        if not name or not name.strip():
            removed += 1
            continue
        kept.append(entry)
    print(f"Removed {removed} low-quality entries (generic names, no websites)")
    return kept


def fix_website_fallbacks(entries):
    """Use directory_url as fallback for empty website. Returns (updated_entries, set_of_updated_ids)."""
    fixed = 0
    updated_ids = set()
    for entry in entries:
        website = entry.get('website', '')
        if not website:
            directory_url = entry.get('directory_url', '')
            if directory_url and directory_url.startswith('http'):
                entry['website'] = directory_url
                updated_ids.add(entry['id'])
                fixed += 1
    print(f"Fixed {fixed} entries using directory_url fallback")
    return entries, updated_ids


def update_db_in_place(entries_to_keep, website_updates):
    """Update SQLite database in-place: remove deleted entries, update websites, preserve all enriched fields."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Build set of IDs to keep
    keep_ids = {e['id'] for e in entries_to_keep}

    # 1. Delete entries that were removed from JSON
    cur.execute('SELECT id, name FROM organizations')
    db_ids = {row[0] for row in cur.fetchall()}
    removed_ids = db_ids - keep_ids
    if removed_ids:
        placeholders = ','.join('?' * len(removed_ids))
        cur.execute(f'DELETE FROM organizations WHERE id IN ({placeholders})', tuple(removed_ids))
        conn.commit()
        print(f"Removed {len(removed_ids)} entries from database")

    # 2. Update website fields from JSON
    updated = 0
    for entry in entries_to_keep:
        entry_id = entry['id']
        website = entry.get('website', '') or ''
        directory_url = entry.get('directory_url', '') or ''
        if entry_id in website_updates:
            cur.execute('''
                UPDATE organizations
                SET website = ?, directory_url = ?
                WHERE id = ?
            ''', (website, directory_url, entry_id))
            updated += 1

    conn.commit()
    print(f"Updated {updated} website entries in database")

    # 3. Also use direct_website as fallback where website is still empty
    cur.execute('''
        UPDATE organizations
        SET website = direct_website
        WHERE (website IS NULL OR website = '')
        AND (direct_website IS NOT NULL AND direct_website != '')
    ''')
    direct_fixed = cur.rowcount
    conn.commit()
    print(f"Fixed {direct_fixed} additional entries using direct_website fallback in DB")

    # 4. Also use directory_url as fallback where website is still empty
    cur.execute('''
        UPDATE organizations
        SET website = directory_url
        WHERE (website IS NULL OR website = '')
        AND (direct_website IS NULL OR direct_website = '')
        AND (directory_url IS NOT NULL AND directory_url != '')
    ''')
    dir_fixed = cur.rowcount
    conn.commit()
    print(f"Fixed {dir_fixed} additional entries using directory_url fallback in DB")

    # Stats
    cur.execute('SELECT COUNT(*) FROM organizations')
    count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM organizations WHERE website IS NOT NULL AND website != ""')
    with_web = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM organizations WHERE website IS NULL OR website = ""')
    without_web = cur.fetchone()[0]
    conn.close()

    print(f"\nDatabase stats after update:")
    print(f"  Total: {count}")
    print(f"  With website: {with_web} ({with_web/count*100:.1f}%)")
    print(f"  Without website: {without_web} ({without_web/count*100:.1f}%)")


def regenerate_geojson():
    """Run the existing convert_to_geojson.py script."""
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'convert_to_geojson.py')
    result = os.system(f'{sys.executable} {script_path}')
    if result != 0:
        print("WARNING: GeoJSON regeneration may have failed")
    else:
        print("GeoJSON regenerated successfully")


def update_csv(entries):
    """Update CSV file from cleaned entries."""
    import csv
    if not entries:
        return
    keys = list(entries[0].keys())
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(entries)
    print(f"Updated CSV with {len(entries)} records")


def main():
    print("=" * 60)
    print("Data Cleaning & Website Enrichment")
    print("=" * 60)

    # Load data
    entries = load_json_data()
    print(f"Loaded {len(entries)} entries from JSON")

    # Clean
    entries = remove_low_quality(entries)
    entries, website_updates = fix_website_fallbacks(entries)

    # Stats
    total = len(entries)
    with_website = sum(1 for e in entries if e.get('website'))
    without_website = total - with_website
    print(f"\nFinal stats:")
    print(f"  Total: {total}")
    print(f"  With website: {with_website} ({with_website/total*100:.1f}%)")
    print(f"  Without website: {without_website} ({without_website/total*100:.1f}%)")

    # Save
    save_json_data(entries)
    update_csv(entries)
    update_db_in_place(entries, website_updates)
    regenerate_geojson()

    print("\nDone!")


if __name__ == '__main__':
    main()
