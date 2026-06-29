#!/usr/bin/env python3
"""Clean up duplicate / incorrect website URLs in the organizations table.

Targets:
- Generic URLs used as direct_website (wordpress.org, creativecommons.org, etc.)
- Malformed URLs with duplicated fragments
- Directory URLs misplaced in website/direct_website
"""
import sqlite3
import re

DB_PATH = "/home/user/volunteer-map/backend/organizations.db"

# URLs that are clearly not a community's own website
BAD_DIRECT_WEBSITES = {
    "https://wordpress.org",
    "http://wordpress.org",
    "http://creativecommons.org/licenses/by-nc-sa/4.0",
    "https://creativecommons.org/licenses/by-nc-sa/4.0",
    "https://ecovillage.org",
    "http://ecovillage.org",
    "https://nextgen-ecovillage.org",
    "http://nextgen-ecovillage.org",
    "https://gofund.me",
    "http://gofund.me",
}


def normalize_url(url):
    if not url:
        return None
    url = url.strip()
    # Fix duplicated trailing fragments like "http://x/yhttp://x/y"
    url = re.sub(r"(https?://[^\s]+)\1+", r"\1", url)
    # Fix trailing path repetition
    url = re.sub(r"(https?://[^\s]+)\1$", r"\1", url)
    return url if url.startswith("http") else None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Clear bad direct_website values
    for bad in BAD_DIRECT_WEBSITES:
        cur.execute("UPDATE organizations SET direct_website = NULL WHERE direct_website = ?", (bad,))
        cur.execute("UPDATE organizations SET website = NULL WHERE website = ?", (bad,))

    # 2. Fix malformed URLs with duplicated fragments
    cur.execute("SELECT id, direct_website, website FROM organizations")
    fixed = 0
    for row in cur.fetchall():
        new_direct = normalize_url(row["direct_website"])
        new_website = normalize_url(row["website"])
        if new_direct != row["direct_website"] or new_website != row["website"]:
            cur.execute(
                "UPDATE organizations SET direct_website = ?, website = ? WHERE id = ?",
                (new_direct, new_website, row["id"]),
            )
            fixed += 1

    # 3. If website and direct_website are identical, keep one
    cur.execute(
        "UPDATE organizations SET direct_website = NULL WHERE website = direct_website AND direct_website IS NOT NULL"
    )

    conn.commit()

    # Report remaining duplicates
    cur.execute("""
        SELECT website, COUNT(DISTINCT id) as cnt
        FROM organizations
        WHERE website IS NOT NULL AND website != ''
        GROUP BY website
        HAVING cnt > 1
        ORDER BY cnt DESC
    """)
    dups = cur.fetchall()
    print(f"Cleared bad URLs and fixed {fixed} malformed URLs")
    print(f"Remaining duplicate website URLs: {len(dups)}")
    for row in dups[:20]:
        print(f"  {row['cnt']}x {row['website']}")

    conn.close()


if __name__ == "__main__":
    main()
