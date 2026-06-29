#!/usr/bin/env python3
"""Fill empty website fields from directory_url where the URL is unique and related.

This gives every org a clickable link without creating duplicate website URLs.
"""
import sqlite3

DB_PATH = "/home/user/volunteer-map/backend/organizations.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # URLs already used as website
    used_websites = set(
        r[0] for r in cur.execute(
            "SELECT DISTINCT website FROM organizations WHERE website IS NOT NULL AND website != ''"
        ).fetchall()
    )

    # Orgs with empty website but non-empty directory_url
    rows = cur.execute(
        """
        SELECT id, name, directory_url
        FROM organizations
        WHERE (website IS NULL OR website = '')
          AND (directory_url IS NOT NULL AND directory_url != '')
        ORDER BY id
        """
    ).fetchall()

    filled = 0
    skipped_dup = 0
    for row in rows:
        url = row["directory_url"].strip()
        if url in used_websites:
            skipped_dup += 1
            continue
        cur.execute(
            "UPDATE organizations SET website = ? WHERE id = ?",
            (url, row["id"]),
        )
        used_websites.add(url)
        filled += 1

    conn.commit()

    # Report remaining without website
    remaining = cur.execute(
        "SELECT COUNT(*) FROM organizations WHERE website IS NULL OR website = ''"
    ).fetchone()[0]

    print(f"Filled {filled} websites from directory_url")
    print(f"Skipped {skipped_dup} because directory_url already used as website")
    print(f"Remaining without website: {remaining}")

    conn.close()


if __name__ == "__main__":
    main()
