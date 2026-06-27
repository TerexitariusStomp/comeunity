#!/usr/bin/env python3
"""Enhanced re-scrape to extract structured details from job and stay pages.

For jobs: re-discovers job pages and extracts skills, commitment, emails, dates, remote options.
For stays: re-fetches booking URLs and extracts price info, better descriptions, booking details.

Uses parallel workers with claim-based batching.
"""
import sqlite3
import re
import sys
import time
import json
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime
from urllib.parse import urlparse, urljoin

DB_PATH = '/home/user/volunteer-map/backend/organizations.db'
BATCH_SIZE = 10
TIMEOUT = 8
NUM_WORKERS = 16

DOMAIN_BLACKLIST = {
    'linktr.ee', 'facebook.com', 'fb.com', 'instagram.com',
    'twitter.com', 'x.com', 'linkedin.com', 'tiktok.com',
    'youtube.com', 'youtu.be', 'vimeo.com', 'pinterest.com',
    't.me', 'telegram.me', 'wa.me', 'whatsapp.com',
    'gofundme.com', 'kickstarter.com', 'indiegogo.com',
}

JOB_PATHS = [
    'volunteer', 'jobs', 'careers', 'get-involved',
    'join-us', 'work-with-us', 'volunteers', 'employment',
    'positions', 'apply', 'about/volunteer',
    'about/careers', 'about/jobs', 'opportunities',
    'live-here', 'membership', 'participate',
]

JOB_KW = ['volunteer', 'job', 'apply', 'position', 'career', 'role',
          'opening', 'hiring', 'join our team', 'work with us', 'internship',
          'apprenticeship', 'we are looking for', 'seeking']

# Patterns for extracting structured data
EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PRICE_PATTERNS = [
    re.compile(r'(?:€|£|\$|USD|EUR|GBP)\s*(\d+(?:[.,]\d{2})?)\s*(?:per\s*night|/night|nightly|per\s*person|/person|per\s*day|/day)', re.I),
    re.compile(r'(\d+(?:[.,]\d{2})?)\s*(?:€|£|\$|USD|EUR|GBP)\s*(?:per\s*night|/night|nightly|per\s*person|/person|per\s*day|/day)', re.I),
    re.compile(r'(?:€|£|\$)\s*(\d+(?:[.,]\d{2})?)\s*(?:–|-|to)\s*(?:€|£|\$)?\s*(\d+(?:[.,]\d{2})?)', re.I),
    re.compile(r'(\d+)\s*(?:€|£|\$|USD|EUR)\s*(?:per\s*night|/night|nightly)', re.I),
    re.compile(r'price\s*(?:from|starts?\s*at)?\s*:?\s*(?:€|£|\$)?\s*(\d+(?:[.,]\d{2})?)', re.I),
    re.compile(r'(?:from|starts?\s*at)\s*(?:€|£|\$)?\s*(\d+(?:[.,]\d{2})?)\s*(?:per\s*night|/night|nightly|per\s*person|/person)', re.I),
    re.compile(r'(\d+(?:[.,]\d{2})?)\s*(?:per\s*night|/night|nightly|per\s*person|/person|per\s*day|/day)', re.I),
    re.compile(r'tarif\s*:?\s*(?:€|£|\$)?\s*(\d+(?:[.,]\d{2})?)', re.I),
    re.compile(r'rate\s*:?\s*(?:€|£|\$)?\s*(\d+(?:[.,]\d{2})?)', re.I),
]
SKILLS_PATTERNS = [
    re.compile(r'(?:skills?\s*(?:needed|required|desired|preferred)|required\s+skills?|key\s+skills?)\s*:?\s*([^\n.]{10,200})', re.I),
    re.compile(r'(?:qualifications?\s*(?:needed|required|desired|preferred))\s*:?\s*([^\n.]{10,200})', re.I),
    re.compile(r'(?:requirements?\s*:)\s*([^\n.]{10,200})', re.I),
    re.compile(r'(?:experience\s*(?:needed|required|desired|preferred))\s*:?\s*([^\n.]{10,200})', re.I),
    re.compile(r'(?:must\s+have|should\s+have)\s*:?\s*([^\n.]{10,200})', re.I),
]
COMMITMENT_PATTERNS = [
    re.compile(r'(?:commitment|duration|time\s*commitment|length\s*of\s*stay|minimum\s*stay)\s*:?\s*([^\n.]{5,200})', re.I),
    re.compile(r'(\d+\s*(?:weeks?|months?|days?|hours?|hours\s*per\s*week|hrs?/wk))', re.I),
    re.compile(r'(?:minimum|at\s*least)\s*(\d+\s*(?:weeks?|months?|days?))', re.I),
    re.compile(r'(?:short[- ]term|long[- ]term|part[- ]time|full[- ]time|flexible\s*hours?)', re.I),
]
DATE_PATTERNS = [
    re.compile(r'(?:start\s*date|begins?|starts?)\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})', re.I),
    re.compile(r'(?:end\s*date|ends?|finishes?)\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})', re.I),
    re.compile(r'(?:deadline|apply\s*by|applications?\s*close)\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})', re.I),
]
REMOTE_PATTERNS = [
    re.compile(r'\b(?:remote\s*(?:work|position|job|opportunity|volunteer)|work\s*from\s*home|telecommute|fully\s*remote|100%\s*remote)\b', re.I),
    re.compile(r'\b(?:virtual\s*(?:volunteer|internship|opportunity)|online\s*(?:volunteer|internship|opportunity))\b', re.I),
]

_opener = urllib.request.build_opener()
_opener.addheaders = [(
    'User-Agent',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
)]


class TextExtractor(HTMLParser):
    SKIP_TAGS = {'script', 'style', 'nav', 'footer', 'header', 'aside', 'menu', 'noscript', 'svg', 'form'}
    SKIP_CLASSES = {'sidebar', 'menu', 'navigation', 'navbar', 'nav-menu', 'main-nav',
                    'breadcrumb', 'breadcrumbs', 'top-bar', 'topbar', 'site-header',
                    'site-footer', 'page-header', 'page-footer', 'mobile-nav',
                    'hamburger', 'social', 'social-links', 'social-icons',
                    'cookie', 'cookie-banner', 'popup', 'modal', 'search-form',
                    'wp-sidebar', 'widget-area', 'secondary', 'masthead',
                    'primary-menu', 'main-menu', 'sub-menu', 'footer-widgets',
                    'copyright', 'legal', 'site-info', 'skip-link', 'screen-reader'}
    SKIP_IDS = {'sidebar', 'navbar', 'header', 'footer', 'menu', 'navigation',
                'primary-menu', 'main-menu', 'site-header', 'site-footer'}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self.skip_depth = 0
        self._skip_stack = []

    def handle_starttag(self, tag, attrs):
        should_skip = False
        if tag in self.SKIP_TAGS:
            should_skip = True
        else:
            attrs_dict = dict(attrs)
            cls = (attrs_dict.get('class') or '').lower()
            id_val = (attrs_dict.get('id') or '').lower()
            role = (attrs_dict.get('role') or '').lower()
            if role in ('navigation', 'banner', 'complementary', 'search'):
                should_skip = True
            elif any(sc in cls for sc in self.SKIP_CLASSES):
                should_skip = True
            elif any(sid in id_val for sid in self.SKIP_IDS):
                should_skip = True
        if should_skip:
            self.skip_depth += 1
            self._skip_stack.append(tag)

    def handle_endtag(self, tag):
        if self.skip_depth > 0 and self._skip_stack and self._skip_stack[-1] == tag:
            self.skip_depth -= 1
            self._skip_stack.pop()
        elif self.skip_depth > 0 and tag in self.SKIP_TAGS:
            # Mismatched but still decrement
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, data):
        if self.skip_depth <= 0:
            s = data.strip()
            if s:
                self.chunks.append(s)

    def get_text(self):
        return re.sub(r'\s+', ' ', ' '.join(self.chunks)).strip()


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._in_a = False
        self._current_text = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._in_a = True
            self._current_text = ''
            for k, v in attrs:
                if k == 'href' and v:
                    self._current_href = v

    def handle_data(self, data):
        if self._in_a:
            self._current_text += data

    def handle_endtag(self, tag):
        if tag == 'a' and self._in_a:
            self._in_a = False
            text = self._current_text.strip()
            if text and hasattr(self, '_current_href'):
                self.links.append((text, self._current_href))

    def get_links(self):
        return self.links


def is_blacklisted(url):
    if not url:
        return True
    try:
        parsed = urlparse(url if url.startswith('http') else f'https://{url}')
        domain = parsed.netloc.lower().lstrip('www.')
        if any(domain.endswith(bd) or domain == bd for bd in DOMAIN_BLACKLIST):
            return True
    except Exception:
        pass
    return False


import socket

def fetch(url, timeout=TIMEOUT):
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        resp = _opener.open(url, timeout=timeout)
        data = resp.read(timeout * 1024).decode('utf-8', errors='replace')
        socket.setdefaulttimeout(old_timeout)
        return resp.status, data, resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, None, url
    except Exception:
        return -1, None, url


def discover_job_page(base_url):
    """Find the job/volunteer page on a website."""
    if is_blacklisted(base_url):
        return None, None
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url
    base_url = base_url.rstrip('/')
    # Check all paths for maximum accuracy — these orgs all previously had job pages
    for p in JOB_PATHS:
        status, html, final = fetch(f"{base_url}/{p}", timeout=5)
        if status == 200 and html and len(html) > 500:
            low = html.lower()
            if any(k in low for k in JOB_KW):
                return final, html
    return None, None


def clean_text(text):
    """Remove nav artifacts and clean text."""
    text = re.sub(r'\[LINK:[^\]]+\]', '', text)
    # Remove common nav/boilerplate phrases
    nav_phrases = [
        r'Skip to (?:Content|Main Content|Navigation)',
        r'Open Menu|Close Menu|Toggle Menu|Toggle Navigation',
        r'top of page|Back to top|Scroll to top',
        r'Home\s*About\s*Contact',
        r'Copyright \d{4}',
        r'All rights reserved',
        r'Privacy Policy|Terms of Service|Terms & Conditions',
        r'Follow us on|Share this|Subscribe to',
        r'Link to (?:X|Facebook|Instagram|YouTube|TikTok|Pinterest|LinkedIn)',
        r'This site uses cookies',
    ]
    for pattern in nav_phrases:
        text = re.sub(pattern, '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[|·–—\s]+', '', text).strip()
    return text


def extract_skills(text):
    """Extract skills/requirements from text."""
    for pat in SKILLS_PATTERNS:
        m = pat.search(text)
        if m:
            skills = m.group(1).strip().rstrip(',.;:')
            if 10 < len(skills) < 300:
                return skills[:200]
    return None


def extract_commitment(text):
    """Extract time commitment from text."""
    for pat in COMMITMENT_PATTERNS:
        m = pat.search(text)
        if m:
            commitment = m.group(0).strip()
            if 3 < len(commitment) < 200:
                return commitment[:100]
    return None


def extract_dates(text):
    """Extract start and end dates."""
    start_date = None
    end_date = None
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            date_str = m.group(1).strip()
            try:
                from dateutil import parser as date_parser
                parsed_date = date_parser.parse(date_str, fuzzy=True)
                if 'start' in pat.pattern.lower() or 'begin' in pat.pattern.lower():
                    start_date = parsed_date.isoformat()
                elif 'end' in pat.pattern.lower() or 'finish' in pat.pattern.lower():
                    end_date = parsed_date.isoformat()
            except Exception:
                pass
    return start_date, end_date


def extract_email(text, html):
    """Extract application/contact email."""
    emails = EMAIL_RE.findall(html or '')
    # Filter out generic emails
    generic = {'info@', 'contact@', 'admin@', 'support@', 'office@', 'hello@', 'webmaster@'}
    specific = [e for e in emails if not any(e.lower().startswith(g) for g in generic)]
    if specific:
        return specific[0]
    if emails:
        return emails[0]
    return None


def extract_remote(text):
    """Check if remote work is mentioned."""
    for pat in REMOTE_PATTERNS:
        if pat.search(text):
            return True
    return False


def extract_price(text, html):
    """Extract price information from stay pages."""
    for pat in PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            price = m.group(0).strip()
            if len(price) < 200:
                return price
    # Also check for price tables/lists in HTML
    price_matches = re.findall(r'(?:€|£|\$|USD|EUR|GBP)\s*\d+(?:[.,]\d{2})?(?:\s*[-–]\s*(?:€|£|\$|USD|EUR|GBP)?\s*\d+(?:[.,]\d{2})?)?', text)
    if price_matches:
        return ', '.join(price_matches[:5])
    return None


def extract_stay_type(text, html):
    """Determine stay type from content."""
    low = text.lower()
    types = []
    if any(x in low for x in ['camping', 'camp site', 'pitch your tent']):
        types.append('camping')
    if any(x in low for x in ['glamping', 'safari tent', 'luxury tent', 'yurt']):
        types.append('glamping')
    if any(x in low for x in ['guest room', 'guest house', 'bed and breakfast', 'bnb', 'chambre']):
        types.append('guest room')
    if any(x in low for x in ['dormitory', 'shared room', 'hostel']):
        types.append('shared room')
    if any(x in low for x in ['cabin', 'cottage', 'chalet', 'tiny house']):
        types.append('cabin')
    if any(x in low for x in ['private room', 'private accommodation']):
        types.append('private room')
    if any(x in low for x in ['apartment', 'flat', 'studio']):
        types.append('apartment')
    if any(x in low for x in ['retreat', 'retreat center']):
        types.append('retreat')
    if any(x in low for x in ['eco-lodge', 'ecolodge', 'lodge']):
        types.append('eco-lodge')
    if not types:
        return 'accommodation'
    return ', '.join(types)


def extract_job_listings_enhanced(html, org_name, page_url):
    """Extract job listings with structured details."""
    ext = TextExtractor()
    try:
        ext.feed(html[:300000])
    except Exception:
        pass
    text = ext.get_text()
    if len(text) < 200:
        return []

    text = clean_text(text)
    raw_blocks = re.split(r'(?=\b[A-Z][A-Z\s&\-/,]{5,80}[A-Z]\b)', text)
    job_terms = ['volunteer', 'intern', 'apprentice', 'position', 'opening',
                 'job', 'role', 'opportunity', 'hiring', 'apply', 'seeking',
                 'work exchange', 'wwoof', 'help wanted']
    listings = []

    for block in raw_blocks:
        block = block.strip()
        if len(block) < 100:
            continue
        score = sum(1 for t in job_terms if t in block.lower())
        if score >= 2:
            lines = re.split(r'[.!?]\s+', block)
            title = lines[0][:150].strip()
            title = re.sub(r'\[LINK:[^\]]+\]', '', title)
            title = clean_text(title)
            if len(title) < 5:
                title = f"Opportunity at {org_name}"

            low = block.lower()
            role = 'volunteer'
            if any(x in low for x in ['intern', 'internship']):
                role = 'internship'
            elif any(x in low for x in ['apprentice', 'apprenticeship']):
                role = 'apprenticeship'
            elif any(x in low for x in ['salary', 'full-time', 'full time', 'paid', 'compensation', 'wage']):
                role = 'paid_job'

            skills = extract_skills(block)
            commitment = extract_commitment(block)
            start_date, end_date = extract_dates(block)
            email = extract_email(block, html)
            remote = extract_remote(block)

            listings.append({
                'title': title,
                'description': extract_description(block),
                'role': role,
                'skills_needed': skills,
                'commitment': commitment,
                'start_date': start_date,
                'end_date': end_date,
                'remote_options': remote,
                'application_email': email,
                'source_url': page_url,
            })

    if not listings:
        score = sum(1 for t in job_terms if t in text.lower())
        if score >= 3 and len(text) > 300:
            sentences = re.split(r'[.!?]\s+', text)
            title = sentences[0][:150] if sentences else f"Opportunities at {org_name}"
            title = clean_text(title)
            skills = extract_skills(text)
            commitment = extract_commitment(text)
            start_date, end_date = extract_dates(text)
            email = extract_email(text, html)
            remote = extract_remote(text)

            listings.append({
                'title': title,
                'description': extract_description(text),
                'role': 'volunteer',
                'skills_needed': skills,
                'commitment': commitment,
                'start_date': start_date,
                'end_date': end_date,
                'remote_options': remote,
                'application_email': email,
                'source_url': page_url,
            })

    return listings


def extract_description(text, title=None):
    """Extract a clean 2-3 sentence description from raw page text."""
    text = clean_text(text)
    # Remove the page title from the start if present
    if title:
        title_clean = clean_text(title)
        if text.startswith(title_clean):
            text = text[len(title_clean):].strip()
        # Also try without special chars
        title_simple = re.sub(r'[^\w\s]', '', title_clean).lower()
        text_simple = re.sub(r'[^\w\s]', '', text[:200]).lower()
        if text_simple.startswith(title_simple):
            text = text[len(title_simple):].strip(' —|-–·')
    # Remove leading separators
    text = re.sub(r'^[—–\-|·\s]+', '', text).strip()

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    good_sentences = []
    for s in sentences:
        s = s.strip()
        if len(s) < 25:
            continue
        low = s.lower()
        words = s.split()
        # Skip nav-like fragments
        skip_words = [
            'menu', 'sidebar', 'footer', 'header', 'navigation',
            'skip to', 'scroll', 'cookie', 'subscribe', 'follow us',
            'all rights reserved', 'copyright', 'privacy policy',
            'link to', 'share this', 'back to top',
            'home about contact', 'search for', 'log in', 'sign up',
            'register', 'cart', 'checkout', 'primary navigation',
            'main content', 'toggle', 'open menu', 'close menu',
        ]
        if any(sw in low for sw in skip_words):
            continue
        # Skip sentences that are just concatenated nav links
        # (many capitalized words, very few lowercase connectors = likely nav)
        cap_words = sum(1 for w in words if w and w[0].isupper())
        if cap_words > len(words) * 0.7 and len(words) > 5:
            continue
        # Skip sentences with pipe separators (nav breadcrumbs)
        if s.count('|') > 2:
            continue
        # Skip sentences that are just domain/page names
        if re.match(r'^[\w\s\-]+\.(com|org|net|de|io|uk|co)\b', s, re.I):
            continue
        # Skip "Home About Contact" style nav
        if re.match(r'^(Home|About|Contact|Blog|Events|Gallery|Shop)\s+', s):
            continue
        # This looks like a real sentence
        good_sentences.append(s)
        if len(good_sentences) >= 3:
            break

    result = ' '.join(good_sentences)
    if len(result) < 50:
        # Fallback: try to find any sentence with job-related keywords
        for s in sentences:
            s = s.strip()
            low = s.lower()
            if len(s) > 40 and any(kw in low for kw in ['volunteer', 'opportunity', 'position', 'help', 'work', 'stay', 'accommodation', 'retreat', 'community']):
                result = s
                break
    if len(result) < 50:
        # Last resort: take first 300 chars of cleaned text, skipping title
        result = text[:300]
    return result[:500]


def analyze_booking_enhanced(html, url):
    """Enhanced booking analysis with price extraction."""
    has_form = bool(re.search(r'<form\b', html, re.I))
    has_iframe = bool(re.search(r'<iframe\b', html, re.I))
    has_email = bool(EMAIL_RE.search(html))
    has_phone = bool(re.search(r'[\+\(]?[0-9]{1,4}[\)]?[-.\s]?[0-9]{1,4}[-.\s]?[0-9\s]{4,}', html))
    has_calendar = any(x in html.lower() for x in ['calendly', 'schedule', 'pick a date', 'availability-calendar'])
    ext_links = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html):
        href = m.group(1).lower()
        if any(x in href for x in ['booking.com', 'airbnb', 'expedia', 'hotels.com',
                                     'checkfront', 'rezdy', 'fareharbor', 'peek',
                                     'stripe', 'squareup', 'eventbrite']):
            ext_links.append(href)

    ext = TextExtractor()
    try:
        ext.feed(html[:250000])
    except Exception:
        pass
    text = ext.get_text()
    text = clean_text(text)
    low = text.lower()
    kw_score = sum(1 for kw in ['book now', 'reserve', 'check availability',
                                'check-in', 'check-out', 'nightly rate', 'per night',
                                'book your stay', 'book a room', 'availability'
                                ] if kw in low)

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

    price = extract_price(text, html)
    stay_type = extract_stay_type(text, html)

    return btype, analysis, price, stay_type, text


def claim_batch_jobs(conn, batch_size):
    """Claim a batch of orgs for job re-scraping."""
    cur = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')
    cur.execute('''
        SELECT DISTINCT o.id, o.name, o.website
        FROM organizations o
        JOIN volunteer_opportunities v ON v.organization_id = o.id
        WHERE o.website IS NOT NULL AND o.website != ''
          AND o.jobs_being_processed_since IS NULL
          AND o.jobs_rescraped IS NULL
        ORDER BY o.id
        LIMIT ?
    ''', (batch_size,))
    rows = cur.fetchall()
    now = datetime.now().isoformat()
    for org_id, _, _ in rows:
        cur.execute('UPDATE organizations SET jobs_being_processed_since = ? WHERE id = ?', (now, org_id))
    conn.commit()
    return rows


def claim_batch_stays(conn, batch_size):
    """Claim a batch of stays for re-scraping."""
    cur = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')
    cur.execute('''
        SELECT s.id, s.organization_id, s.booking_url, o.name, o.website
        FROM stays s
        JOIN organizations o ON s.organization_id = o.id
        WHERE s.booking_url IS NOT NULL AND s.booking_url != ''
          AND s.being_processed_since IS NULL
          AND (s.rescraped IS NULL OR s.rescraped = 0)
        ORDER BY s.id
        LIMIT ?
    ''', (batch_size,))
    rows = cur.fetchall()
    now = datetime.now().isoformat()
    for stay_id, _, _, _, _ in rows:
        cur.execute('UPDATE stays SET being_processed_since = ? WHERE id = ?', (now, stay_id))
    conn.commit()
    return rows


def process_job_org(conn, org_id, name, website):
    """Re-scrape a single org's job page with enhanced extraction."""
    cur = conn.cursor()
    job_url, job_html = discover_job_page(website)
    if job_url and job_html:
        listings = extract_job_listings_enhanced(job_html, name, job_url)
        if listings:
            cur.execute('DELETE FROM volunteer_opportunities WHERE organization_id = ?', (org_id,))
            for li in listings:
                cur.execute('''
                    INSERT INTO volunteer_opportunities
                    (organization_id, title, description, role, skills_needed,
                     commitment, start_date, end_date, remote_options,
                     application_email, source_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (org_id, li['title'], li['description'], li['role'],
                      li['skills_needed'], li['commitment'],
                      li['start_date'], li['end_date'],
                      li['remote_options'], li['application_email'],
                      li['source_url'], datetime.now().isoformat()))
            conn.commit()
            return len(listings)
    # Mark as rescraped even if no new data
    cur.execute('UPDATE organizations SET jobs_rescraped = 1, jobs_being_processed_since = NULL WHERE id = ?', (org_id,))
    conn.commit()
    return 0


def process_stay(conn, stay_id, org_id, booking_url, org_name, org_website):
    """Re-scrape a single stay with enhanced extraction."""
    cur = conn.cursor()
    url = booking_url or org_website
    if not url:
        cur.execute('UPDATE stays SET being_processed_since = NULL, rescraped = 1 WHERE id = ?', (stay_id,))
        conn.commit()
        return False

    status, html, final_url = fetch(url)
    if status != 200 or not html:
        cur.execute('UPDATE stays SET being_processed_since = NULL, rescraped = 1 WHERE id = ?', (stay_id,))
        conn.commit()
        return False

    btype, analysis, price, stay_type, text = analyze_booking_enhanced(html, final_url)

    # Extract a better title from the page
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
    new_title = None
    if title_match:
        raw_title = title_match.group(1).strip()
        raw_title = re.sub(r'\s*[|–—-]\s*.*$', '', raw_title).strip()
        if 5 < len(raw_title) < 100:
            new_title = raw_title

    # Clean description
    desc = clean_text(text[:2000])

    cur.execute('''
        UPDATE stays SET
            title = ?, description = ?, stay_type = ?, price_info = ?,
            booking_type = ?, booking_analysis = ?, booking_url = ?,
            being_processed_since = NULL, rescraped = 1
        WHERE id = ?
    ''', (new_title or f"Stay at {org_name}", desc, stay_type, price,
          btype, str(analysis), final_url, stay_id))
    conn.commit()
    return True


def reset_stale(conn, table, minutes=10):
    """Reset being_processed_since for stale entries."""
    cur = conn.cursor()
    cutoff = datetime.now().isoformat()
    if table == 'organizations':
        cur.execute('''
            UPDATE organizations SET jobs_being_processed_since = NULL
            WHERE jobs_being_processed_since IS NOT NULL
              AND jobs_being_processed_since < datetime('now', '-{} minutes')
        '''.format(minutes))
    else:
        cur.execute('''
            UPDATE stays SET being_processed_since = NULL
            WHERE being_processed_since IS NOT NULL
              AND being_processed_since < datetime('now', '-{} minutes')
        '''.format(minutes))
    conn.commit()


def worker_jobs(worker_id, conn):
    """Worker process for job re-scraping."""
    while True:
        rows = claim_batch_jobs(conn, BATCH_SIZE)
        if not rows:
            print(f"[W{worker_id}] No more jobs to process")
            break
        for org_id, name, website in rows:
            try:
                n = process_job_org(conn, org_id, name, website)
                if n:
                    print(f"[W{worker_id}] Jobs: {name[:40]} -> {n} listings")
            except Exception as e:
                print(f"[W{worker_id}] Error processing org {org_id}: {e}")
                try:
                    cur = conn.cursor()
                    cur.execute('UPDATE organizations SET jobs_being_processed_since = NULL WHERE id = ?', (org_id,))
                    conn.commit()
                except:
                    pass
        reset_stale(conn, 'organizations')


def worker_stays(worker_id, conn):
    """Worker process for stay re-scraping."""
    while True:
        rows = claim_batch_stays(conn, BATCH_SIZE)
        if not rows:
            print(f"[W{worker_id}] No more stays to process")
            break
        for stay_id, org_id, booking_url, org_name, org_website in rows:
            try:
                updated = process_stay(conn, stay_id, org_id, booking_url, org_name, org_website)
                if updated:
                    print(f"[W{worker_id}] Stay: {org_name[:40]} -> updated")
            except Exception as e:
                print(f"[W{worker_id}] Error processing stay {stay_id}: {e}")
                try:
                    cur = conn.cursor()
                    cur.execute('UPDATE stays SET being_processed_since = NULL, rescraped = 1 WHERE id = ?', (stay_id,))
                    conn.commit()
                except:
                    pass
        reset_stale(conn, 'stays')


def main():
    import multiprocessing

    mode = sys.argv[1] if len(sys.argv) > 1 else 'both'
    num_workers = int(sys.argv[2]) if len(sys.argv) > 2 else NUM_WORKERS

    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    cur = conn.cursor()

    # Add necessary columns
    try:
        cur.execute('ALTER TABLE organizations ADD COLUMN jobs_rescraped INTEGER')
    except:
        pass
    try:
        cur.execute('ALTER TABLE stays ADD COLUMN being_processed_since DATETIME')
    except:
        pass
    conn.commit()

    # Reset any stale locks
    cur.execute('UPDATE organizations SET being_processed_since = NULL WHERE being_processed_since IS NOT NULL')
    cur.execute('UPDATE stays SET being_processed_since = NULL WHERE being_processed_since IS NOT NULL')
    conn.commit()

    # Count remaining
    if mode in ('jobs', 'both'):
        cur.execute('''
            SELECT COUNT(DISTINCT o.id) FROM organizations o
            JOIN volunteer_opportunities v ON v.organization_id = o.id
            WHERE o.website IS NOT NULL AND o.website != ''
              AND o.jobs_rescraped IS NULL
        ''')
        total_jobs = cur.fetchone()[0]
        print(f"Orgs to re-scrape for jobs: {total_jobs}")

    if mode in ('stays', 'both'):
        cur.execute('SELECT COUNT(*) FROM stays WHERE booking_url IS NOT NULL AND booking_url != ""')
        total_stays = cur.fetchone()[0]
        print(f"Stays to re-scrape: {total_stays}")

    processes = []
    if mode in ('jobs', 'both'):
        for i in range(num_workers):
            p = multiprocessing.Process(target=worker_jobs, args=(i, conn))
            p.start()
            processes.append(p)
            time.sleep(0.5)

    if mode in ('stays', 'both'):
        for i in range(num_workers):
            p = multiprocessing.Process(target=worker_stays, args=(i + 100, conn))
            p.start()
            processes.append(p)
            time.sleep(0.5)

    # Monitor progress
    try:
        while any(p.is_alive() for p in processes):
            time.sleep(30)
            cur.execute('''
                SELECT COUNT(DISTINCT o.id) FROM organizations o
                JOIN volunteer_opportunities v ON v.organization_id = o.id
                WHERE o.jobs_rescraped = 1
            ''')
            jobs_done = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM stays WHERE being_processed_since IS NULL AND price_info IS NOT NULL')
            stays_priced = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM volunteer_opportunities WHERE skills_needed IS NOT NULL AND skills_needed != ""')
            jobs_skills = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM volunteer_opportunities WHERE commitment IS NOT NULL AND commitment != ""')
            jobs_commit = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM volunteer_opportunities WHERE application_email IS NOT NULL AND application_email != ""')
            jobs_email = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM stays WHERE stay_type != "accommodation"')
            stays_typed = cur.fetchone()[0]
            print(f"\n--- Progress ---")
            print(f"  Jobs re-scraped: {jobs_done}")
            print(f"  Jobs with skills: {jobs_skills}")
            print(f"  Jobs with commitment: {jobs_commit}")
            print(f"  Jobs with email: {jobs_email}")
            print(f"  Stays with price: {stays_priced}")
            print(f"  Stays with specific type: {stays_typed}")
    except KeyboardInterrupt:
        print("\nStopping workers...")
        for p in processes:
            p.terminate()
    finally:
        for p in processes:
            p.join(timeout=5)
        conn.close()
        print("Done.")


if __name__ == '__main__':
    main()
