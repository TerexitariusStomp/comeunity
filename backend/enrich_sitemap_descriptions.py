#!/usr/bin/env python3
"""Enrich ecovillage descriptions by fetching sitemap.xml and website content.

Uses Jina Reader (https://r.jina.ai/) for content extraction and direct HTTP for
sitemap discovery. Updates SQLite, then emits a D1-ready SQL file for the
organizations table. Re-runs are resume-safe via a JSON checkpoint.

Usage:
    cd /home/user/volunteer-map
    python backend/enrich_sitemap_descriptions.py --limit 10 --dry-run
    python backend/enrich_sitemap_descriptions.py --limit 100
    python backend/enrich_sitemap_descriptions.py
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "organizations.db")
CHECKPOINT_PATH = os.path.join(BASE_DIR, "backend", "enrich_sitemap_checkpoint.json")
D1_SQL_PATH = os.path.join(BASE_DIR, "d1-organizations-enriched.sql")

# How many pages per site to read from the sitemap (limit to avoid huge sites)
MAX_SITEMAP_URLS = 4
# Timeout for Jina reader requests
JINA_TIMEOUT = 20
# Sleep between requests. Requests fan out across many different domains, so a
# short delay is polite without making the full 1k+ run unreasonably slow.
REQUEST_DELAY = 0.2
# Max chars to store per org description
MAX_DESC_CHARS = 2000

# Sitemap discovery paths to try, relative to origin
SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemap.php",
]


def load_checkpoint():
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"done_ids": [], "stats": {"enriched": 0, "errors": 0, "skipped": 0}}


def save_checkpoint(done_ids, stats):
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump({"done_ids": sorted(set(done_ids)), "stats": stats}, f, indent=2)


def normalize_url(url):
    if not url:
        return None
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def get_origin(url):
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_url(url, timeout=10, headers=None):
    """Fetch raw HTML/text with a browser-like UA."""
    h = headers or {}
    h.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    try:
        resp = requests.get(url, timeout=timeout, headers=h, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        return resp.text
    except Exception:
        return None


def fetch_jina(url, timeout=JINA_TIMEOUT):
    """Use Jina Reader to extract readable Markdown from a URL."""
    jina_url = f"https://r.jina.ai/{url}"
    try:
        resp = requests.get(
            jina_url, timeout=timeout, headers={"Accept": "text/plain"}
        )
        if resp.status_code != 200:
            return None
        text = resp.text.strip()
        # Jina often prefixes with metadata; strip it
        idx = text.find("Markdown Content:")
        if idx != -1:
            text = text[idx + len("Markdown Content:") :].strip()
        return text
    except Exception:
        return None


def discover_sitemap(site_url):
    """Return the URL of a valid sitemap for the site, or None."""
    origin = get_origin(site_url)
    # Try robots.txt first
    robots_text = fetch_url(f"{origin}/robots.txt", timeout=6)
    if robots_text:
        for match in re.finditer(r"Sitemap:\s*(\S+)", robots_text, re.IGNORECASE):
            sitemap_url = match.group(1)
            if fetch_url(sitemap_url, timeout=6):
                return sitemap_url

    # Try common paths
    for path in SITEMAP_PATHS:
        sitemap_url = f"{origin}{path}"
        if fetch_url(sitemap_url, timeout=6):
            return sitemap_url

    # Try sitemap linked in homepage HTML
    html = fetch_url(site_url, timeout=8)
    if html:
        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("link", rel="sitemap"):
            href = link.get("href")
            if href:
                href = urllib.parse.urljoin(site_url, href)
                if fetch_url(href, timeout=6):
                    return href

    return None


def parse_sitemap_urls(sitemap_url):
    """Extract page URLs from a sitemap XML, with basic recursion for indexes."""
    text = fetch_url(sitemap_url, timeout=10)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except Exception:
        return []

    # Handle both sitemapindex and urlset
    urls = []
    if root.tag.endswith("sitemapindex"):
        for sitemap in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
            loc = sitemap.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                urls.extend(parse_sitemap_urls(loc.text))
                if len(urls) >= MAX_SITEMAP_URLS:
                    break
    else:
        for url in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if loc is not None and loc.text:
                urls.append(loc.text)
                if len(urls) >= MAX_SITEMAP_URLS:
                    break

    return urls[:MAX_SITEMAP_URLS]


def extract_page_text(url):
    """Return readable text from a URL, preferring Jina Reader, falling back to bs4."""
    text = fetch_jina(url)
    if text and len(text.strip()) > 80:
        return text

    html = fetch_url(url, timeout=8)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    # Remove script/style/nav/footer/aside
    for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)
    return text if len(text) > 80 else None


def clean_text(text):
    """Collapse whitespace and truncate."""
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    # Remove URLs that are just noise in descriptions
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_DESC_CHARS]


def is_low_quality(text):
    """Heuristic to reject generic/error pages."""
    if not text:
        return True
    lower = text.lower()
    bad_phrases = [
        "404 not found",
        "403 forbidden",
        "page not found",
        "error 404",
        "error 403",
        "access denied",
        "under construction",
        "just another wordpress site",
    ]
    return any(p in lower for p in bad_phrases)


def enrich_org(org_id, name, website, direct_website, directory_url, existing_desc):
    """Return a richer description for one org, or None if no improvement."""
    # Prefer the real website; fall back to directory URL if no direct website
    site_url = normalize_url(direct_website or website or directory_url)
    if not site_url:
        return None

    # Don't waste time on directory listing pages that are already the source
    if "ic.org/directory/" in site_url or "ecovillage.org/" in site_url:
        # We already have directory data; try to use it if description is poor
        if existing_desc and len(existing_desc) > 100 and "is an intentional community" not in existing_desc:
            return None
        site_url = normalize_url(direct_website or website)
        if not site_url or "ic.org" in site_url or "ecovillage.org" in site_url:
            return None

    sitemap_url = discover_sitemap(site_url)
    page_texts = []

    if sitemap_url:
        page_urls = parse_sitemap_urls(sitemap_url)
        for page_url in page_urls:
            page_text = extract_page_text(page_url)
            if page_text and not is_low_quality(page_text):
                page_texts.append(page_text)
            time.sleep(REQUEST_DELAY)

    # Fallback: homepage if sitemap failed or yielded nothing
    if not page_texts:
        homepage_text = extract_page_text(site_url)
        if homepage_text and not is_low_quality(homepage_text):
            page_texts.append(homepage_text)
        time.sleep(REQUEST_DELAY)

    if not page_texts:
        return None

    combined = "\n\n".join(page_texts)
    cleaned = clean_text(combined)
    if not cleaned or len(cleaned) < 120:
        return None

    # Avoid replacing a good existing description with a worse one
    if existing_desc and len(existing_desc) > len(cleaned) and "is an intentional community" not in existing_desc:
        return None

    # Keep a hint of the original name/location so the embedding still has identity
    if "is an intentional community" in (existing_desc or "") and not cleaned.lower().startswith(name.lower()):
        cleaned = f"{name}. {cleaned}"

    return cleaned


def get_orgs_to_process(conn, limit=None, source=None):
    """Return orgs that need richer descriptions and have a URL to scrape."""
    sql = """
        SELECT id, name, website, direct_website, directory_url, description
        FROM organizations
        WHERE (website IS NOT NULL AND website != '')
           OR (direct_website IS NOT NULL AND direct_website != '')
           OR (directory_url IS NOT NULL AND directory_url != '')
    """
    params = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    # Prefer orgs with short / generic descriptions first
    sql += " ORDER BY CASE WHEN description IS NULL OR description = '' OR description LIKE '%is an intentional community%' THEN 0 ELSE 1 END, id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    cur = conn.execute(sql, params)
    return cur.fetchall()


def escape_sql(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    return "'" + str(val).replace("'", "''") + "'"


def write_d1_upsert_sql(conn, outpath=D1_SQL_PATH):
    """Write a full D1 upsert file for the organizations table after enrichment."""
    cols = [
        "id", "name", "description", "organization_type", "popup_html", "website",
        "email", "phone", "address", "city", "region", "country", "postal_code",
        "latitude", "longitude", "location", "source", "accepts_volunteers",
        "accepts_visitors", "accepts_shortterm", "accepts_longterm", "has_jobs",
        "has_stays", "has_events", "last_updated", "created_at",
        "directory_url", "direct_website", "last_scrape_attempt",
        "being_processed_since", "events_scraped_at", "jobs_rescraped",
        "jobs_being_processed_since",
    ]
    col_list = ", ".join(cols)
    updates = ", ".join(f"{col}=excluded.{col}" for col in cols if col != "id")

    rows = conn.execute(f"SELECT {col_list} FROM organizations").fetchall()
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(f"-- organizations: {len(rows)} rows (enriched via sitemap)\n")
        for row in rows:
            values = ", ".join(escape_sql(row[col]) for col in cols)
            f.write(
                f"INSERT INTO organizations ({col_list}) VALUES ({values}) ON CONFLICT(id) DO UPDATE SET {updates};\n"
            )
    print(f"Wrote D1 upsert SQL to {outpath} ({len(rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description="Enrich org descriptions from website sitemaps")
    parser.add_argument("--limit", type=int, default=None, help="Process only N orgs")
    parser.add_argument("--source", type=str, default=None, help="Filter by source (e.g. IC.org)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    ckpt = load_checkpoint()
    done_ids = set(ckpt["done_ids"])
    stats = dict(ckpt.get("stats", {"enriched": 0, "errors": 0, "skipped": 0}))

    orgs = get_orgs_to_process(conn, limit=args.limit, source=args.source)
    orgs = [o for o in orgs if o["id"] not in done_ids]
    print(f"Found {len(orgs)} orgs to process (skipping {len(done_ids)} already done)")
    if not orgs:
        conn.close()
        return

    def process_one(row):
        try:
            new_desc = enrich_org(
                row["id"], row["name"], row["website"], row["direct_website"],
                row["directory_url"], row["description"],
            )
            if new_desc:
                return ("enriched", row["id"], new_desc)
            return ("skipped", row["id"], None)
        except Exception as e:
            return ("error", row["id"], str(e))

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one, o): o for o in orgs}
        for i, fut in enumerate(as_completed(futures)):
            org = futures[fut]
            status, org_id, payload = fut.result()
            if status == "enriched":
                if not args.dry_run:
                    conn.execute(
                        "UPDATE organizations SET description = ? WHERE id = ?",
                        (payload, org_id),
                    )
                    conn.commit()
                stats["enriched"] += 1
                done_ids.add(org_id)
                print(f"  [{i+1}/{len(orgs)}] Enriched {org['name'][:50]} ({len(payload)} chars)")
            elif status == "error":
                stats["errors"] += 1
                done_ids.add(org_id)
                print(f"  [{i+1}/{len(orgs)}] Error {org['name'][:50]}: {payload}")
            else:
                stats["skipped"] += 1
                done_ids.add(org_id)
                print(f"  [{i+1}/{len(orgs)}] Skipped {org['name'][:50]}")
            save_checkpoint(list(done_ids), stats)

    if not args.dry_run:
        write_d1_upsert_sql(conn)

    print(f"\nDone. Enriched: {stats['enriched']}  Skipped: {stats['skipped']}  Errors: {stats['errors']}")
    conn.close()


if __name__ == "__main__":
    main()
