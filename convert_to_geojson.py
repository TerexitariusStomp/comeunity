#!/usr/bin/env python3
"""Convert organizations.db to GeoJSON for static GitHub Pages deployment."""
import sqlite3
import json
import os
import sys

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "backend/organizations.db"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "frontend/data/organizations.geojson"


def row_to_popup(org):
    parts = [f"<strong>{org['name']}</strong><br>"]
    desc = org.get("description") or ""
    if len(desc) > 10:
        parts.append(
            f'<p style="max-height:200px;overflow-y:auto;font-size:12px;line-height:1.4;">{desc}</p>'
        )
    badges = []
    if org.get("accepts_volunteers"):
        badges.append(
            '<span style="background:#ffc107;color:black;padding:2px 6px;border-radius:3px;margin:1px;">Volunteer</span>'
        )
    if org.get("accepts_visitors"):
        if org.get("accepts_shortterm"):
            badges.append(
                '<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Short-term</span>'
            )
        if org.get("accepts_longterm"):
            badges.append(
                '<span style="background:#17a2b8;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Long-term</span>'
            )
    if org.get("has_jobs"):
        badges.append(
            '<span style="background:#dc3545;color:white;padding:2px 6px;border-radius:3px;margin:1px;">Jobs</span>'
        )
    if badges:
        parts.append(" ".join(badges) + "<br>")

    addr = org.get("address") or ""
    if addr:
        parts.append(
            f'<div style="margin:4px 0;font-size:11px;color:#555;"><i class="fas fa-map-marker-alt" style="color:#e74c3c;"></i> {addr[:150]}</div>'
        )

    location_parts = []
    for key in ("city", "region", "country"):
        val = org.get(key)
        if val:
            location_parts.append(str(val))
    if location_parts:
        parts.append(
            f'<div style="margin:2px 0;font-size:11px;color:#666;font-style:italic;">{", ".join(location_parts)}</div>'
        )

    lines = []
    website = org.get("website") or ""
    if website:
        lines.append(
            f'<a href="{website}" target="_blank" style="color:#007bff;text-decoration:none;">Website</a>'
        )
    email = org.get("email") or ""
    if email:
        lines.append(f'<a href="mailto:{email}" style="color:#007bff;">Email</a>')
    phone = org.get("phone")
    if phone:
        lines.append(str(phone))
    if lines:
        parts.append('<div style="margin:4px 0;">' + " | ".join(lines) + "</div>")

    return " ".join(parts)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, name, description, website, email, phone,
               address, city, region, country, postal_code,
               latitude, longitude, location, source,
               accepts_volunteers, accepts_visitors,
               accepts_shortterm, accepts_longterm, has_jobs,
               popup_html
        FROM organizations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """).fetchall()
    conn.close()

    features = []
    for row in rows:
        org = dict(row)
        popup_html = org.get("popup_html") or ""
        if not popup_html:
            popup_html = row_to_popup(org)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [org["longitude"], org["latitude"]]
            },
            "properties": {
                "id": org["id"],
                "name": org["name"],
                "description": org.get("description") or "",
                "address": org.get("address") or "",
                "city": org.get("city") or "",
                "region": org.get("region") or "",
                "popup": popup_html,
                "source": org.get("source") or "",
                "country": org.get("country") or "",
                "website": org.get("website") or "",
                "acceptsVolunteers": bool(org.get("accepts_volunteers")),
                "acceptsVisitors": bool(org.get("accepts_visitors")),
                "acceptsShortterm": bool(org.get("accepts_shortterm")),
                "acceptsLongterm": bool(org.get("accepts_longterm")),
                "hasJobs": bool(org.get("has_jobs")),
            }
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"Exported {len(features)} features to {OUT_PATH}")
    size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
    print(f"File size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
