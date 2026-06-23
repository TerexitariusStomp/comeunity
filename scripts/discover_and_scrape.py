#!/usr/bin/env python3
"""Parallel-safe discover & scrape for job listings and stay booking pages.

Uses claim-based batching with SQLite BEGIN IMMEDIATE + last_scrape_attempt
so multiple workers can run in parallel without overlap.

Usage:
  # Run 1 worker (background):
  nohup python3 -u scripts/discover_and_scrape.py > /tmp/scrape_worker_1.log 2>&1 &

  # Run multiple workers in parallel:
  nohup python3 -u scripts/discover_and_scrape.py > /tmp/scrape_worker_1.log 2>&1 &
  nohup python3 -u scripts/discover_and_scrape.py > /tmp/scrape_worker_2.log 2>&1 &
  nohup python3 -u scripts/discover_and_scrape.py > /tmp/scrape_worker_3.log 2>&1 &
"""
import sqlite3
import re
import sys
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'
BATCH_SIZE = 20

JOB_PATHS = [
    'jobs', 'careers', 'work-with-us', 'employment', 'opportunities',
    'volunteer', 'volunteers', 'volunteering', 'get-involved', 'join-us',
    'recruitment', 'positions', 'vacancies', 'team', 'about/jobs',
    'about/careers', 'about/volunteer', 'participate', 'live-here',
    'membership', 'apply', 'join', 'work', 'internships', 'internship',
    'apprenticeship', 'apprenticeships', 'wwoof', 'help',
]

STAY_PATHS = [
    'stay', 'stays', 'accommodation', 'accommodations', 'rooms', 'room',
    'book', 'booking', 'book-a-stay', 'book-now', 'reserve', 'reservation',
    'visit', 'visiting', 'guest', 'guests', 'guesthouse', 'camping', 'camp',
    'glamping', 'tent', 'retreat', 'retreats', 'getaway', 'overnight',
    'lodging', 'hebergement', 'logement', 'gite', 'chambre',
    'chambres-dhotes', 'tarif', 'tarifs', 'prices', 'rates',
]

JOB_KW = ['job', 'volunteer', 'apply', 'position', 'career', 'role',
          'opening', 'hiring', 'join our team', 'work with us', 'intern']
STAY_KW = ['stay', 'accommodation', 'room', 'book', 'guest', 'night',
           'reserve', 'check-in', 'check-out', 'tarif', 'price']


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


def discover_page(base_url, paths, keywords, max_checks=8):
    if not base_url:
        return None, None
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url
    base_url = base_url.rstrip('/')
    checked = 0
    for p in paths:
        status, html, final = fetch(f"{base_url}/{p}")
        checked += 1
        if status == 200 and html:
            low = html.lower()
            if any(k in low for k in keywords):
                return final, html
        time.sleep(0.15)
        if checked >= max_checks:
            break
    return None, None


def extract_jobs(html, org_name):
    ext = TextExtractor()
    try:
        ext.feed(html[:400000])
    except Exception:
        pass
    text = ext.get_text()
    if len(text) < 200:
        return []

    raw_blocks = re.split(r'(?=\b[A-Z][A-Z\s&\-/,]{5,80}[A-Z]\b)', text)
    job_terms = ['volunteer', 'intern', 'apprentice', 'position', 'opening',
                 'job', 'role', 'opportunity', 'hiring', 'apply', 'seeking']
    listings = []

    for block in raw_blocks:
        block = block.strip()
        if len(block) < 120:
            continue
        score = sum(1 for t in job_terms if t in block.lower())
        if score >= 2:
            lines = re.split(r'[.!?]\s+', block)
            title = lines[0][:150].strip()
            title = re.sub(r'\[LINK:[^\]]+\]', '', title)
            if len(title) < 5:
                title = f"Opportunity at {org_name}"
            low = block.lower()
            role = 'volunteer'
            if any(x in low for x in ['intern', 'internship']):
                role = 'internship'
            elif any(x in low for x in ['apprentice', 'apprenticeship']):
                role = 'apprenticeship'
            elif any(x in low for x in ['salary', 'full-time', 'full time', 'paid']):
                role = 'paid_job'
            listings.append({'title': title, 'description': block[:2500], 'role': role})

    if not listings:
        score = sum(1 for t in job_terms if t in text.lower())
        if score >= 3 and len(text) > 300:
            sentences = re.split(r'[.!?]\s+', text)
            title = sentences[0][:150] if sentences else f"Opportunities at {org_name}"
            title = re.sub(r'\[LINK:[^\]]+\]', '', title)
            listings.append({'title': title, 'description': text[:2500], 'role': 'volunteer'})
    return listings


def analyze_booking(html, url):
    has_form = bool(re.search(r'<form\b', html, re.I))
    has_iframe = bool(re.search(r'<iframe\b', html, re.I))
    has_email = bool(re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html))
    has_phone = bool(re.search(r'[\+\(]?[0-9]{1,4}[\)]?[-.\s]?[0-9]{1,4}[-.\s]?[0-9\s]{4,}', html))
    has_calendar = any(x in html.lower() for x in ['calendly', 'schedule', 'pick a date'])

    ext_links = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html):
        href = m.group(1).lower()
        if any(x in href for x in ['booking.com', 'airbnb', 'expedia', 'hotels.com',
                                     'checkfront', 'rezdy', 'fareharbor', 'peek']):
            ext_links.append(href)

    ext = TextExtractor()
    try:
        ext.feed(html[:300000])
    except Exception:
        pass
    text = ext.get_text().lower()
    kw_score = sum(1 for kw in ['book now', 'reserve', 'check availability',
                                'check-in', 'check-out', 'nightly rate', 'per night']
                   if kw in text)

    if has_form and kw_score >= 2:
        btype = 'direct_form'
    elif has_iframe or ext_links:
        btype = 'external_widget'
    elif has_calendar:
        btype = 'calendar_tool'
    elif has_email or has_phone:
        btype = 'email_phone' if kw_score >= 1 else 'unknown'
    else:
        btype = 'unknown'

    analysis = {
        'url': url, 'has_form': has_form, 'has_iframe': has_iframe,
        'has_email': has_email, 'has_phone': has_phone,
        'has_calendar': has_calendar, 'external_links': ext_links[:5],
        'booking_keywords': kw_score,
    }
    return btype, analysis


def claim_batch(conn, batch_size):
    """Claim a batch of unprocessed orgs using exclusive transaction."""
    cur = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')
    cur.execute('''
        SELECT id, name, website FROM organizations
        WHERE website IS NOT NULL AND website != ''
          AND last_scrape_attempt IS NULL
        ORDER BY id
        LIMIT ?
    ''', (batch_size,))
    rows = cur.fetchall()
    now = datetime.now().isoformat()
    for org_id, _, _ in rows:
        cur.execute('UPDATE organizations SET last_scrape_attempt = ? WHERE id = ?', (now, org_id))
    conn.commit()
    return rows


def process_org(conn, org_id, name, website):
    """Process one org: discover jobs and stays, store results."""
    cur = conn.cursor()

    # Jobs
    job_url, job_html = discover_page(website, JOB_PATHS, JOB_KW, max_checks=8)
    if job_url and job_html:
        listings = extract_jobs(job_html, name)
        if listings:
            cur.execute('DELETE FROM volunteer_opportunities WHERE organization_id = ?', (org_id,))
            for li in listings:
                cur.execute('''
                    INSERT INTO volunteer_opportunities
                    (organization_id, title, description, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (org_id, li['title'], li['description'], li['role'], datetime.now().isoformat()))
            has_jobs = 1
        else:
            has_jobs = 0
    else:
        has_jobs = 0

    # Stays
    stay_url, stay_html = discover_page(website, STAY_PATHS, STAY_KW, max_checks=8)
    if stay_url and stay_html:
        btype, analysis = analyze_booking(stay_html, stay_url)
        desc = TextExtractor()
        try:
            desc.feed(stay_html[:300000])
        except Exception:
            pass
        desc_text = desc.get_text()[:2000]
        cur.execute('''
            INSERT INTO stays (organization_id, title, description, stay_type, booking_type, booking_analysis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (org_id, f"Stay at {name}", desc_text, 'accommodation',
              btype, str(analysis), datetime.now().isoformat()))
        has_stays = 1
    else:
        has_stays = 0

    # Update flags
    cur.execute('''
        UPDATE organizations SET has_jobs = ?, has_stays = ? WHERE id = ?
    ''', (has_jobs, has_stays, org_id))
    conn.commit()

    return has_jobs, has_stays


def worker_loop(batch_size=BATCH_SIZE):
    """Run indefinitely, claiming and processing batches until exhausted."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute('PRAGMA journal_mode=WAL')

    total_processed = 0
    total_jobs = 0
    total_stays = 0

    while True:
        rows = claim_batch(conn, batch_size)
        if not rows:
            print("No more unprocessed organizations. Worker done.")
            break

        for org_id, name, website in rows:
            try:
                has_jobs, has_stays = process_org(conn, org_id, name, website)
                total_processed += 1
                if has_jobs:
                    total_jobs += 1
                if has_stays:
                    total_stays += 1
                print(f"[{org_id}] {name[:50]} | jobs={has_jobs} stays={has_stays}")
            except Exception as e:
                print(f"[{org_id}] {name[:50]} ERROR: {e}")
                conn.rollback()
            time.sleep(0.3)

    conn.close()
    print(f"\nWorker finished: {total_processed} orgs, {total_jobs} job pages, {total_stays} stay pages")


if __name__ == '__main__':
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else BATCH_SIZE
    worker_loop(batch_size)
