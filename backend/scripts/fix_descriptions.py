"""
Fix descriptions: extract popup HTML from geo_data.json and store both
popup_html and proper description text in the database.
"""
import json
import re
import sqlite3

DB_PATH = "/opt/volunteer-map/backend/organizations.db"
GEO_DATA = "/root/.hermes/volunteer-map/geo_data.json"

def extract_description_text(html):
    """Extract clean description text from popup HTML."""
    # Try to get text from <p> tags first
    p_match = re.search(r'<p>(.*?)</p>', html, re.DOTALL)
    if p_match:
        text = re.sub(r'<[^>]+>', ' ', p_match.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        if text and not text.startswith('Title:') and 'Global Ecovillage Network' not in text:
            return text

    # Fallback: get first meaningful text after <strong> tag
    match = re.search(r'</strong>(.*?)(?:<br>|<span|<div|<a|<small|$)', html, re.DOTALL)
    if match:
        text = re.sub(r'<[^>]+>', ' ', match.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        if text and not text.startswith('Title:') and 'Global Ecovillage Network' not in text:
            return text

    return ''


def main():
    # Load geo data
    with open(GEO_DATA) as f:
        geo_data = json.load(f)

    print(f"Loaded {len(geo_data)} entries from geo_data.json")

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Add popup_html column if it doesn't exist
    cursor.execute("PRAGMA table_info(organizations)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'popup_html' not in columns:
        cursor.execute("ALTER TABLE organizations ADD COLUMN popup_html TEXT")
        print("Added popup_html column")

    # Build lookup by name from geo_data
    geo_lookup = {}
    for entry in geo_data:
        name = entry['properties']['name']
        popup_html = entry['properties'].get('popup', '')
        desc_text = extract_description_text(popup_html)
        geo_lookup[name] = {
            'popup_html': popup_html,
            'description': desc_text
        }

    # Update database
    updated_popup = 0
    updated_desc = 0
    matched = 0

    cursor.execute("SELECT id, name, description FROM organizations")
    for row in cursor.fetchall():
        org_id, name, current_desc = row
        if name in geo_lookup:
            matched += 1
            geo = geo_lookup[name]

            # Update popup_html
            if geo['popup_html']:
                cursor.execute("UPDATE organizations SET popup_html = ? WHERE id = ?", (geo['popup_html'], org_id))
                updated_popup += 1

            # Only update description if it's empty, garbage, or missing
            if (not current_desc or ''
                or current_desc.startswith('Title:')
                or 'Global Ecovillage Network' in current_desc
                or current_desc == geo_lookup[name].get('description', '')):
                if geo['description']:
                    cursor.execute("UPDATE organizations SET description = ? WHERE id = ?", (geo['description'], org_id))
                    updated_desc += 1

    conn.commit()
    print(f"\nMatched {matched}/{matched + len(geo_data) - matched} orgs to geo_data")
    print(f"Updated popup_html: {updated_popup}")
    print(f"Updated descriptions: {updated_desc}")

    # Verify
    cursor.execute("SELECT COUNT(*) FROM organizations WHERE description IS NOT NULL AND description != '' AND description NOT LIKE 'Title:%'")
    good = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM organizations")
    total = cursor.fetchone()[0]
    print(f"\nFinal: {good}/{total} orgs with clean descriptions")

    conn.close()

if __name__ == "__main__":
    main()
