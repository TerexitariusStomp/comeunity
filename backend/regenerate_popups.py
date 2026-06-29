#!/usr/bin/env python3
"""Regenerate popup_html for every organization from the current description.

Run this after enriching descriptions so the map popups match the new text.
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from convert_to_geojson import row_to_popup

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "organizations.db")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, description, website, email, phone,
               address, city, region, country, postal_code,
               latitude, longitude, location, source,
               accepts_volunteers, accepts_visitors,
               accepts_shortterm, accepts_longterm, has_jobs
        FROM organizations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """).fetchall()

    updated = 0
    for row in rows:
        org = dict(row)
        popup = row_to_popup(org)
        conn.execute("UPDATE organizations SET popup_html = ? WHERE id = ?", (popup, org["id"]))
        updated += 1

    conn.commit()
    conn.close()
    print(f"Regenerated popup_html for {updated} organizations")


if __name__ == "__main__":
    main()
