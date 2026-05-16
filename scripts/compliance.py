"""
GDPR/CCPA Compliance: Data enrichment retention, anonymization, and deletion utilities.
"""
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = "/opt/volunteer-map/backend/organizations.db"

# Retention period: 180 days
MAX_RETENTION_DAYS = 180

def anonymize_ip(ip):
    """Truncate last octet for privacy: 8.8.8.8 → 8.8.8.0"""
    if not ip or ip in ("127.0.0.1", "::1", "0.0.0.0"):
        return ip
    parts = ip.split(".")
    if len(parts) == 4:
        parts[3] = "0"
        return ".".join(parts)
    return ip

def delete_enriched_ip(ip):
    """Delete all enrichment records for a given IP (right to erasure)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM ip_enrichments WHERE ip = ?", (ip,))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0

def delete_all_enrichments():
    """Delete ALL enrichment records."""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM ip_enrichments").fetchone()[0]
    conn.execute("DELETE FROM ip_enrichments")
    conn.commit()
    conn.close()
    return count

def purge_old_records(days=MAX_RETENTION_DAYS):
    """Delete enrichment records older than `days` days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM ip_enrichments WHERE enriched_at < ?", (cutoff,)).fetchone()[0]
    conn.execute("DELETE FROM ip_enrichments WHERE enriched_at < ?", (cutoff,))
    conn.commit()
    conn.close()
    return count

def export_enrichments_csv():
    """Export all enrichments as CSV for data portability requests."""
    import csv, io
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM ip_enrichments ORDER BY enriched_at DESC").fetchall()
    conn.close()
    
    output = io.StringIO()
    if rows:
        writer = csv.writer(output)
        writer.writerow([d[0] for d in conn.execute("PRAGMA table_info(ip_enrichments)").fetchall()])
        for row in rows:
            writer.writerow(row)
    return output.getvalue()

def get_stats():
    """Get compliance statistics."""
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM ip_enrichments").fetchone()[0]
    
    # Age of oldest record
    oldest = conn.execute("SELECT MIN(enriched_at) FROM ip_enrichments").fetchone()[0]
    
    # Age of newest record
    newest = conn.execute("SELECT MAX(enriched_at) FROM ip_enrichments").fetchone()[0]
    
    # Count of records older than 90 days
    cutoff_90 = (datetime.now() - timedelta(days=90)).isoformat()
    over_90 = conn.execute("SELECT COUNT(*) FROM ip_enrichments WHERE enriched_at < ?", (cutoff_90,)).fetchone()[0]
    
    conn.close()
    
    return {
        "total_enriched": total,
        "oldest_record": oldest,
        "newest_record": newest,
        "records_over_90_days": over_90,
        "max_retention_days": MAX_RETENTION_DAYS,
        "auto_purge_schedule": "daily at 4:00 AM (via Matomo maintenance cron)",
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "purge":
        purged = purge_old_records()
        print(f"Purged {purged} records older than {MAX_RETENTION_DAYS} days.")
    elif len(sys.argv) > 2 and sys.argv[1] == "delete":
        deleted = delete_enriched_ip(sys.argv[2])
        print(f"Deleted records for {sys.argv[2]}: {deleted}")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
    else:
        print("Usage: python3 compliance.py [purge|delete <ip>|stats]")
