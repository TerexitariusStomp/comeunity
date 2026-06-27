#!/usr/bin/env python3
"""Scrape job/volunteer boards from organization websites.

Checks common paths like /jobs, /careers, /volunteer, /get-involved, /join-us
and extracts job posting information.
"""
import sqlite3
import json
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
from datetime import datetime

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'

# Common paths where job/volunteer info might be found
JOB_PATHS = [
    'jobs', 'careers', 'work-with-us', 'employment', 'opportunities',
    'volunteer', 'volunteers', 'volunteering', 'get-involved', 'join-us',
    'recruitment', 'positions', 'vacancies', 'team', 'about/jobs',
    'about/careers', 'about/volunteer', 'community/jobs', 'participate',
    'live-here', 'membership', 'apply', 'join', 'work', 'internships',
    'internship', 'apprenticeship', 'apprenticeships', 'wwoof', 'help',
    'donate/time', 'become-a-member', 'residents', 'residency',
]


class TextExtractor(HTMLParser):
    """Extract visible text from HTML."""
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer'}
        self._skip_depth = 0
        self._current_tag = None

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        if tag in self.skip_tags:
            self._skip_depth += 1
        if tag == 'a':
            attrs_dict = dict(attrs)
            if 'href' in attrs_dict:
                self.text.append(f" [LINK:{attrs_dict['href']}]")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self._skip_depth -= 1
        if self._skip_depth <= 0:
            self.text.append("\n")

    def handle_data(self, data):
        if self._skip_depth <= 0:
            stripped = data.strip()
            if stripped:
                self.text.append(stripped)

    def get_text(self):
        raw = ' '.join(self.text)
        # Clean up extra whitespace
        return re.sub(r'\s+', ' ', raw).strip()


def fetch_url(url, timeout=15):
    """Fetch URL and return (status, html, final_url)."""
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        html = resp.read().decode('utf-8', errors='replace')
        return resp.status, html, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, None, url
    except Exception as e:
        return -1, None, url


def check_job_page(base_url):
    """Check if a website has a job/volunteer page and return (found, url, text)."""
    if not base_url:
        return False, None, None
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url
    base_url = base_url.rstrip('/')

    for path in JOB_PATHS:
        url = f"{base_url}/{path}"
        status, html, final_url = fetch_url(url)
        if status == 200 and html:
            # Check if page actually has job-related content
            lower_html = html.lower()
            # Look for job-related terms (not just nav links)
            job_terms = [
                'volunteer', 'volunteering', 'job opening', 'we are hiring',
                'join our team', 'work with us', 'positions available',
                'apply now', 'current openings', 'opportunities',
                'apprenticeship', 'internship', 'wwoof', 'work exchange',
                'residency', 'live with us', 'become a member',
            ]
            # Extract text and search
            extractor = TextExtractor()
            try:
                extractor.feed(html)
                text = extractor.get_text()
                text_lower = text.lower()
                score = sum(1 for t in job_terms if t in text_lower)
                # Need at least 2 job terms AND reasonable text length
                if score >= 2 and len(text) > 200:
                    return True, final_url, text
            except Exception:
                pass
        time.sleep(0.3)  # Be polite
    return False, None, None


def extract_job_listings(text, page_url):
    """Try to extract individual job/volunteer listings from page text.
    Returns list of dicts with title, description.
    """
    listings = []
    # Try to find sections that look like job listings
    # Look for patterns like headers followed by paragraphs
    lines = text.split('\n')
    current_title = None
    current_desc = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Heuristic: short lines that look like titles (capitalized, no periods)
        if len(line) < 100 and (line.isupper() or line.istitle() or line.endswith(':')):
            if current_title and current_desc:
                desc = ' '.join(current_desc)
                if len(desc) > 50:
                    listings.append({
                        'title': current_title[:200],
                        'description': desc[:1000],
                    })
            current_title = line
            current_desc = []
        else:
            current_desc.append(line)

    if current_title and current_desc:
        desc = ' '.join(current_desc)
        if len(desc) > 50:
            listings.append({
                'title': current_title[:200],
                'description': desc[:1000],
            })

    # If no structured listings, treat the whole page as one opportunity
    if not listings and len(text) > 200:
        # Extract first paragraph as title, rest as description
        sentences = text.split('. ')
        title = sentences[0][:200] if sentences else 'Volunteer/Work Opportunity'
        listings.append({
            'title': title,
            'description': text[:2000],
        })

    return listings


def process_batch(limit=50, offset=0):
    """Process a batch of organizations."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
        SELECT id, name, website 
        FROM organizations 
        WHERE website IS NOT NULL AND website != ''
        AND (has_jobs IS NULL OR has_jobs = 0)
        ORDER BY id
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    orgs = cur.fetchall()

    if not orgs:
        print("No more organizations to process.")
        conn.close()
        return 0

    found_count = 0
    for org_id, name, website in orgs:
        print(f"Checking: {name} -> {website}")
        has_jobs, job_url, text = check_job_page(website)

        if has_jobs and text:
            found_count += 1
            print(f"  FOUND job page: {job_url}")

            # Update organization
            cur.execute('''
                UPDATE organizations 
                SET has_jobs = 1 
                WHERE id = ?
            ''', (org_id,))

            # Extract and store listings
            listings = extract_job_listings(text, job_url)
            for listing in listings:
                cur.execute('''
                    INSERT INTO volunteer_opportunities 
                    (organization_id, title, description, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (org_id, listing['title'], listing['description'],
                      'volunteer/work', datetime.now().isoformat()))
        else:
            cur.execute('''
                UPDATE organizations 
                SET has_jobs = 0 
                WHERE id = ?
            ''', (org_id,))

        conn.commit()
        time.sleep(0.5)  # Rate limiting

    conn.close()
    return found_count


if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    print(f"Processing batch: limit={limit}, offset={offset}")
    found = process_batch(limit, offset)
    print(f"Found {found} organizations with job boards in this batch.")
