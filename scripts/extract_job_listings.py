#!/usr/bin/env python3
"""Deep scrape job listings from organizations that have job pages."""
import sqlite3
import re
import time
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self.skip_depth = 0
        self.skip_tags = {'script', 'style', 'nav'}

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth <= 0:
            s = data.strip()
            if s:
                self.chunks.append(s)

    def get_text(self):
        return re.sub(r'\s+', ' ', ' '.join(self.chunks)).strip()


def fetch(url, timeout=12):
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read().decode('utf-8', errors='replace'), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, None, url
    except Exception:
        return -1, None, url


def find_job_url(base):
    if not base:
        return None
    if not base.startswith('http'):
        base = 'https://' + base
    base = base.rstrip('/')
    paths = ['jobs', 'careers', 'volunteer', 'work-with-us', 'join-us',
             'get-involved', 'employment', 'positions', 'apply', 'volunteers']
    for p in paths:
        status, html, final = fetch(f"{base}/{p}")
        if status == 200 and html:
            low = html.lower()
            if any(k in low for k in ['job', 'volunteer', 'apply', 'position', 'career', 'role']):
                return final
        time.sleep(0.15)
    return None


def extract_listings(html, org_name):
    ext = TextExtractor()
    try:
        ext.feed(html[:500000])  # Limit to 500KB
    except Exception:
        pass
    text = ext.get_text()
    if len(text) < 200:
        return []

    # Try splitting by ALL-CAPS headings (job titles often look like this)
    # or by "Position:" / "Role:" patterns
    raw_blocks = re.split(r'(?=\b[A-Z][A-Z\s&\-/,]{5,80}[A-Z]\b)', text)

    listings = []
    job_kw = ['volunteer', 'intern', 'apprentice', 'position', 'opening',
              'job', 'role', 'opportunity', 'hiring', 'apply', 'seeking']

    for block in raw_blocks:
        block = block.strip()
        if len(block) < 120:
            continue
        score = sum(1 for kw in job_kw if kw in block.lower())
        if score >= 2:
            lines = re.split(r'[.!?]\s+', block)
            title = lines[0][:150].strip()
            title = re.sub(r'\[LINK:[^\]]+\]', '', title)
            if len(title) < 5:
                title = f"Opportunity at {org_name}"
            role = 'volunteer'
            low = block.lower()
            if any(x in low for x in ['intern', 'internship']):
                role = 'internship'
            elif any(x in low for x in ['apprentice', 'apprenticeship']):
                role = 'apprenticeship'
            elif any(x in low for x in ['salary', 'full-time', 'full time', 'paid']):
                role = 'paid_job'
            listings.append({'title': title, 'description': block[:2500], 'role': role})

    # Fallback: whole page as one listing if it looks job-related
    if not listings:
        score = sum(1 for kw in job_kw if kw in text.lower())
        if score >= 3 and len(text) > 300:
            sentences = re.split(r'[.!?]\s+', text)
            title = sentences[0][:150] if sentences else f"Opportunities at {org_name}"
            title = re.sub(r'\[LINK:[^\]]+\]', '', title)
            listings.append({'title': title, 'description': text[:2500], 'role': 'volunteer'})

    return listings


def process_batch(limit=30, offset=0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
        SELECT id, name, website FROM organizations
        WHERE has_jobs = 1
        ORDER BY id
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    orgs = cur.fetchall()

    if not orgs:
        print("No more orgs to process.")
        conn.close()
        return 0

    total = 0
    for org_id, name, website in orgs:
        sys.stdout.write(f"[{org_id}] {name[:50]}... ")
        sys.stdout.flush()

        job_url = find_job_url(website)
        if not job_url:
            print("no job page")
            continue

        status, html, final = fetch(job_url)
        if status != 200 or not html:
            print(f"fetch failed ({status})")
            continue

        listings = extract_listings(html, name)
        if listings:
            cur.execute('DELETE FROM volunteer_opportunities WHERE organization_id = ?', (org_id,))
            for li in listings:
                cur.execute('''
                    INSERT INTO volunteer_opportunities
                    (organization_id, title, description, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (org_id, li['title'], li['description'], li['role'],
                      datetime.now().isoformat()))
            conn.commit()
            total += len(listings)
            print(f"{len(listings)} listings")
        else:
            print("0 listings")

        time.sleep(0.4)

    conn.close()
    return total


if __name__ == '__main__':
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(f"Batch limit={limit} offset={offset}")
    n = process_batch(limit, offset)
    print(f"Inserted {n} listings")
